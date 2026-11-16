import json
import subprocess
import sys

import pytest

from feishu_codex_workbench.cluster import REMOTE_FILES, ssh_argv
from feishu_codex_workbench.config import Host


def test_path_validation_and_shell_quoting():
    h = Host("h", "H", "H", "test-host", "/work/me", ("/work/me",), "h")
    for path in ("/work/other/file", "/work/me/../other", "relative", "/work/me\ncommand"):
        with pytest.raises(ValueError):
            h.validate_path(path)
    assert h.validate_path("/work/me/a;$(touch nope)")
    argv = ssh_argv(h, "python3 -c 'safe script'")
    assert argv[-2] == "test-host"
    import shlex
    assert shlex.split(argv[-1]) == ["bash", "-lc", "python3 -c 'safe script'"]


def run_helper(root, path, action="dir"):
    return subprocess.run([sys.executable, "-c", REMOTE_FILES], input=json.dumps({
        "roots": [str(root)], "path": str(path), "action": action}), capture_output=True, text=True)


def test_remote_symlink_escape_is_denied(tmp_path):
    root, outside = tmp_path / "owner", tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    result = run_helper(root, root / "escape")
    assert result.returncode != 0
    assert "outside allowed roots" in result.stderr
    assert json.loads(run_helper(root, root).stdout)["directories"] == []


def test_image_header_and_size_validation(tmp_path):
    image = tmp_path / "not-an-image.png"
    image.write_text("secret")
    assert run_helper(tmp_path, image, "image").returncode != 0
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    assert run_helper(tmp_path, image, "image").returncode == 0
    with image.open("wb") as f:
        f.truncate(10 * 1024 * 1024 + 1)
    assert run_helper(tmp_path, image, "image").returncode != 0
