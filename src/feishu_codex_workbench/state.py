from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

ACTIVE = ("starting", "running", "waiting", "unknown")


class State:
    """Private durable inbox/outbox and dispatch journal; safe across SDK threads."""
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.on_change = lambda: None
        self.db = sqlite3.connect(folder / "workbench.sqlite3", check_same_thread=False)
        os.chmod(folder / "workbench.sqlite3", 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, chat TEXT NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, host TEXT NOT NULL,
          session_group TEXT NOT NULL, thread TEXT NOT NULL, turn TEXT,
          chat TEXT NOT NULL, owner TEXT NOT NULL, prompt TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
          updated REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_thread ON jobs(session_group,thread)
          WHERE status IN ('starting','running','waiting','unknown');
        """)
        self.db.commit()

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def ingest(self, event):
        with self.lock, self.db:
            return self.db.execute("INSERT OR IGNORE INTO inbox(id,payload,created) VALUES (?,?,?)",
                                   (event["id"], json.dumps(event, ensure_ascii=False), time.time())).rowcount == 1

    def next_event(self):
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM inbox WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE inbox SET status='processing' WHERE id=?", (row["id"],))
                return json.loads(row["payload"])

    def event_done(self, event_id, status="done"):
        with self.lock, self.db:
            self.db.execute("UPDATE inbox SET status=? WHERE id=?", (status, event_id))

    def recover_inbox(self):
        # An interrupted handler may already have submitted a remote turn. Never replay it.
        with self.lock, self.db:
            rows = self.db.execute("SELECT payload FROM inbox WHERE status='processing'").fetchall()
            self.db.execute("UPDATE inbox SET status='uncertain' WHERE status='processing'")
            return [json.loads(r[0]) for r in rows]

    def send(self, chat, kind, payload, key=None):
        key = key or str(uuid.uuid4())
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO outbox(id,chat,kind,payload) VALUES (?,?,?,?)",
                            (key, chat, kind, json.dumps(payload, ensure_ascii=False)))
        return key

    def pending_messages(self):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM outbox WHERE status='pending' AND next_try<=? ORDER BY rowid LIMIT 20", (time.time(),))]

    def delivered(self, key):
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET status='sent' WHERE id=?", (key,))

    def delivery_failed(self, key, error):
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET attempts=attempts+1, error=?, next_try=?, "
                            "status=CASE WHEN attempts>=7 THEN 'failed' ELSE 'pending' END WHERE id=?",
                            (str(error)[:400], time.time() + 30, key))

    def create_job(self, host, group, thread, chat, owner, prompt, job_id=None):
        job_id = job_id or uuid.uuid4().hex[:12]
        now = time.time()
        with self.lock, self.db:
            try:
                self.db.execute("INSERT INTO jobs(id,host,session_group,thread,chat,owner,prompt,status,created,updated) "
                                "VALUES (?,?,?,?,?,?,?,'starting',?,?)", (job_id, host, group, thread, chat, owner, prompt, now, now))
            except sqlite3.IntegrityError as error:
                raise ValueError("该会话已有任务运行或等待核查，请先查看任务状态") from error
        self.on_change()
        return self.job(job_id)

    def job(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            return dict(row)

    def update_job(self, job_id, **fields):
        if not fields.keys() <= {"status", "turn", "result"}:
            raise ValueError("Invalid job update")
        fields["updated"] = time.time()
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                            (*fields.values(), job_id))
        self.on_change()

    def jobs(self, chat=None, active=False):
        where, args = [], []
        if chat:
            where.append("chat=?"); args.append(chat)
        if active:
            where.append("status IN ('starting','running','waiting','unknown')")
        query = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created DESC"
        if not active:
            query += " LIMIT 30"
        with self.lock:
            return [dict(r) for r in self.db.execute(query, args)]

    def close(self):
        self.db.close()
