"""Read only the explicitly selected Lark CLI app credential, without exporting it.

Optional macOS adapter for the official CLI's existing encrypted credential store.
The store layout is documented by larksuite/cli/internal/keychain/keychain_darwin.go.
No credentials, master keys, or keychain ACLs are created/changed by this adapter.
"""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path


def from_lark_profile(profile):
    if sys.platform != "darwin":
        raise ValueError("Lark CLI profile adapter currently supports macOS; use FEISHU_APP_SECRET on other platforms")
    config = json.loads((Path.home() / ".lark-cli/config.json").read_text())
    app = next((a for a in config["apps"] if a.get("name", a["appId"]) == profile), None)
    if not app:
        raise ValueError("指定的飞书 CLI profile 不存在")
    ref = app["appSecret"]
    if not isinstance(ref, dict) or ref.get("source") != "keychain" or ref.get("id") != "appsecret:" + app["appId"]:
        raise ValueError("不支持该 CLI 凭据引用；请单独配置 FEISHU_APP_SECRET")
    folder = Path.home() / "Library/Application Support/lark-cli"
    blob = (folder / (re.sub(r"[^a-zA-Z0-9._-]", "_", ref["id"]) + ".enc")).read_bytes()
    from Crypto.Cipher import AES
    def decrypt(key):
        if len(key) != 32 or len(blob) < 28:
            raise ValueError("无效的凭据存储")
        cipher = AES.new(key, AES.MODE_GCM, nonce=blob[:12])
        return cipher.decrypt_and_verify(blob[12:-16], blob[-16:]).decode()
    existing_file_key = folder / "master.key.file"
    if existing_file_key.exists():
        try:
            return app["appId"], decrypt(existing_file_key.read_bytes())
        except ValueError:
            pass
    # Capture stdout in memory; never log or print the system keychain result.
    result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "lark-cli",
                             "-a", "master.key", "-w"], capture_output=True, timeout=8)
    if result.returncode:
        raise ValueError("系统钥匙串未允许读取该应用凭据；请允许本机访问，或单独配置 App Secret")
    encoded = result.stdout.strip()
    if encoded.startswith(b"go-keyring-base64:"):
        encoded = base64.b64decode(encoded.split(b":", 1)[1], validate=True)
    elif encoded.startswith(b"go-keyring-encoded:"):
        encoded = bytes.fromhex(encoded.split(b":", 1)[1].decode())
    return app["appId"], decrypt(base64.b64decode(encoded, validate=True))
