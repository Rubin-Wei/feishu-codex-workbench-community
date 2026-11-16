from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx


class Feishu:
    def __init__(self, app_id, app_secret):
        self.app_id, self.app_secret = app_id, app_secret
        self.client = httpx.AsyncClient(base_url="https://open.feishu.cn/open-apis", timeout=25)
        self.token, self.expiry = "", 0
        self.token_lock = asyncio.Lock()

    async def access_token(self):
        async with self.token_lock:
            if self.expiry <= time.time():
                response = await self.client.post("/auth/v3/tenant_access_token/internal", json={
                    "app_id": self.app_id, "app_secret": self.app_secret})
                response.raise_for_status()
                data = response.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"飞书鉴权失败（code={data.get('code')}），请检查应用凭据")
                self.token = data["tenant_access_token"]
                self.expiry = time.time() + data["expire"] - 120
            return self.token

    async def api(self, method, path, **kwargs):
        for attempt in range(2):
            response = await self.client.request(method, path, headers={
                "Authorization": "Bearer " + await self.access_token()}, **kwargs)
            response.raise_for_status()
            data = response.json()
            if data.get("code") in (99991663, 99991664, 99991668) and attempt == 0:
                self.expiry = 0
                continue
            if data.get("code") != 0:
                raise RuntimeError(f"飞书 API 请求失败（code={data.get('code')}）：{data.get('msg','')[:250]}")
            return data.get("data", {})
        raise RuntimeError("飞书 token 刷新失败")

    async def send(self, chat, kind, payload, key):
        return await self.api("POST", "/im/v1/messages", params={"receive_id_type": "chat_id"}, json={
            "receive_id": chat, "msg_type": kind, "content": json.dumps(payload, ensure_ascii=False),
            "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, "feishu-workbench:" + key))})

    async def upload_image(self, name, data):
        result = await self.api("POST", "/im/v1/images", data={"image_type": "message"},
                                files={"image": (name, data, "application/octet-stream")})
        return result["image_key"]

    async def close(self):
        await self.client.aclose()


def normalize_message(data):
    event = data["event"]
    msg = event["message"]
    sender = event["sender"]
    if sender.get("sender_type") != "user" or msg.get("chat_type") != "p2p":
        return None
    if msg.get("message_type") != "text":
        text = "/不支持消息"
    else:
        text = json.loads(msg["content"]).get("text", "").strip()
    return {"id": msg["message_id"], "owner": sender["sender_id"]["open_id"],
            "chat": msg["chat_id"], "text": text, "kind": "message"}


def normalize_card(data):
    event = data["event"]
    action = event["action"]
    value = action.get("value", {})
    command = value.get("command", "")
    if value.get("action") == "new_session":
        import shlex
        form = action.get("form_value", {})
        command = shlex.join(["/新建", value["host"], form.get("cwd", ""), form.get("title") or "手机会话"])
    event_id = data.get("header", {}).get("event_id") or event.get("token")
    if not event_id or not command:
        return None
    return {"id": "card:" + event_id, "owner": event["operator"]["open_id"],
            "chat": event["context"]["open_chat_id"], "text": command, "kind": "card"}


def run_socket(config, ingest):
    """SDK owns main-thread loop; durable ingestion finishes before acknowledging."""
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

    def message(data):
        event = normalize_message(json.loads(lark.JSON.marshal(data)))
        if event:
            ingest(event)

    def action(data):
        event = normalize_card(json.loads(lark.JSON.marshal(data)))
        accepted = bool(event and ingest(event))
        return P2CardActionTriggerResponse({"toast": {"type": "info" if accepted else "error",
            "content": "已接收，结果将发送到聊天" if accepted else "未授权、已处理或操作无效"}})

    handler = (lark.EventDispatcherHandler.builder("", "")
               .register_p2_im_message_receive_v1(message)
               .register_p2_im_message_message_read_v1(lambda _: None)
               .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(lambda _: None)
               .register_p2_card_action_trigger(action).build())
    lark.ws.Client(config.app_id, config.app_secret, event_handler=handler,
                   log_level=lark.LogLevel.WARNING).start()
