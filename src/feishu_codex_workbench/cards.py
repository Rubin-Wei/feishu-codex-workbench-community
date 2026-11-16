"""Feishu message-card JSON, kept independent from transport for local previews."""
from __future__ import annotations

import shlex


def button(label, command, *, primary=False):
    return {"tag": "button", "text": {"tag": "plain_text", "content": label[:70]},
            "type": "primary" if primary else "default", "value": {"command": command}}


def card(title, text, actions=(), color="blue"):
    elements = [{"tag": "markdown", "content": text[:20000]}]
    for offset in range(0, len(actions), 3):
        elements.append({"tag": "action", "actions": list(actions[offset:offset + 3])})
    return {"config": {"wide_screen_mode": True},
            "header": {"template": color, "title": {"tag": "plain_text", "content": title[:100]}},
            "elements": elements}


def home(config, selection):
    current = "总管家" if selection.get("mode") == "supervisor" else selection.get("host", "尚未选择")
    text = f"**当前：{current}**\n会话：`{selection.get('thread') or '尚未选择'}`\n\n选择机器后查看已有会话，或新建会话。进入会话后直接发送任务。"
    actions = [button(h.label, f"/机器 {h.id}") for h in config.hosts.values()]
    actions += [button("总管家", "/管家", primary=True), button("任务看板", "/任务"), button("帮助", "/帮助")]
    return card("Codex 工作台", text, actions)


def sessions(host, threads, cursor_token=None):
    elements = [{"tag": "markdown", "content": f"执行机器：**{host.label}**\n同集群可共享历史；执行地点以本页机器为准。"}]
    for t in threads:
        title = t.get("name") or t.get("preview", "")[:70] or t["id"]
        elements.extend([
            {"tag": "markdown", "content": f"**{title[:120]}**\n`{t['cwd']}` · {t.get('status', {}).get('type', 'unknown')}"},
            {"tag": "action", "actions": [button("进入会话", f"/会话 {host.id} {t['id']}")]}
        ])
    actions = [button("新建会话", f"/新建界面 {host.id}"), button("切换机器", "/工作台")]
    if cursor_token:
        actions.append(button("下一页", f"/下一页 {cursor_token}"))
    elements.append({"tag": "action", "actions": actions})
    result = card(f"{host.label} · 会话列表", "")
    result["elements"] = elements
    return result


def new_session(host, cwd):
    c = card(f"{host.label} · 新建会话", "输入工作目录和会话名称。目录须已存在；可以先用 `/目录` 浏览。")
    c["elements"].append({"tag": "form", "name": "new_session", "elements": [
        {"tag": "input", "name": "cwd", "default_value": cwd,
         "label": {"tag": "plain_text", "content": "工作目录"},
         "placeholder": {"tag": "plain_text", "content": "绝对路径"}},
        {"tag": "input", "name": "title", "label": {"tag": "plain_text", "content": "会话名称"},
         "placeholder": {"tag": "plain_text", "content": "例如：Qwen 实验"}},
        {"tag": "button", "name": "submit", "text": {"tag": "plain_text", "content": "创建并进入"},
         "type": "primary", "action_type": "form_submit", "value": {"action": "new_session", "host": host.id}}
    ]})
    return c


def directories(host, result):
    commands = [button("在此新建会话", f"/新建界面 {host.id} {shlex.quote(result['path'])}")]
    commands.extend(button(path.rsplit("/", 1)[-1], f"/目录 {host.id} {shlex.quote(path)}")
                    for path in result["directories"][:18])
    return card(f"{host.label} · 目录", f"`{result['path']}`\n也可发送 `/新建 机器ID \"绝对路径\" 名称`。", commands)


def url_button(label, url):
    return {"tag":"button", "text":{"tag":"plain_text", "content":label}, "type":"primary", "url":url}
