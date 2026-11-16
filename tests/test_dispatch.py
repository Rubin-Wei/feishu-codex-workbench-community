import asyncio
from unittest.mock import AsyncMock

import pytest

from feishu_codex_workbench.config import Config, Host
from feishu_codex_workbench.rpc import RpcError
from feishu_codex_workbench.service import Workbench
from feishu_codex_workbench.state import State


@pytest.fixture
def service(tmp_path):
    hosts = {name: Host(name, name, "PT", "ssh-host", "/work/me", ("/work/me",), "pt") for name in ("cpu", "gpu")}
    state = State(tmp_path)
    svc = Workbench(Config(hosts, tmp_path, tmp_path, "codex", "", "", "owner"), state)
    yield svc
    state.close()


async def test_active_sibling_blocks_before_dispatch(service):
    service.metadata = AsyncMock(side_effect=[{"status": {"type": "idle"}}, {"status": {"type": "active"}}])
    client = AsyncMock()
    client.request.return_value = {"data": ["thread"]}
    service.get_client = AsyncMock(return_value=client)
    with pytest.raises(ValueError, match="正在 gpu"):
        await service.submit("cpu", "thread", "run", "chat", "owner")
    assert [x.args[0] for x in client.request.call_args_list] == ["thread/loaded/list"]
    assert not service.state.jobs()


async def test_unknown_submit_is_not_automatically_retried(service):
    service.check_idle = AsyncMock()
    client = AsyncMock()
    client.request.side_effect = [{}, TimeoutError()]
    service.get_client = AsyncMock(return_value=client)
    with pytest.raises(TimeoutError):
        await service.submit("cpu", "thread", "run", "chat", "owner")
    assert service.state.jobs()[0]["status"] == "unknown"
    assert [x.args[0] for x in client.request.call_args_list] == ["thread/resume", "turn/start"]
    client.request.side_effect = None
    with pytest.raises(ValueError, match="已有任务"):
        await service.submit("gpu", "thread", "retry", "chat", "owner")
    assert sum(x.args[0] == "turn/start" for x in client.request.call_args_list) == 1


async def test_completion_reads_wrapped_items_and_preserves_final(service):
    client = AsyncMock()
    client.request.return_value = {"data": [{"turnId": "turn", "item": {
        "type": "agentMessage", "phase": "final_answer", "text": "Verified hostname: machine-cpu"}}]}
    service.get_client = AsyncMock(return_value=client)
    job = service.state.create_job("cpu", "pt", "thread", "chat", "owner", "check")
    await service.finish(job, {"id": "turn", "status": "completed", "items": []})
    assert service.state.job(job["id"])["result"] == "Verified hostname: machine-cpu"
    assert len(service.state.pending_messages()) == 1
    await service.finish(job, {"id": "turn", "status": "completed", "items": []})
    assert len(service.state.pending_messages()) == 1


async def test_reconnect_never_starts_a_new_turn(service):
    client = AsyncMock()
    client.request.side_effect = [
        {"thread": {"status": {"type": "active"}, "turns": []}},
        {"data": [{"id": "turn", "status": "inProgress"}]},
    ]
    service.get_client = AsyncMock(return_value=client)
    job = service.state.create_job("cpu", "pt", "thread", "chat", "owner", "check")
    service.state.update_job(job["id"], status="unknown", turn="turn")
    result = await service.reconcile(service.state.job(job["id"]))
    assert result["status"] == "running"
    assert [x.args[0] for x in client.request.call_args_list] == ["thread/resume", "thread/turns/list"]


async def test_approval_only_accepts_current_owner(service):
    service.state.put("owner", {"open_id": "owner", "chat": "chat"})
    job = service.state.create_job("cpu", "pt", "thread", "chat", "owner", "check")
    service.state.update_job(job["id"], turn="turn", status="running")
    pending = asyncio.create_task(service.on_request("cpu", "item/commandExecution/requestApproval", {
        "threadId": "thread", "turnId": "turn", "itemId": "item", "command": "echo OK"}))
    await asyncio.sleep(0)
    token = next(iter(service.pending_input))
    await service.handle({"text": "/批准 " + token, "owner": "attacker", "chat": "chat"})
    assert not pending.done()
    await service.handle({"text": "/批准 " + token, "owner": "owner", "chat": "chat"})
    assert await pending == {"decision": "accept"}


async def test_stream_completion_replaces_deltas_and_repeated_events(service):
 job=service.state.create_job('cpu','pt','thread','chat','owner','check')
 service.state.update_job(job['id'],status='running',turn='turn')
 async def delta(id,text):await service.on_event('cpu','item/agentMessage/delta',{'threadId':'thread','turnId':'turn','itemId':id,'delta':text})
 async def complete(id,text):await service.on_event('cpu','item/completed',{'threadId':'thread','turnId':'turn','item':{'id':id,'type':'agentMessage','text':text}})
 await delta('a','First ');await delta('a','paragraph.');await complete('a','First paragraph.')
 await complete('a','First paragraph.')
 await delta('b','Second paragraph.');await complete('b','Second paragraph.')
 assert service.partial[job['id']]=='First paragraph.\n\nSecond paragraph.'
 await complete('c','First paragraph.')
 assert len(service.partial_items[job['id']])==3  # different items may intentionally repeat text


async def test_model_and_effort_only_override_the_submitted_turn(service):
 service.check_idle=AsyncMock()
 service.list_models=AsyncMock(return_value=[{'id':'native-model','efforts':['low','medium']}])
 c=AsyncMock();c.request.side_effect=[{}, {'turn':{'id':'turn'}}];service.get_client=AsyncMock(return_value=c)
 await service.submit('cpu','thread','test','chat','owner',model='native-model',effort='medium')
 calls=c.request.call_args_list
 assert calls[-1].args[1]['model']=='native-model' and calls[-1].args[1]['effort']=='medium'
 assert all(x.args[0] in ('thread/resume','turn/start') for x in calls)


async def test_unsupported_effort_fails_before_dispatch(service):
 service.check_idle=AsyncMock();service.list_models=AsyncMock(return_value=[{'id':'native-model','efforts':['low']}])
 c=AsyncMock();service.get_client=AsyncMock(return_value=c)
 with pytest.raises(ValueError,match='不支持所选推理强度'):
  await service.submit('cpu','thread','test','chat','owner',model='native-model',effort='ultra')
 c.request.assert_not_awaited();assert not service.state.jobs()
