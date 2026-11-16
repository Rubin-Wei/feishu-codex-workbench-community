#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec .venv/bin/feishu-codex run
