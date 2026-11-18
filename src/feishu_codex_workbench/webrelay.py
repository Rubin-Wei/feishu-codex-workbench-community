"""Outbound-only connection to the owner's private mobile workbench.

Cloud command IDs are persisted locally before execution. A command recovered in
'processing' is never executed again, even if its cloud acknowledgement was lost.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import shlex
import time
import httpx
from .cluster import remote_file, remote_history
from .rpc import RpcError, CompatibilityError
from .readcache import ReadCache, compact_thread
from .accounts import AccountCache
from .filepreview import preview_file

log = logging.getLogger(__name__)

class WebRelay:
    def __init__(self, service):
        self.s = service
        self.tasks = set()
        self.enqueue_lock = asyncio.Lock()
        self.exchange_event = asyncio.Event()
        self.url = os.environ['WORKBENCH_SITE_URL'].rstrip('/')
        self.agent_url = os.getenv('WORKBENCH_AGENT_URL', self.url+'/api/agent')
        headers = {}
        if os.getenv('WORKBENCH_OPENAPI_KEY'):
            headers['Authorization'] = 'Bearer '+os.environ['WORKBENCH_OPENAPI_KEY']
        else:
            headers['Authorization'] = 'Bearer '+os.environ['WORKBENCH_AGENT_SECRET']
            if os.getenv('WORKBENCH_SITE_ACCESS_TOKEN'):
                headers['OAI-Sites-Authorization'] = 'Bearer '+os.environ['WORKBENCH_SITE_ACCESS_TOKEN']
        self.client = httpx.AsyncClient(timeout=35, trust_env=False, headers=headers)
        with self.s.state.lock, self.s.state.db:
            self.s.state.db.execute('CREATE TABLE IF NOT EXISTS web_commands(id TEXT PRIMARY KEY, status TEXT NOT NULL, ok INTEGER, result TEXT)')
            self.s.state.db.execute("UPDATE web_commands SET status='ready',ok=0,result=? WHERE status='processing'",
                (json.dumps({'error':'后台重启，操作结果未确认。未自动重新执行，请核查任务及原会话。'}, ensure_ascii=False),))
        self.cache = ReadCache(self)
        self.accounts = AccountCache(self.s.get_client)

    def exchange_payload(self, ready, cache_updates):
        payload = {'snapshot':self.snapshot(),'results':[],
                   'capacity':max(0,4-len(self.tasks)),'cacheUpdates':[]}
        def encoded_size(value):
            return len(json.dumps(value,ensure_ascii=False).encode())
        # Reserve enough room for any single supported result. Only unusually
        # large snapshots lose display detail; persisted history stays intact.
        if encoded_size(payload) > 750_000:
            import copy
            snapshot = payload['snapshot'] = copy.deepcopy(payload['snapshot'])
            snapshot['snapshotTruncated'] = True
            for job in snapshot.get('jobs',[]):
                for key in ('prompt','result','partial'):
                    if isinstance(job.get(key),str):job[key]=job[key][:2000]
                job['partialItems'] = []
            for item in snapshot.get('queue',[]):
                for key in ('prompt','error','paused'):
                    if isinstance(item.get(key),str):item[key]=item[key][:1000]
            if encoded_size(payload) > 750_000:
                catalogs = sorted(snapshot.get('catalogs',{}).values(),key=encoded_size,reverse=True)
                for catalog in catalogs:
                    catalog.pop('threads',None)
                    catalog['syncing'] = True
                    if encoded_size(payload) <= 750_000:break
            # Retain active jobs first when old completed jobs dominate a batch.
            for job in reversed(list(snapshot.get('jobs',[]))):
                if encoded_size(payload) <= 750_000:break
                if job.get('status') not in ('starting','running','waiting','unknown'):
                    snapshot['jobs'].remove(job)
            if encoded_size(payload) > 750_000:
                # Models can be read explicitly; complete queued prompts remain
                # in the local durable queue. Preserve IDs and task status.
                snapshot['models'] = {}
                for job in snapshot.get('jobs',[]):
                    for key in ('prompt','result','partial'):
                        if isinstance(job.get(key),str):job[key]=job[key][:200]
                for item in snapshot.get('queue',[]):
                    for key in ('prompt','error','paused'):
                        if isinstance(item.get(key),str):item[key]=item[key][:200]
            if encoded_size(payload) > 750_000:
                # An exceptional oversized interactive request must not starve
                # other read results. Its complete content remains in Codex.
                snapshot['approvals'] = []
                snapshot['snapshotError'] = '部分交互内容过大，请在原客户端查看完整内容。'
        # Binary previews can be much larger than command acknowledgements.
        # Prioritize results and leave unacknowledged entries for the next batch.
        budget = 1_800_000 - encoded_size(payload)
        for row in ready:
            result = {'id':row['id'],'ok':bool(row['ok']),'value':json.loads(row['result'])}
            size = len(json.dumps(result,ensure_ascii=False).encode()) + 2
            if size > 1_000_000:
                result = {'id':row['id'],'ok':False,'value':{'error':'结果过大，请缩小读取范围后重试'}}
                size = len(json.dumps(result,ensure_ascii=False).encode()) + 2
            if size > budget:continue
            payload['results'].append(result);budget -= size
        for entry in cache_updates:
            size = len(json.dumps(entry,ensure_ascii=False).encode()) + 2
            if size > budget:continue
            payload['cacheUpdates'].append(entry);budget -= size
        return payload

    def snapshot(self):
        s = self.s
        owner = s.state.get('owner', {})
        jobs = [{**s.public_job(j), 'partial':s.partial.get(j['id'], '')[-16000:],
                 'partialItems':[{'id':key,'text':s.redact(value)} for key,value in s.partial_items.get(j['id'],{}).items()]}
                for j in s.state.jobs(owner.get('chat'))]
        approvals = []
        for token, a in s.pending_input.items():
            j = s.state.job(a['job'])
            approvals.append({'token':token, 'host':j['host'], 'thread':j['thread'], 'job':j['id'],
                             **{k:a['params'].get(k) for k in ('command','reason','questions')}})
        return {'controller':os.getenv('WORKBENCH_CONTROLLER_LABEL','Controller · 常驻服务'),
                'hosts':[{'id':h.id,'label':h.label,'default_cwd':h.default_cwd,'roots':h.roots} for h in s.config.hosts.values()],
                'supervisor_model':s.config.supervisor_model,'supervisor_effort':s.config.supervisor_effort,
                'jobs':jobs,'approvals':approvals,'catalogs':self.cache.catalogs,
                'models':{h:v[1] for h,v in s.model_catalogs.items()},
                'queue':s.queue.items(owner.get('chat')),'revision':s.live_revision}

    def live_snapshot(self):
        full=self.snapshot()
        value={k:full[k] for k in ('jobs','approvals','queue','revision')}
        # Live metadata is bounded; full messages remain in the original history.
        value['jobs']=[{**j,'prompt':j['prompt'][:2000],'result':j['result'][:2000]} for j in value['jobs']]
        return value

    async def live_loop(self):
        # Actual new text is forwarded independently of slow command/history batches.
        # The hosted frontend supports HTTP short polling, not SSE/WebSocket.
        last_sent=0
        while not self.s.stopping:
            try:
                try:await asyncio.wait_for(self.s.live_event.wait(),5)
                except asyncio.TimeoutError:pass
                self.s.live_event.clear()
                await asyncio.sleep(.15)  # coalesce token bursts, not fabricated typing
                payload=self.live_snapshot()
                if payload['revision']==last_sent:continue
                r=await self.client.post(self.agent_url,json={'live':payload})
                r.raise_for_status();last_sent=payload['revision']
            except asyncio.CancelledError:raise
            except Exception as error:
                log.warning('Live sync unavailable: %s',self.s.redact(str(error))[:180])
                self.s.live_event.set();await asyncio.sleep(2)

    async def run(self):
        failures = 0
        warmer = asyncio.create_task(self.cache.run())
        live = asyncio.create_task(self.live_loop())
        try:
            while not self.s.stopping:
                try:
                    # Clear before collecting results so completions during the
                    # exchange wake the next batch instead of waiting two seconds.
                    self.exchange_event.clear()
                    with self.s.state.lock:
                        ready = [dict(r) for r in self.s.state.db.execute("SELECT * FROM web_commands WHERE status='ready' LIMIT 20")]
                    cache_updates = self.cache.pending()
                    response = await self.client.post(self.agent_url,json=self.exchange_payload(ready,cache_updates))
                    response.raise_for_status()
                    data = response.json()
                    self.cache.acknowledge(data.get('cacheAcked', []))
                    failures = 0
                    with self.s.state.lock,self.s.state.db:
                        for id in data.get('acked',[]):
                            self.s.state.db.execute("UPDATE web_commands SET status='acked' WHERE id=? AND status='ready'",(id,))
                    for command in data.get('commands',[]):
                        with self.s.state.lock,self.s.state.db:
                            fresh = self.s.state.db.execute("INSERT OR IGNORE INTO web_commands(id,status) VALUES(?,'processing')",(command['id'],)).rowcount
                        if not fresh:
                            continue
                        task = asyncio.create_task(self.execute(command))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures += 1
                    log.warning('Web relay unavailable: %s', self.s.redact(str(error))[:300])
                if self.s.stopping:break
                if failures:
                    await asyncio.sleep(min(60, 2 * 2**min(failures, 5)))
                else:
                    try:await asyncio.wait_for(self.exchange_event.wait(),2)
                    except asyncio.TimeoutError:pass
        finally:
            warmer.cancel()
            live.cancel()
            await asyncio.gather(warmer,live,return_exceptions=True)
            for task in self.tasks: task.cancel()
            if self.tasks: await asyncio.gather(*self.tasks,return_exceptions=True)
            await self.client.aclose()

    async def execute(self, command):
        try:
            if command['action']=='enqueue':
                async with self.enqueue_lock:value = await self.dispatch(command['action'],command['args'])
            else:value = await self.dispatch(command['action'],command['args'])
            ok = 1
        except asyncio.CancelledError:
            raise
        except Exception as error:
            value = {'error':self.s.redact(str(error))}
            ok = 0
        with self.s.state.lock,self.s.state.db:
            self.s.state.db.execute("UPDATE web_commands SET status='ready',ok=?,result=? WHERE id=?",
                (ok,json.dumps(value,ensure_ascii=False),command['id']))
        self.exchange_event.set()

    async def history(self, host, thread, cursor=None):
        s = self.s
        try:metadata = await s.metadata(host,thread)
        except CompatibilityError:
            metadata=s.state.get('rollout:'+host+':'+thread)
            if not metadata or host not in s.config.hosts:raise
            if cursor and not cursor.startswith('rollout:'):raise ValueError('原生接口不可用，请从最新历史重新打开只读记录')
            page=await remote_history(s.config.hosts[host],metadata['path'],thread,cursor)
            return self.visible_history(s,metadata,page['data'],page.get('nextCursor'))
        c = await s.get_client(host)
        if cursor and cursor.startswith('rollout:'):
            page = await remote_history(s.config.hosts[host],metadata['path'],thread,cursor)
            items,next_cursor = page['data'],page.get('nextCursor')
        else:
            try:items,next_cursor = await self.rpc_history(c,host,thread,cursor)
            except CompatibilityError:
                if host not in s.config.hosts or not metadata.get('path'):raise
                if cursor:raise ValueError('原生历史接口异常，请重新打开最新的只读记录')
                page=await remote_history(s.config.hosts[host],metadata['path'],thread)
                return self.visible_history(s,metadata,page['data'],page.get('nextCursor'))
            if not cursor and not items and not next_cursor and metadata.get('path') and host in s.config.hosts and not s.state.get('pending-title:'+host+':'+thread):
                page = await remote_history(s.config.hosts[host],metadata['path'],thread)
                items,next_cursor = page['data'],page.get('nextCursor')
        return self.visible_history(s,metadata,items,next_cursor)

    @staticmethod
    def visible_history(s,metadata,items,next_cursor):
        visible = []
        for i,item in enumerate(reversed(items)):
            role = None
            if item.get('type')=='agentMessage':role,text='assistant',item.get('text','')
            elif item.get('type')=='userMessage':
                role,text='user','\n'.join(x.get('text','') for x in item.get('content',[]) if x.get('type')=='text')
            if role and text:visible.append({'id':item.get('id') or f'{next_cursor}:{i}', 'role':role,'text':s.redact(text),
                                            **({'clientId':item['clientId']} if item.get('clientId') else {})})
        return {'thread':metadata,'messages':visible,'nextCursor':next_cursor}

    async def rpc_history(self, c, host, thread, cursor):
        try:
            page = await c.request('thread/items/list',{'threadId':thread,'limit':100,'sortDirection':'desc','cursor':cursor})
            items = [x.get('item',x) for x in page.get('data',[])]
            next_cursor = page.get('nextCursor')
        except RpcError as error:
            if error.payload.get('code') not in (-32600,-32601):raise
            # Legacy server: paginate its read snapshot locally without silently truncating.
            items = await self.s.turn_items(host,thread)
            offset = int(cursor or 0)
            if offset<0:raise ValueError('Invalid history cursor')
            next_cursor = str(offset+100) if offset+100<len(items) else None
            items = items[offset:offset+100]
        return items,next_cursor

    async def dispatch(self, action, a):
        s = self.s
        owner = s.state.get('owner',{})
        if not owner.get('open_id') or not owner.get('chat'):raise ValueError('请先在飞书完成个人绑定')
        chat,who = owner['chat'],owner['open_id']
        if action in ('account','file_preview'):
            host = a.get('host')
            actual_host = s.config.supervisor_host if host=='supervisor' else host
            if actual_host not in s.config.hosts:raise ValueError('未知的执行机器')
            if action=='account':return await self.accounts.get(actual_host,force=a.get('force') is True)
            thread = a.get('thread')
            if not isinstance(thread,str) or not thread:raise ValueError('请指定文件所属的会话')
            if host=='supervisor' and thread!=s.state.get('supervisor:'+chat):raise ValueError('会话不属于当前总管家')
            try:metadata = await asyncio.wait_for(s.metadata(host,thread),20)
            except (CompatibilityError, RpcError, ConnectionError, TimeoutError):
                metadata = s.state.get('rollout:'+actual_host+':'+thread)
                if not metadata:raise
            if metadata.get('id')!=thread:raise ValueError('会话信息不匹配')
            value = await preview_file(s.config.hosts[actual_host],a.get('path'),metadata['cwd'])
            if value.get('kind')=='text':value['text']=s.redact(value['text'])
            return value
        if action=='models':return await s.list_models(a['host'])
        if action=='sessions':
            page = await s.list_sessions(a['host'],a.get('cursor'),a.get('limit',10))
            # The project index needs labels and directories, not full thread metadata.
            return {'data':[compact_thread(s,t) for t in page['data']],
                    'nextCursor':page['nextCursor']}
        if action=='history':
            result = await self.history(a['host'],a['thread'],a.get('cursor'))
            if not a.get('cursor'):self.cache.remember(a['host'],a['thread'],result)
            return result
        if action=='directories':return await remote_file(s.config.hosts[a['host']],a['path'])
        if action=='new_session':return await s.new_session(a['host'],a['cwd'],a['title'])
        if action=='supervisor':
            thread = s.state.get('supervisor:'+chat)
            return await self.history('supervisor',thread) if thread else {'thread':None,'messages':[]}
        if action=='submit':
            host = a['host']
            thread = await s.supervisor(chat) if host=='supervisor' else a['thread']
            cwd = None if host=='supervisor' else (await s.metadata(host,thread))['cwd']
            return s.public_job(await s.submit(host,thread,a['prompt'],chat,who,cwd,a.get('model'),a.get('effort')))
        if action=='enqueue':
            host=a['host']
            if host=='supervisor':
                thread=s.state.get('supervisor:'+chat) or await s.supervisor(chat)
            else:thread=a['thread']
            return await s.queue.enqueue(host,thread,a['prompt'],chat,who,a.get('model'),a.get('effort'))
        if action=='steer':return await s.queue.steer(a['job'],a.get('expectedTurn'),a.get('prompt'),chat,who,a.get('queued'))
        if action=='cancel_queue':return s.queue.cancel(a['id'],chat,who)
        if action=='resume_queue':
            entry=s.queue.get_owned(a['id'],chat,who)
            s.queue.pause(entry['host'],entry['thread'],'')
            return {'resumed':True}
        if action in ('stop','reconcile'):
            j = s.state.job(a['job'])
            if j['chat']!=chat:raise ValueError('任务不属于当前账号')
            if action=='reconcile':return s.public_job(await s.reconcile(j))
            if not j['turn']:raise ValueError('提交结果尚未确认，请先核查')
            s.queue.pause(j['host'],j['thread'],'你停止了当前轮次；确认后可继续队列')
            c = await s.get_client(j['host'])
            await c.request('turn/interrupt',{'threadId':j['thread'],'turnId':j['turn']})
            return {'interrupted':True}
        if action in ('approval','answer'):
            if action=='approval':text=('/批准 ' if a['accept'] else '/拒绝 ')+a['token']
            else:text=shlex.join(['/回答',a['token'],a['question'],a['answer']])
            await s.handle({'text':text,'chat':chat,'owner':who})
            return {'accepted':True}
        if action=='image':return await s.send_image(a['host'],a['path'],chat)
        raise ValueError('未知工作台操作')
