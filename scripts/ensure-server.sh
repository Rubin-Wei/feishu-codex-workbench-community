#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p .local/run .local/logs
exec 9>.local/run/launch.lock
flock -n 9 || exit 0
if .venv/bin/supervisorctl -c .local/supervisord.conf pid >/dev/null 2>&1; then exit 0; fi
.venv/bin/supervisord -c .local/supervisord.conf
