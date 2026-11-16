#!/usr/bin/env python3
"""Run only the workbench process tree, restarting after exit or excess RSS.
Native remote Codex daemons and experiment processes are outside this tree.
"""
import os,signal,subprocess,sys,time
from pathlib import Path
base=Path(__file__).resolve().parent.parent
limit=int(os.getenv('WORKBENCH_MEMORY_LIMIT_MB','2048'))*1024
stop=False
child=None

def signal_stop(*_):
 global stop
 stop=True
 if child and child.poll() is None:
  try:os.killpg(child.pid,signal.SIGTERM)
  except ProcessLookupError:pass
signal.signal(signal.SIGTERM,signal_stop);signal.signal(signal.SIGINT,signal_stop)

def tree_rss(pid):
 rows={}
 for folder in Path('/proc').iterdir():
  if not folder.name.isdigit():continue
  try:
   fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (folder/'status').read_text().splitlines()}
   rows[int(folder.name)]=(int(fields['PPid']),int(fields.get('VmRSS','0 kB').split()[0]))
  except (OSError,ValueError,KeyError):pass
 descendants={pid}
 while True:
  more={p for p,(parent,_) in rows.items() if parent in descendants}-descendants
  if not more:break
  descendants.update(more)
 return sum(rows.get(p,(0,0))[1] for p in descendants)

while not stop:
 child=subprocess.Popen([str(base/'.venv/bin/feishu-codex'),'run'],cwd=base,start_new_session=True)
 while child.poll() is None and not stop:
  time.sleep(5)
  if tree_rss(child.pid)>limit:
   print('Workbench memory budget exceeded; restarting managed processes only.',flush=True)
   os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
 if stop and child.poll() is None:
  try:child.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
 if not stop:time.sleep(5)
