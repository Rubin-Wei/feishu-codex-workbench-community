#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
unset PYTHONPATH
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
exec .venv/bin/python scripts/watch-memory.py
