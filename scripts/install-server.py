#!/usr/bin/env python3
"""Install an isolated supervisor; do not alter machine init or native Codex."""
import os, pathlib,subprocess
base=pathlib.Path(__file__).resolve().parent.parent
os.umask(0o077)
for p in ['.local/run','.local/logs']:(base/p).mkdir(parents=True,exist_ok=True)
(base/'.local/supervisord.conf').write_text(f'''[unix_http_server]
file={base}/.local/run/supervisor.sock
chmod=0600
[supervisord]
logfile={base}/.local/logs/supervisord.log
logfile_maxbytes=5MB
logfile_backups=2
pidfile={base}/.local/run/supervisord.pid
childlogdir={base}/.local/logs
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{base}/.local/run/supervisor.sock
[program:workbench]
command=/bin/bash {base}/scripts/run-server.sh
directory={base}
autostart=true
autorestart=true
startsecs=5
startretries=100
stopasgroup=true
killasgroup=true
stopwaitsecs=25
stdout_logfile={base}/.local/logs/workbench.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
redirect_stderr=true
''')
subprocess.run(['/bin/bash',str(base/'scripts/ensure-server.sh')],check=True)
print('Isolated supervisor installed. Container recreation still requires its startup hook.')
