from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex

from .config import Host
from .rpc import RpcClient


def ssh_argv(host: Host, command: str) -> list[str]:
    return ["ssh", *(["-F", os.environ["WORKBENCH_SSH_CONFIG"]] if os.getenv("WORKBENCH_SSH_CONFIG") else []), "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
            host.ssh, "bash -lc " + shlex.quote(command)]


SOCKET_RELAY = r'''
import os,select,socket,stat,sys
path=sys.argv[1]
if not stat.S_ISSOCK(os.stat(path).st_mode):raise ValueError('Configured native endpoint is not a socket')
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(path)
while True:
 for source in select.select([0,s],[],[])[0]:
  data=os.read(0,65536) if source==0 else s.recv(65536)
  if not data:sys.exit(0)
  if source==0:s.sendall(data)
  else:
   while data:data=data[os.write(1,data):]
'''


def client_for(host: Host, **kwargs):
    # Connect bytes to an already-running native daemon. Never execute Codex,
    # bootstrap another daemon, open a state DB, or fall back to a different CLI.
    if host.transport != 'proxy' or not host.native_socket or not host.native_socket.startswith('/'):
        raise ValueError('该机器尚未配置原生 Codex socket；工作台不会另起 Codex 或修复数据库')
    command = 'exec python3 -c ' + shlex.quote(SOCKET_RELAY) + ' ' + shlex.quote(host.native_socket)
    return RpcClient(ssh_argv(host, command), websocket=True, **kwargs)


# Passed as a single shell-quoted program; all variable data is JSON on stdin.
# realpath checks are performed on the remote filesystem, including symlinks.
REMOTE_FILES = r'''
import base64,json,os,pathlib,sys
q=json.load(sys.stdin)
p=pathlib.Path(q['path']).resolve(strict=True)
roots=[pathlib.Path(r).resolve(strict=True) for r in q['roots'] if pathlib.Path(r).exists()]
if not any(p==r or r in p.parents for r in roots): raise ValueError('Path outside allowed roots')
if q['action']=='dir':
 if not p.is_dir(): raise ValueError('Not a directory')
 children=[]
 for child in sorted(p.iterdir(),key=lambda x:x.name.lower()):
  if len(children)>=60: break
  try:
   resolved=child.resolve(strict=True)
   if child.is_dir() and not child.name.startswith('.') and any(resolved==r or r in resolved.parents for r in roots): children.append(str(child))
  except (OSError,ValueError): pass
 print(json.dumps({'path':str(p),'directories':children}))
elif q['action']=='image':
 if p.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'): raise ValueError('Only PNG/JPEG/WebP images are supported')
 if not p.is_file() or p.stat().st_size>10*1024*1024: raise ValueError('Image is missing or exceeds 10 MB')
 with p.open('rb') as f: data=f.read(10*1024*1024+1)
 if len(data)>10*1024*1024: raise ValueError('Image exceeds 10 MB')
 if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or (data.startswith(b'RIFF') and data[8:12]==b'WEBP')): raise ValueError('Invalid image header')
 print(json.dumps({'name':p.name,'data':base64.b64encode(data).decode()}))
else: raise ValueError('Unsupported action')
'''

# Compatibility reader for versions whose paginated RPC index is empty while
# the original rollout contains visible messages. No database repair or resume.
REMOTE_HISTORY = r'''
import json,pathlib,sys
q=json.load(sys.stdin)
p=pathlib.Path(q['path']).resolve(strict=True)
roots=[pathlib.Path(r).resolve(strict=True) for r in q['roots'] if pathlib.Path(r).exists()]
if not any(p==r or r in p.parents for r in roots): raise ValueError('Path outside allowed roots')
if p.suffix!='.jsonl' or not p.name.startswith('rollout-') or not p.is_file(): raise ValueError('Not a rollout file')
with p.open('rb') as f:
 first=f.readline(16*1024*1024)
 meta=json.loads(first)
 if meta.get('type')!='session_meta' or meta.get('payload',{}).get('id')!=q['thread']: raise ValueError('Rollout thread mismatch')
 size=f.seek(0,2)
 end=size if q.get('before') is None else int(q['before'])
 if end<0 or end>size: raise ValueError('Invalid rollout cursor')
 def lines_backwards(end):
  pos=end;buffer=b''
  while pos:
   n=min(pos,65536);pos-=n;f.seek(pos);buffer=f.read(n)+buffer
   while b'\n' in buffer:
    left,_,line=buffer.rpartition(b'\n');start=pos+len(left)+1;buffer=left
    if line: yield start,line
   if len(buffer)>16*1024*1024: raise ValueError('Rollout entry exceeds 16 MB')
  if buffer: yield 0,buffer
 items=[];seen=set();next_cursor=None;bytes_out=0
 for offset,line in lines_backwards(end):
  try: row=json.loads(line)
  except (ValueError,UnicodeDecodeError): continue
  payload=row.get('payload',{})
  if row.get('type')!='event_msg' or payload.get('type')!='item_completed': continue
  item=payload.get('item',{});kind=item.get('type','').lower()
  if kind not in ('usermessage','agentmessage'): continue
  text=item.get('text') or '\n'.join(c.get('text','') for c in item.get('content',[]) if c.get('type','').lower()=='text')
  if not text: continue
  identity=item.get('id') or 'rollout:'+str(offset)
  if identity in seen: continue
  # Avoid oversized heartbeat batches; leave the next complete message for the next page.
  if items and bytes_out+len(text.encode())>300000:
   next_cursor='rollout:'+str(offset+len(line)+1);break
  if len(text.encode())>700000: raise ValueError('Single history message exceeds web transport limit; read it in the original Codex client')
  seen.add(identity);bytes_out+=len(text.encode())
  result={'id':identity,'type':'userMessage' if kind=='usermessage' else 'agentMessage'}
  if item.get('clientId') or item.get('client_id'):result['clientId']=item.get('clientId') or item.get('client_id')
  if kind=='usermessage':result['content']=[{'type':'text','text':text}]
  else:result['text']=text
  items.append(result)
  if len(items)>=100:
   next_cursor='rollout:'+str(offset);break
 print(json.dumps({'data':items,'nextCursor':next_cursor},ensure_ascii=False))
'''


async def remote_history(host: Host, path: str, thread: str, cursor=None):
    host.validate_path(path)
    before = None
    if cursor:
        if not cursor.startswith('rollout:'):
            raise ValueError('Invalid rollout cursor')
        before = int(cursor.split(':', 1)[1])
    process = await asyncio.create_subprocess_exec(
        *ssh_argv(host, 'python3 -c ' + shlex.quote(REMOTE_HISTORY)),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(json.dumps({
            'path': path, 'roots': host.roots, 'thread': thread, 'before': before}).encode()), 40)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError('历史文件只读访问失败：' + err.decode(errors='replace').splitlines()[-1][:300])
    return json.loads(out)


REMOTE_TITLES = r'''
import json,pathlib,sys
q=json.load(sys.stdin);p=pathlib.Path(q['path']).resolve(strict=True)
roots=[pathlib.Path(r).resolve(strict=True) for r in q['roots'] if pathlib.Path(r).exists()]
if not any(p==r or r in p.parents for r in roots): raise ValueError('Path outside allowed roots')
sessions=next((r for r in p.parents if r.name in ('sessions','archived_sessions')),None)
names={}
if sessions:
 index=(sessions.parent/'session_index.jsonl').resolve()
 if index.exists():
  if not any(index==r or r in index.parents for r in roots): raise ValueError('Index outside allowed roots')
  with index.open() as f:
   for line in f:
    try:
     v=json.loads(line)
     if isinstance(v.get('id'),str) and isinstance(v.get('thread_name'),str):names[v['id']]=v['thread_name']
    except ValueError:continue
print(json.dumps(names,ensure_ascii=False))
'''


async def remote_titles(host: Host, path: str):
    host.validate_path(path)
    process = await asyncio.create_subprocess_exec(
        *ssh_argv(host, 'python3 -c ' + shlex.quote(REMOTE_TITLES)),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(json.dumps({
            'path': path, 'roots': host.roots}).encode()), 25)
    except BaseException:
        process.kill(); await process.wait(); raise
    if process.returncode:
        raise ValueError('会话名称索引读取失败：' + err.decode(errors='replace').splitlines()[-1][:200])
    return json.loads(out)


async def remote_file(host: Host, path: str, action="dir"):
    host.validate_path(path)
    process = await asyncio.create_subprocess_exec(
        *ssh_argv(host, "python3 -c " + shlex.quote(REMOTE_FILES)),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(json.dumps({
            "path": path, "roots": host.roots, "action": action}).encode()), 40)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("远程文件访问失败：" + err.decode(errors="replace").splitlines()[-1][:300])
    result = json.loads(out)
    if action == "image":
        result["data"] = base64.b64decode(result["data"])
    return result
