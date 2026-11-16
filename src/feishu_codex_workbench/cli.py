from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
import threading
import time
import shlex
from pathlib import Path

from .cluster import client_for, remote_file
from .config import load_config
from .feishu import Feishu, run_socket
from .service import Workbench
from .state import State


async def doctor(config):
    async def probe(host):
        client = client_for(host)
        try:
            init = await client.start()
            account = await client.request("account/read", {"refreshToken": False})
            sessions = await client.request("thread/list", {"limit": 5, "modelProviders": []})
            directory = await remote_file(host, host.default_cwd)
            return {"host": host.id, "ssh_rpc": "ok", "codex_home": init.get("codexHome"),
                    "server": init.get("userAgent"), "auth": (account.get("account") or {}).get("type", "not_logged_in"),
                    "sessions_sample": len(sessions.get("data", [])), "cwd": directory["path"],
                    "note": "登录状态和接口检查通过；此检查未调用模型"}
        except Exception as e:
            return {"host": host.id, "ssh_rpc": "failed", "error": str(e)}
        finally:
            await client.close()
    results = await asyncio.gather(*(probe(h) for h in config.hosts.values()))
    return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hosts": results, "feishu_credentials_configured": bool(config.app_id and config.app_secret)}


async def smoke(config, hosts):
    """Explicit opt-in: create test sessions and use the configured models."""
    state = State(config.state_dir / "smoke")
    service = Workbench(config, state)
    original_request = service.on_request
    async def smoke_request(host, method, p):
        if method == "item/commandExecution/requestApproval":
            command = p.get("command") or ""
            argv = shlex.split(command)
            if len(argv) == 3 and argv[0] in ("/bin/bash", "/bin/sh", "/bin/zsh", "bash", "sh") and argv[1] in ("-lc", "-c"):
                command = argv[2]
            commands = [part.strip() for part in re.split(r"&&|;|\n", command) if part.strip()]
            if commands and set(commands) <= {"hostname", "pwd", "id -un"}:
                return {"decision": "accept"}
            return {"decision": "decline"}
        return await original_request(host, method, p)
    import re
    service.on_request = smoke_request
    results = []
    try:
        for host in hosts:
            h = config.hosts[host]
            thread = await service.new_session(host, h.default_cwd, "飞书联调 · " + h.label)
            job = await service.submit(host, thread["id"],
                "这是飞书工作台连通性测试。只用终端工具执行 hostname、pwd 和 id -un，"
                "不要修改任何文件，不要运行实验。请用三行原样报告三个命令的结果。", "local-smoke", "local-smoke")
            results.append(job)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            latest = [state.job(j["id"]) for j in results]
            if all(j["status"] not in ("starting", "running", "waiting") for j in latest):
                break
            await asyncio.sleep(1)
        for j in results:
            current = state.job(j["id"])
            if current["status"] in ("starting", "running", "waiting") and current["turn"]:
                c = await service.get_client(current["host"])
                await c.request("turn/interrupt", {"threadId": current["thread"], "turnId": current["turn"]})
                await asyncio.sleep(1)
        return [service.public_job(state.job(j["id"])) for j in results]
    finally:
        await service.close()
        state.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="飞书 Codex 工作台")
    parser.add_argument("--config", help="Config TOML file (default config.local.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only SSH, RPC, login-state and directory checks")
    sub.add_parser("run", help="Start Feishu long connection and dispatch worker")
    sub.add_parser("status", help="Show local dispatch/outbox state without connecting")
    sub.add_parser("retry-delivery", help="Retry failed outbound messages without rerunning jobs")
    s = sub.add_parser("smoke", help="Create test sessions and execute read-only hostname/pwd checks using Codex")
    s.add_argument("--host", action="append", help="Host id; omit for all hosts")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "doctor":
        result = asyncio.run(doctor(config))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(h["ssh_rpc"] == "ok" for h in result["hosts"]) else 1
    if args.command == "smoke":
        result = asyncio.run(smoke(config, args.host or list(config.hosts)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(j["status"] == "completed" for j in result) else 1
    state = State(config.state_dir)
    if args.command == "status":
        print(json.dumps({"owner_bound": bool(config.owner_open_id or state.get("owner")),
                          "jobs": [Workbench.public_job(j) for j in state.jobs()],
                          "delivery": [dict(r) for r in state.db.execute("SELECT status,count(*) AS count FROM outbox GROUP BY status")]},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "retry-delivery":
        with state.db:
            changed = state.db.execute("UPDATE outbox SET status='pending',attempts=0,next_try=0 WHERE status='failed'").rowcount
        print(f"Requeued {changed} outbound messages. No jobs rerun.")
        return 0
    if not config.app_id or not config.app_secret:
        parser.error("请先在 .env 填入 FEISHU_APP_ID 和 FEISHU_APP_SECRET；参见 docs/FEISHU_SETUP.md")
    lock_file = (config.state_dir / "runner.lock").open("a")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("已有工作台进程使用同一个状态目录，拒绝重复启动")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    service = Workbench(config, state, Feishu(config.app_id, config.app_secret))
    if not service.owner():
        print("请在 15 分钟内从你的飞书账号私聊机器人发送：", flush=True)
        print("/绑定 " + service.pairing_code, flush=True)
    else:
        print("工作台已启动，仅接受已绑定账号的单聊消息。", flush=True)
    loop = asyncio.new_event_loop()
    holder = {}
    ready = threading.Event()
    def worker():
        asyncio.set_event_loop(loop)
        task = loop.create_task(service.run())
        holder["task"] = task
        ready.set()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()
    thread = threading.Thread(target=worker, name="workbench", daemon=True)
    thread.start()
    ready.wait()
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        run_socket(config, service.ingest)
    except KeyboardInterrupt:
        pass
    finally:
        if not loop.is_closed():
            loop.call_soon_threadsafe(holder["task"].cancel)
        thread.join(timeout=12)
        if not thread.is_alive():
            state.close()
        lock_file.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
