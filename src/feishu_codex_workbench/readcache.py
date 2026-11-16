"""Warm read connections and visible history; never submits or resumes a turn."""
from __future__ import annotations
import asyncio
import hashlib
import json
import time


def compact_thread(service, thread):
    return {k: service.redact(thread[k]) if isinstance(thread.get(k), str) else thread.get(k)
            for k in ('id', 'name', 'cwd', 'status', 'updatedAt', 'model', 'reasoningEffort')} | {
                'preview': service.redact(thread.get('preview') or '')[:200]}


class ReadCache:
    def __init__(self, relay):
        self.relay, self.s = relay, relay.s
        self.catalogs = {}
        self.queue = asyncio.PriorityQueue()
        self.queued = set()
        with self.s.state.lock, self.s.state.db:
            self.s.state.db.execute('''CREATE TABLE IF NOT EXISTS web_history_cache (
              host TEXT, thread TEXT, revision TEXT, synced TEXT, source TEXT,
              updated REAL, payload TEXT, PRIMARY KEY(host,thread))''')
        for host in self.s.config.hosts:
            saved = self.s.state.get('catalog:' + host, {})
            self.catalogs[host] = {**saved, 'connected': False, 'syncing': True}

    def remember(self, host, thread, history, source=None):
        value = {**history, 'thread': compact_thread(self.s, history['thread']) if history.get('thread') else None}
        payload = json.dumps(value, ensure_ascii=False)
        # Keep transport batches bounded. Large histories remain available via the explicit reader.
        if len(payload.encode()) > 350000:
            return
        revision = hashlib.sha256(payload.encode()).hexdigest()
        with self.s.state.lock, self.s.state.db:
            self.s.state.db.execute('''INSERT INTO web_history_cache VALUES(?,?,?,NULL,?,?,?)
              ON CONFLICT(host,thread) DO UPDATE SET revision=excluded.revision,
              source=COALESCE(excluded.source,source),updated=excluded.updated,payload=excluded.payload''',
                (host, thread, revision, source, time.time(), payload))

    def pending(self, budget=450000):
        result = []
        with self.s.state.lock:
            rows = self.s.state.db.execute('''SELECT * FROM web_history_cache
              WHERE synced IS NULL OR synced!=revision ORDER BY updated LIMIT 12''').fetchall()
        for row in rows:
            entry = {'host': row['host'], 'thread': row['thread'], 'revision': row['revision'],
                     'updatedAt': int(row['updated'] * 1000), 'value': json.loads(row['payload'])}
            size = len(json.dumps(entry, ensure_ascii=False).encode())
            if size > budget: break
            result.append(entry); budget -= size
        return result

    def acknowledge(self, entries):
        with self.s.state.lock, self.s.state.db:
            for item in entries:
                self.s.state.db.execute('''UPDATE web_history_cache SET synced=?
                  WHERE host=? AND thread=? AND revision=?''',
                    (item['revision'], item['host'], item['thread'], item['revision']))

    async def sync_host(self, host):
        old = self.catalogs.get(host, {})
        self.catalogs[host] = {**old, 'syncing': True}
        try:
            threads, cursor, cursors = [], None, set()
            while True:
                page = await self.s.list_sessions(host, cursor, 100)
                threads.extend(compact_thread(self.s, t) for t in page['data'])
                cursor = page.get('nextCursor')
                if not cursor: break
                if cursor in cursors: raise ValueError('会话分页游标重复')
                cursors.add(cursor)
            threads = list({t['id']: t for t in threads}.values())
            value = {'threads': threads, 'connected': True, 'syncing': False,
                     'updatedAt': int(time.time()*1000), 'error': None}
            self.catalogs[host] = value
            self.s.state.put('catalog:' + host, value)
            with self.s.state.lock:
                known = {r['thread']: r for r in self.s.state.db.execute(
                    'SELECT thread,source,updated FROM web_history_cache WHERE host=?', (host,))}
            for rank, t in enumerate(threads):
                key = (host, t['id'])
                source = json.dumps([2, t.get('updatedAt'), t.get('name')], ensure_ascii=False)
                cached = known.get(t['id'])
                if key not in self.queued and (not cached or cached['source'] != source or time.time()-cached['updated'] > 600):
                    self.queued.add(key)
                    self.queue.put_nowait((rank, host, t['id'], source))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.catalogs[host] = {**old, 'connected': False, 'syncing': False,
                                   'error': self.s.redact(str(error))[:200]}

    async def host_loop(self, host):
        while not self.s.stopping:
            await self.sync_host(host)
            try:await self.s.list_models(host)
            except Exception:pass
            await asyncio.sleep(30)

    async def supervisor_models(self):
        while not self.s.stopping:
            try:await self.s.list_models('supervisor')
            except Exception:pass
            await asyncio.sleep(60)

    async def history_loop(self):
        while not self.s.stopping:
            _, host, thread, source = await self.queue.get()
            try:
                history = await self.relay.history(host, thread)
                self.remember(host, thread, history, source)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The on-demand reader reports errors to the owner; background reads
                # keep the last successful value and retry on the next catalog pass.
                pass
            finally:
                self.queued.discard((host, thread)); self.queue.task_done()
            await asyncio.sleep(.2)

    async def run(self):
        workers = [asyncio.create_task(self.host_loop(h)) for h in self.s.config.hosts]
        workers += [asyncio.create_task(self.history_loop()) for _ in range(2)]
        workers.append(asyncio.create_task(self.supervisor_models()))
        try:
            await asyncio.gather(*workers)
        finally:
            for w in workers: w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
