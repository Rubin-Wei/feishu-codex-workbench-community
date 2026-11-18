"""Bounded, read-only previews inside a host's configured owner directories."""
from __future__ import annotations

import asyncio
import json
import posixpath
import shlex

from .cluster import ssh_argv
from .config import Host


TEXT_PREVIEW_BYTES = 160 * 1024
BINARY_PREVIEW_BYTES = 512 * 1024

# The remote program is fixed and shell quoted. Paths and roots only enter via
# JSON stdin. Never turn assistant-authored paths into shell commands.
REMOTE_PREVIEW = r'''
import base64,codecs,json,os,pathlib,stat,sys

TEXT_LIMIT=160*1024
BINARY_LIMIT=512*1024

def protected(path):
 parts=[part.lower() for part in path.parts]
 name=parts[-1] if parts else ''
 if any(part in ('.ssh','.aws','.gnupg','.git','.lark-cli','lark-cli') for part in parts):return True
 if any(part.startswith('.env') for part in parts):return True
 if name.startswith(('id_rsa','id_ed25519','id_ecdsa','id_dsa')):return True
 if name.endswith(('.pem','.key','.p12','.pfx')):return True
 if name in ('.netrc','.npmrc','.pypirc','.git-credentials','api_key','api-key','token','stored_tokens','access_token','rclone.conf'):return True
 if name.startswith(('auth.json','credentials.json','credentials.toml','credentials.yaml','credentials.yml')) or name=='credentials':return True
 if any(parts[i]=='.config' and parts[i+1] in ('wandb','rclone','gcloud','gh') for i in range(len(parts)-1)):return True
 if 'huggingface' in parts and name.startswith(('token','stored_tokens')):return True
 if any(part in ('.kube','.docker') for part in parts) and name in ('config','config.json'):return True
 return False

def preview(q):
 value=q['path'];cwd_value=q['cwd']
 if not isinstance(value,str) or not value or len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value):
  raise ValueError('文件路径无效')
 if not isinstance(cwd_value,str) or not pathlib.Path(cwd_value).is_absolute() or '..' in pathlib.Path(cwd_value).parts:
  raise ValueError('会话工作目录无效')
 roots=[pathlib.Path(r).resolve(strict=True) for r in q['roots'] if pathlib.Path(r).is_dir()]
 def allowed(p):return any(p==root or root in p.parents for root in roots)
 cwd=pathlib.Path(cwd_value).resolve(strict=True)
 if not allowed(cwd):raise ValueError('会话工作目录不在该机器配置的个人工作区域内')
 if not cwd.is_dir():raise ValueError('会话工作目录不是目录')
 raw=pathlib.Path(value)
 if not raw.is_absolute():raw=cwd/raw
 if protected(raw):raise ValueError('凭据或私钥文件不能在工作台预览')
 path=raw.resolve(strict=True)
 if not allowed(path):raise ValueError('文件不在该机器配置的个人工作区域内')
 if protected(path):raise ValueError('凭据或私钥文件不能在工作台预览')
 if not stat.S_ISREG(path.stat().st_mode):raise ValueError('只能预览普通文件')
 # Nonblocking open prevents FIFOs from hanging. O_NOFOLLOW and checking the
 # opened descriptor also protect against symlinks changed between checks.
 flags=os.O_RDONLY|os.O_NONBLOCK|getattr(os,'O_CLOEXEC',0)|getattr(os,'O_NOFOLLOW',0)
 fd=os.open(str(path),flags)
 with os.fdopen(fd,'rb') as stream:
  info=os.fstat(stream.fileno())
  if not stat.S_ISREG(info.st_mode):raise ValueError('只能预览普通文件')
  descriptor=pathlib.Path('/proc/self/fd')/str(stream.fileno())
  if descriptor.exists():
   opened=descriptor.resolve(strict=True)
   if not allowed(opened):raise ValueError('文件不在该机器配置的个人工作区域内')
   if protected(opened):raise ValueError('凭据或私钥文件不能在工作台预览')
   path=opened
  header=stream.read(16)
  kind='text';mime='text/plain'
  if header.startswith(b'\x89PNG\r\n\x1a\n'):kind,mime='image','image/png'
  elif header.startswith(b'\xff\xd8\xff'):kind,mime='image','image/jpeg'
  elif header[:6] in (b'GIF87a',b'GIF89a'):kind,mime='image','image/gif'
  elif header.startswith(b'RIFF') and header[8:12]==b'WEBP':kind,mime='image','image/webp'
  elif header.startswith(b'%PDF-'):kind,mime='pdf','application/pdf'
  limit=TEXT_LIMIT if kind=='text' else BINARY_LIMIT
  if kind!='text' and info.st_size>limit:raise ValueError('图片或 PDF 超过预览上限（512 KiB）')
  stream.seek(0);data=stream.read(limit+1)
  truncated=len(data)>limit or info.st_size>limit
  data=data[:limit]
  result={'path':str(path),'name':path.name,'size':info.st_size,'kind':kind,'mime':mime,'truncated':truncated,'bytesRead':len(data)}
  if kind!='text':
   if truncated:raise ValueError('图片或 PDF 超过预览上限（512 KiB）')
   result.update(encoding='base64',data=base64.b64encode(data).decode('ascii'))
  else:
   if path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif','.pdf'):
    raise ValueError('图片或 PDF 文件头无效')
   if any(byte<32 and byte not in (9,10,13) for byte in data) or b'\x7f' in data:
    raise ValueError('暂不支持此二进制文件；可预览 UTF-8 文本、PNG、JPEG、WebP、GIF 和 PDF')
   try:
    decoder=codecs.getincrementaldecoder('utf-8-sig')('strict')
    content=decoder.decode(data,final=not truncated)
   except UnicodeDecodeError:
    raise ValueError('暂不支持此文件编码；文本预览需要 UTF-8') from None
   if 'PRIVATE KEY-----' in content:raise ValueError('凭据或私钥文件不能在工作台预览')
   # HTML and SVG intentionally remain literal text, never executable markup.
   result.update(encoding='utf-8',text=content,startLine=1,endLine=len(content.splitlines()))
  return result

try:
 print(json.dumps(preview(json.load(sys.stdin)),ensure_ascii=False))
except FileNotFoundError:
 print(json.dumps({'error':'文件不存在或链接已失效'},ensure_ascii=False));sys.exit(1)
except PermissionError:
 print(json.dumps({'error':'没有权限读取此文件'},ensure_ascii=False));sys.exit(1)
except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
 message=str(error) if isinstance(error,ValueError) else '文件无法读取或路径无效'
 print(json.dumps({'error':message},ensure_ascii=False));sys.exit(1)
'''


async def preview_file(host: Host, path: str, cwd: str) -> dict:
    """Read a file without changing host state; callers supply trusted thread cwd.

    Text includes a bounded UTF-8 prefix and line metadata. Images and PDFs have
    bounded base64 data. Errors are safe, user-facing ValueErrors. The caller
    should strip display-only line suffixes before passing an actual file path.
    """
    host.validate_path(cwd)
    if (not isinstance(path, str) or not path or len(path) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError("文件路径无效")
    host.validate_path(posixpath.normpath(posixpath.join(cwd, path)))
    # ssh_argv may use a login shell, so explicitly enter the validated thread
    # cwd in the remote command rather than relying on the shell's default cwd.
    command = "cd " + shlex.quote(cwd) + " && exec python3 -c " + shlex.quote(REMOTE_PREVIEW)
    process = await asyncio.create_subprocess_exec(
        *ssh_argv(host, command), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(process.communicate(json.dumps({
            "path": path, "cwd": cwd, "roots": host.roots}).encode()), timeout=35)
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise ValueError("文件预览读取超时，请稍后重试") from None
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    try:
        result = json.loads(out)
    except (UnicodeDecodeError, ValueError):
        # SSH/Python diagnostics can contain shell startup output; don't return
        # arbitrary remote stderr (or any credential value) to the browser.
        raise ValueError("文件预览连接失败，请检查主机连接和会话工作目录") from None
    if not isinstance(result, dict):
        raise ValueError("文件预览返回了无效结果")
    if result.get("error"):
        raise ValueError(result["error"])
    if process.returncode:
        raise ValueError("文件预览读取失败")
    return result
