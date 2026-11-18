import json
from unittest.mock import AsyncMock

import pytest

from feishu_codex_workbench.config import Host
from feishu_codex_workbench.rpc import CompatibilityError, RpcError
from test_webrelay import relay


@pytest.fixture
async def feature_relay(relay):
    relay.s.config.hosts["h"] = Host("h", "H", "H", "h", "/work", ("/work",), "h")
    relay.s.config.supervisor_host = "h"
    try:
        yield relay
    finally:
        await relay.client.aclose()


@pytest.mark.parametrize("host", ["h", "supervisor"])
async def test_account_uses_configured_host_and_supervisor_mapping(feature_relay, monkeypatch, host):
    account = AsyncMock(return_value={"status": "ok", "weekly": None})
    monkeypatch.setattr(feature_relay.accounts, "get", account)
    assert await feature_relay.dispatch("account", {"host": host, "force": True}) == account.return_value
    account.assert_awaited_once_with("h", force=True)


@pytest.mark.parametrize("force", [None, "true", 1, False])
async def test_account_only_boolean_true_bypasses_cache(feature_relay, monkeypatch, force):
    account = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(feature_relay.accounts, "get", account)
    await feature_relay.dispatch("account", {"host": "h", "force": force})
    account.assert_awaited_once_with("h", force=False)


@pytest.mark.parametrize("action", ["account", "file_preview"])
async def test_new_actions_reject_unknown_hosts_before_remote_access(feature_relay, monkeypatch, action):
    account = AsyncMock()
    metadata = AsyncMock()
    monkeypatch.setattr(feature_relay.accounts, "get", account)
    monkeypatch.setattr(feature_relay.s, "metadata", metadata)
    with pytest.raises(ValueError, match="未知的执行机器"):
        await feature_relay.dispatch(action, {"host": "unknown", "thread": "thread", "path": "a.py"})
    account.assert_not_awaited()
    metadata.assert_not_awaited()


@pytest.mark.parametrize("owner", [{}, {"chat": "chat"}, {"open_id": "owner"}])
@pytest.mark.parametrize("action", ["account", "file_preview"])
async def test_new_actions_require_paired_owner(feature_relay, monkeypatch, owner, action):
    feature_relay.s.state.put("owner", owner)
    account, metadata, preview = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(feature_relay.accounts, "get", account)
    monkeypatch.setattr(feature_relay.s, "metadata", metadata)
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    with pytest.raises(ValueError, match="个人绑定"):
        await feature_relay.dispatch(action, {"host": "h", "thread": "thread", "path": "a.py"})
    account.assert_not_awaited()
    metadata.assert_not_awaited()
    preview.assert_not_awaited()


async def test_file_preview_uses_trusted_thread_cwd_and_redacts_text(feature_relay, monkeypatch):
    metadata = AsyncMock(return_value={"id": "thread", "cwd": "/work/project"})
    preview = AsyncMock(return_value={"kind": "text", "text": "sk-0123456789abcdef0123"})
    monkeypatch.setattr(feature_relay.s, "metadata", metadata)
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    result = await feature_relay.dispatch("file_preview", {
        "host": "h", "thread": "thread", "path": "src/main.py", "cwd": "/attacker/chosen"})
    metadata.assert_awaited_once_with("h", "thread")
    preview.assert_awaited_once_with(feature_relay.s.config.hosts["h"], "src/main.py", "/work/project")
    assert result["text"] == "[redacted]"


@pytest.mark.parametrize("thread", [None, "", 12])
async def test_file_preview_requires_thread(feature_relay, monkeypatch, thread):
    metadata = AsyncMock()
    monkeypatch.setattr(feature_relay.s, "metadata", metadata)
    with pytest.raises(ValueError, match="文件所属的会话"):
        await feature_relay.dispatch("file_preview", {"host": "h", "thread": thread, "path": "a.py"})
    metadata.assert_not_awaited()


async def test_file_preview_rejects_mismatched_metadata(feature_relay, monkeypatch):
    monkeypatch.setattr(feature_relay.s, "metadata", AsyncMock(return_value={"id": "other", "cwd": "/work"}))
    preview = AsyncMock()
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    with pytest.raises(ValueError, match="会话信息不匹配"):
        await feature_relay.dispatch("file_preview", {"host": "h", "thread": "thread", "path": "a.py"})
    preview.assert_not_awaited()


async def test_supervisor_preview_requires_owned_thread_and_maps_file_host(feature_relay, monkeypatch):
    feature_relay.s.state.put("supervisor:chat", "owned")
    metadata = AsyncMock(return_value={"id": "owned", "cwd": "/work/supervisor"})
    preview = AsyncMock(return_value={"kind": "image", "data": "safe-base64"})
    monkeypatch.setattr(feature_relay.s, "metadata", metadata)
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    with pytest.raises(ValueError, match="不属于当前总管家"):
        await feature_relay.dispatch("file_preview", {"host": "supervisor", "thread": "other", "path": "a.png"})
    metadata.assert_not_awaited()
    assert await feature_relay.dispatch("file_preview", {
        "host": "supervisor", "thread": "owned", "path": "a.png"}) == preview.return_value
    metadata.assert_awaited_once_with("supervisor", "owned")
    preview.assert_awaited_once_with(feature_relay.s.config.hosts["h"], "a.png", "/work/supervisor")


@pytest.mark.parametrize("host", ["h", "supervisor"])
@pytest.mark.parametrize("error", [CompatibilityError("native history unavailable"),
                                    RpcError({"code": -32603, "message": "disk I/O error"}),
                                    ConnectionError("native connection unavailable"),
                                    TimeoutError("native read timed out")])
async def test_file_preview_uses_cached_rollout_cwd_when_native_metadata_is_unavailable(feature_relay, monkeypatch, host, error):
    feature_relay.s.state.put("supervisor:chat", "thread")
    feature_relay.s.state.put("rollout:h:thread", {"id": "thread", "cwd": "/work/cached", "path": "/work/rollout.jsonl"})
    monkeypatch.setattr(feature_relay.s, "metadata", AsyncMock(side_effect=error))
    preview = AsyncMock(return_value={"kind": "text", "text": "cached metadata read"})
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    await feature_relay.dispatch("file_preview", {"host": host, "thread": "thread", "path": "notes.md", "cwd": "/ignored"})
    preview.assert_awaited_once_with(feature_relay.s.config.hosts["h"], "notes.md", "/work/cached")


async def test_file_preview_does_not_guess_cwd_without_cached_rollout(feature_relay, monkeypatch):
    monkeypatch.setattr(feature_relay.s, "metadata", AsyncMock(side_effect=CompatibilityError("native history unavailable")))
    preview = AsyncMock()
    monkeypatch.setattr("feishu_codex_workbench.webrelay.preview_file", preview)
    with pytest.raises(CompatibilityError):
        await feature_relay.dispatch("file_preview", {"host": "h", "thread": "thread", "path": "notes.md", "cwd": "/work"})
    preview.assert_not_awaited()


async def test_history_metadata_compatibility_error_uses_cached_rollout_without_rpc(feature_relay, monkeypatch):
    metadata = {"id": "thread", "cwd": "/work", "path": "/work/rollout-thread.jsonl"}
    feature_relay.s.state.put("rollout:h:thread", metadata)
    monkeypatch.setattr(feature_relay.s, "metadata", AsyncMock(side_effect=CompatibilityError("broken native index")))
    client = AsyncMock()
    monkeypatch.setattr(feature_relay.s, "get_client", client)
    remote = AsyncMock(return_value={"data": [
        {"id": "a", "type": "agentMessage", "text": "answer"},
        {"id": "u", "type": "userMessage", "content": [{"type": "text", "text": "question"}]},
    ], "nextCursor": "rollout:10"})
    monkeypatch.setattr("feishu_codex_workbench.webrelay.remote_history", remote)
    value = await feature_relay.history("h", "thread")
    assert value["thread"] == metadata
    assert [m["text"] for m in value["messages"]] == ["question", "answer"]
    assert value["nextCursor"] == "rollout:10"
    remote.assert_awaited_once_with(feature_relay.s.config.hosts["h"], metadata["path"], "thread", None)
    client.assert_not_awaited()
    with pytest.raises(ValueError, match="重新打开"):
        await feature_relay.history("h", "thread", "native-cursor")
    assert remote.await_count == 1


async def test_history_items_compatibility_error_falls_back_only_without_native_cursor(feature_relay, monkeypatch):
    metadata = {"id": "thread", "cwd": "/work", "path": "/work/rollout-thread.jsonl"}
    monkeypatch.setattr(feature_relay.s, "metadata", AsyncMock(return_value=metadata))
    monkeypatch.setattr(feature_relay.s, "get_client", AsyncMock())
    monkeypatch.setattr(feature_relay, "rpc_history", AsyncMock(side_effect=CompatibilityError("broken native index")))
    remote = AsyncMock(return_value={"data": [], "nextCursor": None})
    monkeypatch.setattr("feishu_codex_workbench.webrelay.remote_history", remote)
    assert (await feature_relay.history("h", "thread"))["thread"] == metadata
    remote.assert_awaited_once_with(feature_relay.s.config.hosts["h"], metadata["path"], "thread")
    with pytest.raises(ValueError, match="重新打开"):
        await feature_relay.history("h", "thread", "native-cursor")
    assert remote.await_count == 1


def ready_row(identity, value):
    return {"id": identity, "ok": 1, "result": json.dumps(value, ensure_ascii=False)}


async def test_exchange_aggregate_budget_and_deferred_entries_survive_for_later(feature_relay, monkeypatch):
    monkeypatch.setattr(feature_relay, "snapshot", lambda: {"controller": "工作台"})
    rows = [ready_row(f"result-{i}", {"data": "x" * 700_000}) for i in range(3)]
    updates = [{"host": "h", "thread": f"thread-{i}", "revision": str(i), "value": "文" * 90_000}
               for i in range(3)]
    with feature_relay.s.state.db:
        for row in rows:
            feature_relay.s.state.db.execute("INSERT INTO web_commands VALUES(?, 'ready', ?, ?)",
                                            (row["id"], row["ok"], row["result"]))
    first = feature_relay.exchange_payload(rows, updates)
    assert len(json.dumps(first, ensure_ascii=False).encode()) <= 1_800_000
    assert len(first["results"]) == 2 and len(first["cacheUpdates"]) == 1
    first_results = {r["id"] for r in first["results"]}
    first_updates = {r["thread"] for r in first["cacheUpdates"]}
    assert all(row[0] == "ready" for row in feature_relay.s.state.db.execute("SELECT status FROM web_commands"))
    remaining_rows = [r for r in rows if r["id"] not in first_results]
    remaining_updates = [r for r in updates if r["thread"] not in first_updates]
    second = feature_relay.exchange_payload(remaining_rows, remaining_updates)
    assert len(json.dumps(second, ensure_ascii=False).encode()) <= 1_800_000
    assert {r["id"] for r in second["results"]} == {"result-2"}
    assert {r["thread"] for r in second["cacheUpdates"]} == {"thread-1", "thread-2"}


async def test_exchange_overlarge_result_becomes_explicit_error(feature_relay, monkeypatch):
    monkeypatch.setattr(feature_relay, "snapshot", lambda: {})
    value = feature_relay.exchange_payload([ready_row("huge", {"text": "文" * 400_000})], [])
    assert value["results"] == [{"id": "huge", "ok": False,
                                  "value": {"error": "结果过大，请缩小读取范围后重试"}}]
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 1_800_000


async def test_exchange_budget_also_handles_oversized_snapshot(feature_relay, monkeypatch):
    snapshot = feature_relay.snapshot()
    snapshot["jobs"] = [{"id": "large-job", "prompt": "p" * 100_000, "result": "r" * 1_800_000,
                         "partial": "", "partialItems": []}]
    monkeypatch.setattr(feature_relay, "snapshot", lambda: snapshot)
    value = feature_relay.exchange_payload([ready_row("account", {"status": "ok"})], [])
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 1_800_000
    assert value["results"] == [{"id": "account", "ok": True, "value": {"status": "ok"}}]
    assert len(snapshot["jobs"][0]["result"]) == 1_800_000


async def test_exchange_giant_catalog_preserves_hosts_and_connection_metadata(feature_relay, monkeypatch):
    snapshot = feature_relay.snapshot()
    snapshot["catalogs"] = {"h": {"connected": True, "updatedAt": 1234, "syncing": False,
                                  "threads": [{"id": str(i), "name": "大" * 1000} for i in range(400)]}}
    monkeypatch.setattr(feature_relay, "snapshot", lambda: snapshot)
    row = ready_row("preview", {"data": "x" * 999_000})
    value = feature_relay.exchange_payload([row], [])
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 1_800_000
    assert value["snapshot"]["hosts"] == snapshot["hosts"]
    assert value["snapshot"]["catalogs"]["h"] == {"connected": True, "updatedAt": 1234, "syncing": True}
    assert value["results"][0]["id"] == "preview" and value["results"][0]["ok"]
    assert len(snapshot["catalogs"]["h"]["threads"]) == 400
