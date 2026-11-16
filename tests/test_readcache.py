import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, patch
from feishu_codex_workbench.cluster import REMOTE_TITLES
from feishu_codex_workbench.config import Host
from test_webrelay import relay


async def test_catalog_warms_all_pages_and_retains_data_on_disconnect(relay):
    s=relay.s
    s.list_sessions=AsyncMock(side_effect=[
        {'data':[{'id':'a','cwd':'/work','name':'Original name'}],'nextCursor':'next'},
        {'data':[{'id':'b','cwd':'/work','name':'Second'}],'nextCursor':None},
    ])
    await relay.cache.sync_host('h')
    assert [t['id'] for t in relay.snapshot()['catalogs']['h']['threads']]==['a','b']
    assert relay.cache.catalogs['h']['connected']
    assert relay.cache.queue.qsize()==2
    s.list_sessions.side_effect=ConnectionError('disconnected')
    await relay.cache.sync_host('h')
    assert not relay.cache.catalogs['h']['connected']
    assert len(relay.cache.catalogs['h']['threads'])==2
    await relay.client.aclose()


async def test_old_cache_ack_cannot_hide_newer_revision(relay):
    def history(text):return {'thread':{'id':'t','cwd':'/work','name':'Native'},'messages':[{'id':'a','role':'assistant','text':text}]}
    relay.cache.remember('h','t',history('old'))
    old=relay.cache.pending()
    relay.cache.remember('h','t',history('new'))
    relay.cache.acknowledge(old)
    new=relay.cache.pending()
    assert new[0]['value']['messages'][0]['text']=='new'
    relay.cache.acknowledge(new)
    assert relay.cache.pending()==[]
    assert relay.cache.pending(budget=1)==[]
    await relay.client.aclose()


async def test_missing_rpc_names_use_existing_index_without_renaming(relay,tmp_path):
    s=relay.s;s.config.hosts['h']=Host('h','H','H','h',str(tmp_path),(str(tmp_path),),'h')
    c=AsyncMock();c.request.return_value={'data':[
        {'id':'a','cwd':str(tmp_path),'path':str(tmp_path/'rollout-a.jsonl'),'name':None},
        {'id':'b','cwd':str(tmp_path),'name':'RPC name'},
    ],'nextCursor':None}
    s.get_client=AsyncMock(return_value=c)
    with patch('feishu_codex_workbench.service.remote_titles',new_callable=AsyncMock) as titles:
        titles.return_value={'a':'Codex sidebar name','b':'older name'}
        page=await s.list_sessions('h')
        assert [t['name'] for t in page['data']]==['Codex sidebar name','RPC name']
        assert all(call.args[0]=='thread/list' for call in c.request.await_args_list)
    await relay.client.aclose()


def test_title_reader_uses_last_name_and_does_not_write(tmp_path):
    sessions=tmp_path/'.codex'/'sessions'/'2026';sessions.mkdir(parents=True)
    rollout=sessions/'rollout-t.jsonl';rollout.write_text('')
    index=tmp_path/'.codex'/'session_index.jsonl'
    index.write_text(json.dumps({'id':'t','thread_name':'Old'})+'\n'+json.dumps({'id':'t','thread_name':'Exact desktop title'})+'\n')
    before=index.read_bytes()
    r=subprocess.run([sys.executable,'-c',REMOTE_TITLES],input=json.dumps({'path':str(rollout),'roots':[str(tmp_path)]}),text=True,capture_output=True)
    assert r.returncode==0 and json.loads(r.stdout)=={'t':'Exact desktop title'}
    assert before==index.read_bytes()
