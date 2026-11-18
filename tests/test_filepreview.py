import asyncio
import base64
import json
import subprocess
import sys

import pytest

from feishu_codex_workbench.config import Host
from feishu_codex_workbench.filepreview import (
    BINARY_PREVIEW_BYTES, REMOTE_PREVIEW, TEXT_PREVIEW_BYTES, preview_file,
)


def run_preview(root, path, cwd=None):
    result = subprocess.run([sys.executable, "-c", REMOTE_PREVIEW], input=json.dumps({
        "roots": [str(root)], "path": str(path), "cwd": str(cwd or root),
    }), capture_output=True, text=True, timeout=5)
    return result.returncode, json.loads(result.stdout)


def test_relative_utf8_text_and_literal_markup(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    (tmp_path / "readme.md").write_text("# 中文\n<script>alert('test')</script>\n")
    status, result = run_preview(tmp_path, "../readme.md", folder)
    assert status == 0
    assert result["path"] == str(tmp_path / "readme.md")
    assert result["kind"] == "text"
    assert result["mime"] == "text/plain"
    assert result["text"] == "# 中文\n<script>alert('test')</script>\n"
    assert result["startLine"] == 1 and result["endLine"] == 2
    assert not result["truncated"]
    (tmp_path / "drawing.svg").write_text('<svg onload="alert(1)"/>')
    assert run_preview(tmp_path, "drawing.svg")[1]["kind"] == "text"


def test_traversal_and_symlink_outside_roots_are_denied(tmp_path):
    root = tmp_path / "owner"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("outside")
    (root / "escape.txt").symlink_to(tmp_path / "outside.txt")
    (root / "bad-cwd").symlink_to(tmp_path, target_is_directory=True)
    for path, cwd in [("../outside.txt", root), ("escape.txt", root), ("outside.txt", root / "bad-cwd")]:
        status, result = run_preview(root, path, cwd)
        assert status != 0
        assert "个人工作区域" in result["error"]


@pytest.mark.parametrize("path", [
    ".env", ".env.production", ".envrc", ".codex/auth.json", ".codex/auth.json.backup",
    ".cache/huggingface/token", ".ssh/id_rsa", ".aws/credentials",
    ".config/wandb/api_key", ".config/rclone/hdd2.conf", ".netrc", "private.pem",
    ".lark-cli/config.json", ".local/share/lark-cli/master.key.file", "rclone.conf",
])
def test_secret_files_and_links_are_denied(tmp_path, path):
    secret = tmp_path / path
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("this must never enter a preview")
    (tmp_path / "innocent.txt").symlink_to(secret)
    for value in (path, "innocent.txt"):
        status, result = run_preview(tmp_path, value)
        assert status != 0
        assert "凭据或私钥" in result["error"]
        assert "this must never" not in json.dumps(result)


def test_renamed_private_key_is_denied(tmp_path):
    (tmp_path / "readme.txt").write_text("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nexample\n")
    assert "凭据或私钥" in run_preview(tmp_path, "readme.txt")[1]["error"]


def test_plain_binary_invalid_utf8_and_invalid_image_are_denied(tmp_path):
    for name, data in (("file.bin", b"\x00secret"), ("file.txt", b"\xff\xfe"), ("file.png", b"not an image")):
        (tmp_path / name).write_bytes(data)
        assert run_preview(tmp_path, name)[0] != 0


@pytest.mark.parametrize("name,data,mime,kind", [
    ("plot.png", b"\x89PNG\r\n\x1a\nexample", "image/png", "image"),
    ("photo.jpg", b"\xff\xd8\xffexample", "image/jpeg", "image"),
    ("plot.webp", b"RIFF0000WEBPexample", "image/webp", "image"),
    ("animation.gif", b"GIF89aexample", "image/gif", "image"),
    ("report.pdf", b"%PDF-1.7\nexample", "application/pdf", "pdf"),
])
def test_supported_media_has_bounded_base64(tmp_path, name, data, mime, kind):
    (tmp_path / name).write_bytes(data)
    status, result = run_preview(tmp_path, name)
    assert status == 0
    assert result["kind"] == kind and result["mime"] == mime
    assert base64.b64decode(result["data"]) == data
    assert not result["truncated"]


def test_text_truncates_at_utf8_boundary_and_transport_stays_bounded(tmp_path):
    value = b"a" * (TEXT_PREVIEW_BYTES - 1) + "中文".encode()
    (tmp_path / "large.txt").write_bytes(value)
    status, result = run_preview(tmp_path, "large.txt")
    assert status == 0 and result["truncated"]
    assert result["text"] == "a" * (TEXT_PREVIEW_BYTES - 1)
    assert "\ufffd" not in result["text"]
    assert result["size"] == len(value)
    (tmp_path / "max.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (BINARY_PREVIEW_BYTES - 8))
    status, result = run_preview(tmp_path, "max.png")
    assert status == 0
    assert len(json.dumps(result).encode()) < 700_000
    (tmp_path / "max.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * BINARY_PREVIEW_BYTES)
    assert "512 KiB" in run_preview(tmp_path, "max.png")[1]["error"]


def test_nonregular_and_missing_files_fail_without_hanging(tmp_path):
    import os
    os.mkfifo(tmp_path / "pipe")
    assert "普通文件" in run_preview(tmp_path, "pipe")[1]["error"]
    assert "普通文件" in run_preview(tmp_path, ".")[1]["error"]
    assert "不存在" in run_preview(tmp_path, "missing.txt")[1]["error"]


def test_shell_metacharacters_are_literal_paths(tmp_path, monkeypatch):
    # Exercise the production async wrapper while keeping the test's shell
    # independent of the developer's login profile.
    monkeypatch.setattr("feishu_codex_workbench.filepreview.ssh_argv", lambda host, command: ["/bin/bash", "-c", command])
    name = "report ' ;$(touch PWNED).txt"
    (tmp_path / name).write_text("safe")
    host = Host("h", "H", "H", "local", str(tmp_path), (str(tmp_path),), "h", transport="local")
    result = asyncio.run(preview_file(host, name, str(tmp_path)))
    assert result["text"] == "safe"
    assert not (tmp_path / "PWNED").exists()
    with pytest.raises(ValueError, match="不存在"):
        asyncio.run(preview_file(host, "missing.txt", str(tmp_path)))
    for path in ("../outside.txt", "bad\npath", ""):
        with pytest.raises(ValueError):
            asyncio.run(preview_file(host, path, str(tmp_path)))
