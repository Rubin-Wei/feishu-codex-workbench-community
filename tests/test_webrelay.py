import json
from unittest.mock import AsyncMock
import pytest
from feishu_codex_workbench.config import Config, Host
from feishu_codex_workbench.service import Workbench
from feishu_codex_workbench.state import State
from feishu_codex_workbench.webrelay import WebRelay

@pytest.fixture
def relay(tmp_path,monkeypatch):
 for k,v in {'WORKBENCH_SITE_URL':'https://example.invalid','WORKBENCH_AGENT_SECRET':'secret','WORKBENCH_SITE_ACCESS_TOKEN':'access'}.items():monkeypatch.setenv(k,v)
 s=Workbench(Config({},tmp_path,tmp_path,'codex','','','owner'),State(tmp_path))
 s.state.put('owner',{'open_id':'owner','chat':'chat'})
 w=WebRelay(s)
 yield w
 s.state.close()

async def test_recovery_never_replays_processing(relay):
 with relay.s.state.db:relay.s.state.db.execute("INSERT INTO web_commands(id,status) VALUES('request','processing')")
 w=WebRelay(relay.s)
 row=dict(w.s.state.db.execute('SELECT * FROM web_commands').fetchone())
 assert row['status']=='ready' and row['ok']==0
 assert '未自动重新执行' in json.loads(row['result'])['error']
 await w.client.aclose();await relay.client.aclose()

async def test_history_preserves_order_and_cursor(relay):
 relay.s.metadata=AsyncMock(return_value={'id':'t','cwd':'/work'})
 c=AsyncMock();c.request.return_value={'nextCursor':'older','data':[{'item':{'id':'a','type':'agentMessage','text':'answer'}},{'item':{'id':'u','type':'userMessage','content':[{'type':'text','text':'question'}]}}]}
 relay.s.get_client=AsyncMock(return_value=c)
 page=await relay.history('host','t')
 assert [m['text'] for m in page['messages']]==['question','answer']
 assert page['nextCursor']=='older'
 await relay.client.aclose()


async def test_history_preserves_native_client_id_for_optimistic_message_merge(relay):
 page=relay.visible_history(relay.s,{'id':'t'},[{'type':'userMessage','id':'native-id','clientId':'sent-client-id','content':[{'type':'text','text':'one message'}]}],None)
 assert page['messages'][0]['clientId']=='sent-client-id'
 await relay.client.aclose()

async def test_supervisor_model_and_effort_are_pinned(relay):
 s=relay.s;c=AsyncMock();c.request.side_effect=[{'thread':{'id':'t'}},{}, {}, {'turn':{'id':'turn'}}]
 s.get_client=AsyncMock(return_value=c);s.check_idle=AsyncMock()
 thread=await s.supervisor('chat');await s.submit('supervisor',thread,'test','chat','owner')
 calls=c.request.call_args_list
 assert calls[0].args[1]['model']=='gpt-6.1-sol'
 assert calls[0].args[1]['config']['model_reasoning_effort']=='medium'
 assert calls[-1].args[1]['model']=='gpt-6.1-sol' and calls[-1].args[1]['effort']=='medium'
 await relay.client.aclose()

async def test_miaoda_scoped_key_does_not_send_sites_credentials(relay,monkeypatch):
 monkeypatch.setenv('WORKBENCH_AGENT_URL','https://example.invalid/openapi/agent')
 monkeypatch.setenv('WORKBENCH_OPENAPI_KEY','test-key')
 w=WebRelay(relay.s)
 assert w.agent_url.endswith('/openapi/agent')
 assert w.client.headers['Authorization']=='Bearer test-key'
 assert 'X-Api-Key' not in w.client.headers
 assert 'OAI-Sites-Authorization' not in w.client.headers
 await w.client.aclose();await relay.client.aclose()

async def test_project_index_preserves_names_paths_and_pagination(relay):
 relay.s.list_sessions=AsyncMock(return_value={'data':[{'id':'t','name':'Experiment','cwd':'/projects/a','preview':None,'private':'excluded'}],'nextCursor':'older'})
 page=await relay.dispatch('sessions',{'host':'h','limit':100})
 relay.s.list_sessions.assert_awaited_once_with('h',None,100)
 assert page['data'][0]['name']=='Experiment' and page['data'][0]['cwd']=='/projects/a'
 assert page['data'][0]['preview']=='' and 'private' not in page['data'][0]
 assert page['nextCursor']=='older'
 await relay.client.aclose()
