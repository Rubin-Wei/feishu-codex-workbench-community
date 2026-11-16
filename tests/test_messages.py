import asyncio
import sys
import tempfile
from dataclasses import replace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from test_dispatch import service
from feishu_codex_workbench.messages import MessageQueue
from feishu_codex_workbench.cluster import client_for, SOCKET_RELAY
from feishu_codex_workbench.rpc import RpcClient, RpcError, CompatibilityError


async def drain(s):
    await s.queue.tick()
    await asyncio.gather(*s.queue.tasks)


async def test_queue_fifo_waits_for_completion_and_keeps_model(service):
    s=service;s.metadata=AsyncMock(return_value={'cwd':'/work/me'})
    s.validate_model=AsyncMock();s.check_idle=AsyncMock()
    c=AsyncMock();c.request.side_effect=[{}, {'turn':{'id':'one'}},{},{'turn':{'id':'two'}}]
    s.get_client=AsyncMock(return_value=c)
    first=await s.queue.enqueue('cpu','t','first','chat','owner',model='m',effort='medium')
    second=await s.queue.enqueue('gpu','t','second','chat','owner')
    await drain(s)
    assert s.state.job(first['id'])['status']=='running'
    assert s.queue.get_owned(second['id'],'chat','owner')['status']=='queued'
    await drain(s);assert c.request.await_count==2
    s.state.update_job(first['id'],status='completed')
    await drain(s)
    starts=[x.args[1] for x in c.request.await_args_list if x.args[0]=='turn/start']
    assert [x['input'][0]['text'] for x in starts]==['first','second']
    assert starts[0]['effort']=='medium'
    assert starts[0]['clientUserMessageId']==first['message_id']


async def test_cancel_and_pause_do_not_dispatch(service):
    s=service;s.metadata=AsyncMock();s.validate_model=AsyncMock();s.submit=AsyncMock()
    a=await s.queue.enqueue('cpu','t','first','chat','owner')
    with pytest.raises(ValueError):s.queue.cancel(a['id'],'other','attacker')
    s.queue.cancel(a['id'],'chat','owner');await drain(s);s.submit.assert_not_awaited()
    b=await s.queue.enqueue('cpu','t','second','chat','owner')
    s.queue.pause('cpu','t','stopped');await drain(s);s.submit.assert_not_awaited()
    assert s.queue.items('chat')[-1]['paused']=='stopped'


async def test_crash_after_claim_never_replays_message(service):
    s=service;s.metadata=AsyncMock();s.validate_model=AsyncMock();s.submit=AsyncMock()
    item=await s.queue.enqueue('cpu','t','do once','chat','owner')
    s.queue.update(item['id'],'dispatching')
    s.queue=MessageQueue(s)
    await drain(s)
    assert s.queue.get_owned(item['id'],'chat','owner')['status']=='unknown'
    s.submit.assert_not_awaited()


async def test_steer_requires_owner_and_exact_turn_and_does_not_start(service):
    s=service;j=s.state.create_job('cpu','pt','t','chat','owner','task')
    s.state.update_job(j['id'],status='running',turn='active')
    c=AsyncMock();c.request.return_value={'turnId':'active'};s.get_client=AsyncMock(return_value=c)
    with pytest.raises(ValueError):await s.queue.steer(j['id'],'active','steer','chat','attacker')
    with pytest.raises(ValueError):await s.queue.steer(j['id'],'old','steer','chat','owner')
    c.request.assert_not_awaited()
    result=await s.queue.steer(j['id'],'active','new direction','chat','owner')
    assert result['status']=='sent'
    assert c.request.call_args.args[0]=='turn/steer'
    assert c.request.call_args.args[1]['expectedTurnId']=='active'
    c.request.side_effect=TimeoutError()
    with pytest.raises(TimeoutError):await s.queue.steer(j['id'],'active','once only','chat','owner')
    assert s.queue.items('chat')[-1]['status']=='unknown'
    await drain(s);assert c.request.await_count==2


async def test_database_incompatibility_trips_before_more_rpc_writes():
    c=RpcClient(['unused'])
    async def write(message):c.pending[message['id']].set_exception(RpcError({'message':'no such column: threads.attached_thread_parent_id'}))
    c.write=AsyncMock(side_effect=write)
    with pytest.raises(CompatibilityError):await c.request('thread/list')
    with pytest.raises(CompatibilityError):await c.request('turn/start')
    with pytest.raises(CompatibilityError):await c.request('thread/list')
    assert c.write.await_count==1


async def test_promote_queued_message_steers_once_without_new_turn(service):
    s=service;s.metadata=AsyncMock();s.validate_model=AsyncMock()
    j=s.state.create_job('cpu','pt','t','chat','owner','task');s.state.update_job(j['id'],status='running',turn='active')
    queued=await s.queue.enqueue('cpu','t','queued guidance','chat','owner')
    c=AsyncMock();c.request.return_value={'turnId':'active'};s.get_client=AsyncMock(return_value=c)
    result=await s.queue.steer(j['id'],'active',None,'chat','owner',queued['id'])
    assert result['status']=='sent' and result['mode']=='steer'
    with pytest.raises(ValueError):await s.queue.steer(j['id'],'active',None,'chat','owner',queued['id'])
    await drain(s)
    assert [call.args[0] for call in c.request.await_args_list]==['turn/steer']


async def test_corrupt_history_isolated_to_its_thread():
    c=RpcClient(['unused'])
    async def write(message):
        future=c.pending[message['id']]
        if message['params'].get('threadId')=='broken' and message['method']!='turn/interrupt':future.set_exception(RpcError({'message':'database disk image is malformed'}))
        else:future.set_result({'ok':True})
    c.write=AsyncMock(side_effect=write)
    with pytest.raises(CompatibilityError):await c.request('thread/items/list',{'threadId':'broken'})
    with pytest.raises(CompatibilityError):await c.request('turn/start',{'threadId':'broken'})
    assert await c.request('thread/read',{'threadId':'healthy'})=={'ok':True}
    assert await c.request('turn/interrupt',{'threadId':'broken','turnId':'known'})=={'ok':True}
    assert c.write.await_count==3


async def test_new_thread_rollout_race_does_not_create_twice(service):
    s=service;c=AsyncMock()
    c.request.side_effect=[{'thread':{'id':'new'}},{'thread':{'id':'new','name':None}},
        RpcError({'message':'no rollout found for thread id new'}),{'thread':{'id':'new','name':None}},{}]
    s.get_client=AsyncMock(return_value=c)
    with patch('feishu_codex_workbench.service.remote_file',new_callable=AsyncMock,return_value={'path':'/work/me'}):
        t=await s.new_session('cpu','/work/me','My title')
    assert t['id']=='new' and t['name']=='My title'
    assert sum(call.args[0]=='thread/start' for call in c.request.await_args_list)==1
    assert s.state.get('pending-title:cpu:new') is None


async def test_first_message_subscribes_even_when_new_thread_already_loaded(service):
    s=service;s.state.put('pending-title:cpu:new','Pending name')
    s.check_idle=AsyncMock();s.is_loaded=AsyncMock(return_value=True);s.persist_title=AsyncMock()
    c=AsyncMock();c.request.side_effect=[{}, {'turn':{'id':'first'}}];s.get_client=AsyncMock(return_value=c)
    await s.submit('cpu','new','first message','chat','owner')
    await asyncio.gather(*s.background)
    assert [call.args[0] for call in c.request.await_args_list]==['thread/resume','turn/start']


async def test_active_owner_can_queue_without_reading_history_again(service):
    s=service;j=s.state.create_job('cpu','pt','t','chat','owner','task');s.state.update_job(j['id'],status='running',turn='turn')
    s.metadata=AsyncMock(side_effect=CompatibilityError('history unavailable'))
    item=await s.queue.enqueue('cpu','t','follow-up','chat','owner')
    assert item['status']=='queued';s.metadata.assert_not_awaited()


async def test_socket_relay_only_connects_existing_endpoint(tmp_path,service):
    h=service.config.hosts['cpu']
    with pytest.raises(ValueError):client_for(replace(h,transport='stdio'))
    with pytest.raises(ValueError):client_for(h)
    folder=tempfile.TemporaryDirectory(prefix='wb-',dir='/tmp')
    socket_path=folder.name+'/native.sock'
    async def echo(reader,writer):
        writer.write(await reader.read(100));await writer.drain();writer.close()
    server=await asyncio.start_unix_server(echo,path=socket_path)
    p=await asyncio.create_subprocess_exec(sys.executable,'-c',SOCKET_RELAY,socket_path,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
    p.stdin.write(b'native-bytes');await p.stdin.drain()
    assert await asyncio.wait_for(p.stdout.readexactly(12),3)==b'native-bytes'
    await p.wait();server.close();await server.wait_closed()
    folder.cleanup()
    client=client_for(replace(h,native_socket=socket_path))
    assert client.ws and '--listen' not in client.argv[-1] and 'exec python3' in client.argv[-1]
