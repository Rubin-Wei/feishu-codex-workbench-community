import json
import subprocess
import sys
from unittest.mock import AsyncMock, patch

from feishu_codex_workbench.cluster import REMOTE_HISTORY
from feishu_codex_workbench.config import Host
from test_webrelay import relay


def read(root, path, thread='t', before=None):
    return subprocess.run([sys.executable, '-c', REMOTE_HISTORY], input=json.dumps({
        'roots': [str(root)], 'path': str(path), 'thread': thread, 'before': before,
    }), text=True, capture_output=True)


def item(i):
    return {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
        'type': 'UserMessage' if i % 2 == 0 else 'AgentMessage', 'id': str(i),
        'content': [{'type': 'text' if i % 2 == 0 else 'Text', 'text': '消息 ' + str(i)}]}}}


def test_readonly_rollout_pagination_excludes_internal_context(tmp_path):
    p = tmp_path / 'rollout-test.jsonl'
    rows = [{'type': 'session_meta', 'payload': {'id': 't'}},
            {'type': 'response_item', 'payload': {'role': 'developer', 'content': ['PRIVATE']}},
            *[item(i) for i in range(205)]]
    p.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    original = p.read_bytes()
    first = json.loads(read(tmp_path, p).stdout)
    assert len(first['data']) == 100 and first['data'][0]['id'] == '204'
    # An append must not shift a previously returned byte-offset cursor.
    with p.open('a') as f: f.write(json.dumps(item(205)) + '\n')
    second = json.loads(read(tmp_path, p, before=first['nextCursor'].split(':')[1]).stdout)
    third = json.loads(read(tmp_path, p, before=second['nextCursor'].split(':')[1]).stdout)
    ids = [int(x['id']) for page in (first, second, third) for x in page['data']]
    assert ids == list(range(204, -1, -1))
    assert third['nextCursor'] is None
    assert 'PRIVATE' not in json.dumps(first)
    assert json.loads(read(tmp_path, p, before=0).stdout)['data'] == []
    assert p.read_bytes().startswith(original)


def test_rollout_identity_and_symlink_boundaries(tmp_path):
    root = tmp_path / 'owner'; root.mkdir()
    outside = tmp_path / 'rollout-outside.jsonl'
    outside.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 't'}}) + '\n')
    link = root / 'rollout-link.jsonl'; link.symlink_to(outside)
    assert 'outside allowed roots' in read(root, link).stderr
    local = root / 'rollout-local.jsonl'; local.write_bytes(outside.read_bytes())
    assert 'thread mismatch' in read(root, local, 'different').stderr


async def test_empty_rpc_uses_readonly_fallback_and_keeps_cursor(relay, tmp_path):
    s = relay.s
    s.config.hosts['h'] = Host('h','H','H','test-host',str(tmp_path),(str(tmp_path),),'h')
    s.metadata = AsyncMock(return_value={'id':'t','cwd':str(tmp_path),'path':str(tmp_path/'rollout-t.jsonl')})
    c = AsyncMock(); c.request.return_value = {'data': [], 'nextCursor': None}
    s.get_client = AsyncMock(return_value=c)
    with patch('feishu_codex_workbench.webrelay.remote_history', new_callable=AsyncMock) as fallback:
        fallback.return_value = {'data':[{'id':'a','type':'agentMessage','text':'answer'},
            {'id':'u','type':'userMessage','content':[{'type':'text','text':'question'}]}], 'nextCursor':'rollout:123'}
        page = await relay.history('h','t')
        assert [m['role'] for m in page['messages']] == ['user','assistant']
        assert page['nextCursor'] == 'rollout:123'
        await relay.history('h','t','rollout:123')
        assert c.request.await_count == 1  # opaque rollout cursors never reach RPC
        assert fallback.await_args.args[-1] == 'rollout:123'
    await relay.client.aclose()
