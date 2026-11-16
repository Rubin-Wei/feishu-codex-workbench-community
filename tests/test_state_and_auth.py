import json
import pytest

from feishu_codex_workbench.config import Config, Host
from feishu_codex_workbench.feishu import normalize_card, normalize_message
from feishu_codex_workbench.service import Workbench
from feishu_codex_workbench.state import State


@pytest.fixture
def service(tmp_path):
    host = Host("pt-cpu", "PT CPU", "PT", "ssh-host", "/work/me", ("/work/me",), "pt")
    config = Config({host.id: host}, tmp_path, tmp_path, "codex", "app", "secret-value", "")
    state = State(tmp_path)
    result = Workbench(config, state)
    yield result
    state.close()


def event(text, *, owner="owner", chat="chat", id="m1", kind="message"):
    return dict(id=id, text=text, owner=owner, chat=chat, kind=kind)


def test_pairing_requires_code_and_private_message(service):
    assert not service.ingest(event("/工作台"))
    assert not service.ingest(event("/绑定 " + service.pairing_code, kind="card"))
    assert service.ingest(event("/绑定 " + service.pairing_code))
    assert service.owner() == "owner"
    assert service.state.next_event()["text"] == "/工作台"
    assert not service.ingest(event("/任务", owner="attacker", id="m2"))
    assert not service.ingest(event("/任务", chat="different-chat", id="m3", kind="card"))
    assert service.ingest(event("/任务", id="m4"))
    assert not service.ingest(event("/任务", id="m4"))


def test_inbox_recovery_does_not_replay_dispatched_message(service):
    state = service.state
    assert state.ingest(event("experiment"))
    assert state.next_event()["id"] == "m1"
    assert len(state.recover_inbox()) == 1
    assert state.next_event() is None
    assert not state.ingest(event("experiment"))


def test_shared_history_prevents_parallel_dispatch(service):
    s = service.state
    j = s.create_job("cpu", "pt", "same-thread", "chat", "owner", "run")
    with pytest.raises(ValueError, match="已有任务"):
        s.create_job("gpu", "pt", "same-thread", "chat", "owner", "run again")
    s.update_job(j["id"], status="unknown")
    with pytest.raises(ValueError):
        s.create_job("gpu", "pt", "same-thread", "chat", "owner", "retry")
    s.update_job(j["id"], status="completed")
    assert s.create_job("gpu", "pt", "same-thread", "chat", "owner", "next")


def test_outbox_idempotency_and_bounded_retry(service):
    s = service.state
    s.send("chat", "text", {"text": "result"}, "unique")
    s.send("chat", "text", {"text": "result"}, "unique")
    assert len(s.pending_messages()) == 1
    for _ in range(8):
        s.delivery_failed("unique", "network down")
    assert s.db.execute("SELECT status FROM outbox").fetchone()[0] == "failed"
    assert not s.pending_messages()


def test_normalizers_reject_group_and_bot_messages():
    raw = {"event": {"sender": {"sender_type": "user", "sender_id": {"open_id": "ou_owner"}},
                     "message": {"chat_type": "group", "message_id": "msg", "chat_id": "oc_chat", "message_type": "text", "content": '{"text":"hi"}'}}}
    assert normalize_message(raw) is None
    raw["event"]["message"]["chat_type"] = "p2p"
    assert normalize_message(raw)["text"] == "hi"
    raw["event"]["sender"]["sender_type"] = "app"
    assert normalize_message(raw) is None


def test_form_quotes_directory_and_title():
    raw = {"header": {"event_id": "event"}, "event": {"operator": {"open_id": "owner"},
           "context": {"open_chat_id": "chat"}, "action": {"value": {"action": "new_session", "host": "pt-cpu"},
           "form_value": {"cwd": "/work/me/space ' $dir", "title": "my session"}}}}
    import shlex
    normalized = normalize_card(raw)
    assert shlex.split(normalized["text"]) == ["/新建", "pt-cpu", "/work/me/space ' $dir", "my session"]


def test_expired_pairing_and_secret_redaction(service):
    service.pairing_expiry = 0
    assert not service.ingest(event("/绑定 " + service.pairing_code))
    assert service.redact("secret-value") == "[redacted]"


@pytest.mark.asyncio
async def test_stale_approval_cannot_be_applied_from_another_chat(service):
    import asyncio
    service.state.put("owner", {"open_id": "owner", "chat": "chat"})
    future = asyncio.get_running_loop().create_future()
    service.pending_input["token"] = {"future": future, "owner": "other", "chat": "chat"}
    with pytest.raises(ValueError, match="请求不存在"):
        await service.handle(event("/批准 token"))
    assert not future.done()
