"""Durable owner messages: FIFO follow-ups and explicit same-turn steering."""
from __future__ import annotations

import asyncio
import time
import uuid

from .rpc import RpcError, CompatibilityError


class SessionBusy(ValueError):
    """No turn was submitted; it is safe to leave a queued message waiting."""


class MessageQueue:
    def __init__(self, service):
        self.s = service
        self.inflight = set()
        self.tasks = set()
        with self.s.state.lock, self.s.state.db:
            self.s.state.db.execute('''CREATE TABLE IF NOT EXISTS message_queue (
              id TEXT PRIMARY KEY, host TEXT, session_group TEXT, thread TEXT,
              chat TEXT, owner TEXT, prompt TEXT, mode TEXT, model TEXT, effort TEXT,
              status TEXT, job TEXT, message_id TEXT, error TEXT DEFAULT '', created REAL)''')
            # A crash after the RPC write is ambiguous. Never replay it.
            self.s.state.db.execute("UPDATE message_queue SET status='unknown',error='后台重启，发送结果未确认；没有自动重发' WHERE status='dispatching'")

    def group(self, host):
        return 'supervisor' if host == 'supervisor' else self.s.config.hosts[host].session_group

    def pause_key(self, host, thread):
        return 'queue_paused:' + self.group(host) + ':' + thread

    def pause(self, host, thread, reason):
        self.s.state.put(self.pause_key(host, thread), reason)
        self.s.changed()

    def items(self, chat):
        with self.s.state.lock:
            rows = self.s.state.db.execute('''SELECT * FROM message_queue WHERE chat=?
              AND (status IN ('queued','dispatching','unknown','failed') OR created>?)
              ORDER BY created,rowid''', (chat, time.time()-3600)).fetchall()
        result = []
        for r in rows:
            item = {k:r[k] for k in ('id','host','thread','prompt','mode','model','effort','status','job','message_id','error')}
            item['prompt'] = self.s.redact(item['prompt'])
            item['paused'] = self.s.state.get(self.pause_key(r['host'],r['thread']), '')
            result.append(item)
        return result[-100:]

    def get_owned(self, ident, chat, owner):
        with self.s.state.lock:
            row = self.s.state.db.execute('SELECT * FROM message_queue WHERE id=?',(ident,)).fetchone()
        if not row or row['chat'] != chat or row['owner'] != owner:
            raise ValueError('消息不属于当前账号')
        return dict(row)

    def update(self, ident, status, error='', job=None):
        with self.s.state.lock, self.s.state.db:
            self.s.state.db.execute('UPDATE message_queue SET status=?,error=?,job=COALESCE(?,job) WHERE id=?',
                                    (status, self.s.redact(error)[:400], job, ident))
        self.s.changed()

    async def enqueue(self, host, thread, prompt, chat, owner, model=None, effort=None):
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>50000:
            raise ValueError('任务内容不能为空，也不能超过 50000 字符')
        # A running owner job has already validated this thread. Appending to its
        # durable queue must not depend on a second history/database read.
        owned_active=any(j['host']==host and j['thread']==thread and j['chat']==chat and j['owner']==owner
                         for j in self.s.state.jobs(active=True))
        if not owned_active:await self.s.metadata(host,thread)
        await self.s.validate_model(host,thread,model,effort)
        return self.insert(host,thread,prompt,chat,owner,'queue',model,effort)

    def insert(self, host, thread, prompt, chat, owner, mode, model=None, effort=None, job=None):
        ident=uuid.uuid4().hex[:12]
        with self.s.state.lock, self.s.state.db:
            count=self.s.state.db.execute("SELECT count(*) FROM message_queue WHERE session_group=? AND thread=? AND status IN ('queued','dispatching','unknown')",(self.group(host),thread)).fetchone()[0]
            if count>=30:raise ValueError('该会话已有 30 条待处理消息，请先处理或取消部分消息')
            self.s.state.db.execute('''INSERT INTO message_queue
              (id,host,session_group,thread,chat,owner,prompt,mode,model,effort,status,job,message_id,created)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (ident,host,self.group(host),thread,chat,owner,prompt,mode,model,effort,
               'queued' if mode=='queue' else 'dispatching',job,str(uuid.uuid4()),time.time()))
        self.s.changed()
        return self.get_owned(ident,chat,owner)

    def cancel(self, ident, chat, owner):
        self.get_owned(ident,chat,owner)
        with self.s.state.lock, self.s.state.db:
            changed=self.s.state.db.execute("UPDATE message_queue SET status='cancelled' WHERE id=? AND status IN ('queued','failed')",(ident,)).rowcount
        if not changed:raise ValueError('该消息已开始发送或结果尚未确认，不能当作未发送消息取消')
        self.s.changed()
        return {'cancelled':True}

    async def steer(self, job_id, expected_turn, prompt, chat, owner, queued=None):
        job=self.s.owned_job(job_id,owner,chat)
        if job['status'] not in ('running','waiting') or not expected_turn or job['turn']!=expected_turn:
            raise ValueError('当前轮次已改变，未发送引导；请重新查看状态或使用排队发送')
        if queued:
            entry=self.get_owned(queued,chat,owner)
            if entry['host']!=job['host'] or entry['thread']!=job['thread']:raise ValueError('排队消息不属于当前机器和会话')
            with self.s.state.lock,self.s.state.db:
                claimed=self.s.state.db.execute("UPDATE message_queue SET status='dispatching',mode='steer',job=? WHERE id=? AND status='queued'",(job_id,queued)).rowcount
            if not claimed:raise ValueError('这条消息已经开始发送，不能重复引导')
            prompt=entry['prompt'];self.s.changed()
        else:
            if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>50000:raise ValueError('引导消息不能为空或超过 50000 字符')
            entry=self.insert(job['host'],job['thread'],prompt,chat,owner,'steer',job=job_id)
        try:
            c=await self.s.get_client(job['host'])
            # expectedTurnId makes a completion/next-turn race fail closed.
            await c.request('turn/steer', {'threadId':job['thread'],'expectedTurnId':expected_turn,
                'clientUserMessageId':entry['message_id'],
                'input':[{'type':'text','text':prompt,'text_elements':[]}]})
        except RpcError as error:
            self.update(entry['id'],'failed',str(error));raise
        except Exception:
            self.update(entry['id'],'unknown','引导发送结果未确认；没有自动重发');raise
        self.update(entry['id'],'sent')
        return self.get_owned(entry['id'],chat,owner)

    async def dispatch_one(self, entry):
        key=(entry['session_group'],entry['thread'])
        try:
            with self.s.state.lock,self.s.state.db:
                claimed=self.s.state.db.execute("UPDATE message_queue SET status='dispatching' WHERE id=? AND status='queued'",(entry['id'],)).rowcount
            if not claimed:return
            self.s.changed()
            try:
                job=await self.s.submit(entry['host'],entry['thread'],entry['prompt'],entry['chat'],entry['owner'],
                    model=entry['model'],effort=entry['effort'],job_id=entry['id'],client_message_id=entry['message_id'])
            except SessionBusy:
                self.update(entry['id'],'queued');return
            except CompatibilityError as error:
                # All turn/start writes occur after create_job. A preflight failure
                # without this job ID is known not to have submitted a new turn.
                with self.s.state.lock:
                    started=self.s.state.db.execute('SELECT id FROM jobs WHERE id=?',(entry['id'],)).fetchone()
                self.update(entry['id'],'unknown' if started else 'failed',str(error))
                self.pause(entry['host'],entry['thread'],'原生接口异常，队列已暂停');return
            except (ValueError,RpcError) as error:
                self.update(entry['id'],'failed',str(error));self.pause(entry['host'],entry['thread'],'上一条消息未能发送，请检查后继续队列');return
            except Exception as error:
                self.update(entry['id'],'unknown',str(error));self.pause(entry['host'],entry['thread'],'发送结果未确认；请核查任务，不会自动重发');return
            self.update(entry['id'],'sent',job=job['id'])
        finally:self.inflight.discard(key)

    async def tick(self):
        with self.s.state.lock:
            rows=[dict(r) for r in self.s.state.db.execute("SELECT * FROM message_queue WHERE mode='queue' AND status IN ('queued','dispatching','unknown') ORDER BY created,rowid")]
        seen=set()
        for entry in rows:
            key=(entry['session_group'],entry['thread'])
            if key in seen:continue
            seen.add(key)
            if entry['status']!='queued' or key in self.inflight or self.s.state.get(self.pause_key(entry['host'],entry['thread'])):continue
            if any((j['session_group'],j['thread'])==key for j in self.s.state.jobs(active=True)):continue
            self.inflight.add(key)
            task=asyncio.create_task(self.dispatch_one(entry));self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def run(self):
        try:
            while not self.s.stopping:
                await self.tick();await asyncio.sleep(.5)
        finally:
            for task in self.tasks:task.cancel()
            await asyncio.gather(*self.tasks,return_exceptions=True)
