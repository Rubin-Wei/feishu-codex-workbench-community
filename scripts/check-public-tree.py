#!/usr/bin/env python3
"""Fail on accidentally tracked secrets and runtime artifacts; print paths only."""
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
credential = re.compile(rb'(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
bad = []
for name in paths:
    if not name:
        continue
    p = Path(name)
    forbidden = p.name in {'.env','.env.local','config.local.toml','web-auth.json'} or any(x in p.parts for x in ('.local','node_modules','.spark')) or p.suffix in {'.sqlite','.db','.pem','.key'}
    if forbidden or credential.search((root/p).read_bytes()):
        bad.append(name)
if bad:
    raise SystemExit('Do not publish these paths: ' + ', '.join(bad))
print('Public tree checks passed.')
