from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv


@dataclass(frozen=True)
class Host:
    id: str
    label: str
    cluster: str
    ssh: str
    default_cwd: str
    roots: tuple[str, ...]
    session_group: str
    transport: str = "proxy"
    codex_command: str = "codex"
    proxy_url: str | None = None
    native_socket: str | None = None

    def validate_path(self, value: str) -> str:
        p = PurePosixPath(value)
        if not p.is_absolute() or ".." in p.parts or any(ord(c) < 32 for c in value):
            raise ValueError("目录必须是绝对路径，且不能包含 .. 或控制字符")
        if not any(p.is_relative_to(PurePosixPath(root)) for root in self.roots):
            raise ValueError("目录不在该机器配置的个人工作区域内")
        return str(p)


@dataclass
class Config:
    hosts: dict[str, Host]
    state_dir: Path
    supervisor_cwd: Path
    codex_command: str
    app_id: str
    app_secret: str
    owner_open_id: str
    progress_interval: int = 30
    supervisor_model: str = "gpt-6.1-sol"
    supervisor_effort: str = "medium"
    supervisor_host: str = "worker-gpu"


def load_config(path: str | None = None) -> Config:
    load_dotenv(override=False)
    p = Path(path or os.getenv("WORKBENCH_CONFIG", "config.local.toml")).resolve()
    raw = tomllib.loads(p.read_text())
    hosts = {}
    for item in raw["hosts"]:
        item["roots"] = tuple(item["roots"])
        h = Host(**item)
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", h.ssh):
            raise ValueError("ssh 必须是 ~/.ssh/config 中的单个别名")
        if h.transport not in ("proxy", "stdio") or h.id in hosts:
            raise ValueError("transport 无效或 host id 重复")
        h.validate_path(h.default_cwd)
        hosts[h.id] = h
    state = (p.parent / raw.get("state_dir", ".local/state")).resolve()
    supervisor = (p.parent / raw.get("supervisor_cwd", ".local/supervisor")).resolve()
    for folder in (state, supervisor):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    app_id, app_secret = os.getenv("FEISHU_APP_ID", ""), os.getenv("FEISHU_APP_SECRET", "")
    if not app_secret and os.getenv("FEISHU_LARK_PROFILE"):
        from .credentials import from_lark_profile
        profile_id, app_secret = from_lark_profile(os.environ["FEISHU_LARK_PROFILE"])
        if app_id and profile_id != app_id:
            raise ValueError("App ID 与选定的 CLI profile 不匹配")
        app_id = profile_id
    return Config(hosts, state, supervisor, raw.get("codex_command", "codex"),
                  app_id, app_secret,
                  os.getenv("FEISHU_OWNER_OPEN_ID", ""),
                  int(raw.get("progress_interval_seconds", 30)),
                  raw.get("supervisor_model", "gpt-6.1-sol"),
                  raw.get("supervisor_effort", "medium"),
                  raw.get("supervisor_host", "worker-gpu"))
