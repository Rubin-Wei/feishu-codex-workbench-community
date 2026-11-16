import { BadRequestException, ConflictException, HttpException, Inject, Injectable,
  NotFoundException, ServiceUnavailableException, UnauthorizedException } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { and, asc, count, eq, inArray, lt, lte, sql } from 'drizzle-orm';
import {createHash} from 'node:crypto';
import { workbenchCommand as commands, workbenchSnapshot as snapshots,
  workbenchLogin as attempts } from '@server/database/schema';
import { COMMAND_ACTIONS, type AgentRequest, type AgentResponse, type CommandRequest,
  type JsonObject, type LoginRequest, type CacheAck } from '@shared/api.interface';
import type {CachedHistory,LiveReply} from '@shared/workbench';
import { passwordMatches, signSession } from './auth';

@Injectable()
export class WorkbenchService {
  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}

  async login(body: LoginRequest, ip: string): Promise<string> {
    if (!body || typeof body.username !== 'string' || typeof body.password !== 'string' ||
        body.username.length > 100 || body.password.length > 500) throw new BadRequestException('请输入账号密码');
    const now = Date.now();
    const bucket = ip.slice(0, 120) + ':' + Math.floor(now / 900000);
    const [row] = await this.db.insert(attempts).values({ bucket, attempts: 1, expiresAt: now + 86400000 })
      .onConflictDoUpdate({ target: attempts.bucket, set: { attempts: sql`${attempts.attempts} + 1` } })
      .returning({ attempts: attempts.attempts });
    if (row.attempts > 5) throw new HttpException('尝试次数过多，请 15 分钟后再试', 429);
    if (!await passwordMatches(body.username, body.password)) throw new UnauthorizedException('账号或密码不正确');
    await this.db.update(attempts).set({ attempts: 0 }).where(eq(attempts.bucket, bucket));
    return signSession();
  }

  async state(): Promise<JsonObject> {
    const [row] = await this.db.select().from(snapshots).where(eq(snapshots.key, 'agent')).limit(1);
    return row ? { ...JSON.parse(row.payload), online: Date.now() - row.seenAt < 30000, lastSeen: row.seenAt }
      : { online: false, hosts: [], jobs: [], approvals: [] };
  }

  async live(after:number):Promise<LiveReply> {
    const [row]=await this.db.select().from(snapshots).where(eq(snapshots.key,'live')).limit(1);
    return row&&row.seenAt>after?{changed:true,revision:row.seenAt,value:JSON.parse(row.payload)}:{changed:false,revision:after};
  }

  private historyKey(host:string,thread:string):string {
    if(!/^[a-z0-9-]{1,40}$/.test(host||'')||!/^[a-f0-9-]{36}$/.test(thread||''))throw new BadRequestException('会话编号无效');
    return 'h:'+createHash('sha256').update(host+'\0'+thread).digest('hex').slice(0,30);
  }

  async history(host:string,thread:string):Promise<CachedHistory> {
    const [row]=await this.db.select().from(snapshots).where(eq(snapshots.key,this.historyKey(host,thread))).limit(1);
    return row?{cached:true,updatedAt:row.seenAt,value:JSON.parse(row.payload)}:{cached:false};
  }

  async submit(b: CommandRequest): Promise<{ id: string; status: string }> {
    if (!b || !/^[a-f0-9-]{36}$/.test(b.id || '') || !COMMAND_ACTIONS.some(a => a === b.action) ||
        !b.args || typeof b.args !== 'object' || Array.isArray(b.args) || JSON.stringify(b).length > 60000) {
      throw new BadRequestException('操作格式错误');
    }
    if (!(await this.state()).online) throw new ServiceUnavailableException('服务器当前离线，请稍后再提交');
    const [pending] = await this.db.select({ n: count() }).from(commands).where(eq(commands.status, 'pending'));
    if (pending.n > 30) throw new HttpException('请求较多，请稍后重试', 429);
    const args = JSON.stringify(b.args);
    await this.db.insert(commands).values({ requestId: b.id, action: b.action, args, status: 'pending', created: Date.now() })
      .onConflictDoNothing({ target: commands.requestId });
    const [row] = await this.db.select().from(commands).where(eq(commands.requestId, b.id)).limit(1);
    if (row.action !== b.action || row.args !== args) throw new ConflictException('请求编号冲突');
    return { id: b.id, status: row.status };
  }

  async result(id: string): Promise<JsonObject> {
    const [row] = await this.db.select().from(commands).where(eq(commands.requestId, id || '')).limit(1);
    if (!row) throw new NotFoundException('请求不存在');
    return { id: row.requestId, status: row.status, result: row.result ? JSON.parse(row.result) : null };
  }

  async exchange(b: AgentRequest): Promise<AgentResponse> {
    if (!b || JSON.stringify(b).length > 2000000) throw new BadRequestException('Invalid relay payload');
    const now = Date.now();
    const acked: string[] = [];
    const cacheAcked:CacheAck[]=[];
    if(b.live){
      const revision=Number(b.live.revision),payload=JSON.stringify(b.live);
      if(!Number.isSafeInteger(revision)||revision<=0||Buffer.byteLength(payload)>1000000)throw new BadRequestException('Invalid live update');
      await this.db.insert(snapshots).values({key:'live',payload,seenAt:revision})
        .onConflictDoUpdate({target:snapshots.key,set:{payload,seenAt:revision},setWhere:lte(snapshots.seenAt,revision)});
      if(!b.snapshot&&!b.results&&!b.capacity)return {acked,cacheAcked,commands:[]};
    }
    for(const item of (Array.isArray(b.cacheUpdates)?b.cacheUpdates:[]).slice(0,12)){
      if(!/^[a-f0-9]{64}$/.test(item.revision)||!Number.isFinite(item.updatedAt)||!item.value)continue;
      const key=this.historyKey(item.host,item.thread),payload=JSON.stringify(item.value);
      if(Buffer.byteLength(payload)>400000)continue;
      await this.db.insert(snapshots).values({key,payload,seenAt:item.updatedAt})
        .onConflictDoUpdate({target:snapshots.key,set:{payload,seenAt:item.updatedAt},setWhere:lte(snapshots.seenAt,item.updatedAt)});
      cacheAcked.push({host:item.host,thread:item.thread,revision:item.revision});
    }
    for (const r of (Array.isArray(b.results) ? b.results : []).slice(0, 20)) {
      if (!r || typeof r.id !== 'string') continue;
      await this.db.update(commands).set({ status: r.ok ? 'done' : 'failed', result: JSON.stringify(r.value ?? null), completed: now })
        .where(and(eq(commands.requestId, r.id), inArray(commands.status, ['running', 'unknown'])));
      acked.push(r.id);
    }
    if (b.snapshot && typeof b.snapshot === 'object') {
      const payload = JSON.stringify(b.snapshot);
      await this.db.insert(snapshots).values({ key: 'agent', payload, seenAt: now })
        .onConflictDoUpdate({ target: snapshots.key, set: { payload, seenAt: now } });
    }
    await this.db.update(commands).set({ status: 'unknown', result: JSON.stringify({ error: '服务器响应尚未确认，未自动重复执行。请查看任务或原会话。' }) })
      .where(and(eq(commands.status, 'running'), lt(commands.claimed, now - 180000)));
    await this.db.update(commands).set({ status: 'failed', result: JSON.stringify({ error: '操作已过期，未执行。' }) })
      .where(and(eq(commands.status, 'pending'), lt(commands.created, now - 120000)));
    const claimed: CommandRequest[] = [];
    const capacity = Math.max(0, Math.min(4, Math.floor(Number(b.capacity) || 0)));
    if (capacity) {
      const pending = await this.db.select({ id: commands.id }).from(commands)
        .where(eq(commands.status, 'pending')).orderBy(asc(commands.created)).limit(capacity);
      for (const candidate of pending) {
        // Compare-and-set: concurrent heartbeats cannot claim a command twice.
        const [row] = await this.db.update(commands).set({ status: 'running', claimed: now })
          .where(and(eq(commands.id, candidate.id), eq(commands.status, 'pending'))).returning();
        if (row) claimed.push({ id: row.requestId, action: row.action, args: JSON.parse(row.args) });
      }
    }
    return { acked, commands: claimed, cacheAcked };
  }
}
