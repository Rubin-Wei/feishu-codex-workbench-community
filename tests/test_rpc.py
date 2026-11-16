import asyncio
import sys

import pytest

from feishu_codex_workbench.rpc import RpcClient, RpcError


SERVER = r'''
import os,sys,json
from wsproto import WSConnection,ConnectionType
from wsproto.events import Request,AcceptConnection,TextMessage,Ping
ws=WSConnection(ConnectionType.SERVER) if sys.argv[1]=='ws' else None
held=None
def send(obj):
 data=json.dumps(obj)
 if ws:
  mid=len(data)//2
  os.write(1,ws.send(TextMessage(data=data[:mid],message_finished=False)))
  os.write(1,ws.send(TextMessage(data=data[mid:],message_finished=True)))
 else: print(data,flush=True)
def handle(m):
 global held
 if 'method' not in m:
  if m.get('id')=='server-request': send({'id':held,'result':m['result']})
  return
 name=m['method']
 if name=='initialize': send({'id':m['id'],'result':{'ok':True}})
 elif name=='initialized': pass
 elif name=='slow': held=m['id']
 elif name=='fast':
  send({'id':m['id'],'result':{'value':'fast'}});send({'id':held,'result':{'value':'slow'}})
 elif name=='fail': send({'id':m['id'],'error':{'code':-123,'message':'test failure'}})
 elif name=='interaction':
  held=m['id'];send({'id':'server-request','method':'item/tool/call','params':{'tool':'test'}})
 elif name=='exit': sys.exit(0)
 else: send({'id':m['id'],'result':{'value':'nested'}})
if ws:
 fragments=[]
 while True:
  data=os.read(0,65536)
  if not data: break
  ws.receive_data(data)
  for e in ws.events():
   if isinstance(e,Request):
    os.write(1,ws.send(AcceptConnection()));os.write(1,ws.send(Ping(payload=b'alive')))
   elif isinstance(e,TextMessage):
    fragments.append(e.data)
    if e.message_finished:
     handle(json.loads(''.join(fragments)));fragments=[]
else:
 for line in sys.stdin: handle(json.loads(line))
'''


@pytest.mark.parametrize("websocket", [False, True])
async def test_rpc_multiplexing_and_nested_server_requests(websocket):
    client = RpcClient([sys.executable, "-u", "-c", SERVER, "ws" if websocket else "stdio"], websocket=websocket)
    async def on_request(method, params):
        assert method == "item/tool/call"
        result = await client.request("nested")
        return {"success": True, "nested": result}
    client.on_request = on_request
    try:
        assert await client.start() == {"ok": True}
        slow = asyncio.create_task(client.request("slow"))
        await asyncio.sleep(0.01)
        assert await client.request("fast") == {"value": "fast"}
        assert await slow == {"value": "slow"}
        assert await client.request("interaction") == {"success": True, "nested": {"value": "nested"}}
        with pytest.raises(RpcError, match="test failure"):
            await client.request("fail")
        with pytest.raises(ConnectionError):
            await client.request("exit")
    finally:
        await client.close()
