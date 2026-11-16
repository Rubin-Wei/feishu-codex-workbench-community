"""Install an opt-in macOS login service after foreground Feishu validation."""
import os
import pathlib
import plistlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
if not (root / ".env").exists():
    raise SystemExit("Create and verify .env with a foreground run first.")
logs = root / ".local" / "logs"
logs.mkdir(parents=True, exist_ok=True, mode=0o700)
target = pathlib.Path.home() / "Library/LaunchAgents/org.codex-workbench.feishu.plist"
target.parent.mkdir(parents=True, exist_ok=True)
data = {"Label": "org.codex-workbench.feishu", "ProgramArguments": ["/bin/bash", str(root / "scripts/run.sh")],
        "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
        "StandardOutPath": str(logs / "service.out.log"), "StandardErrorPath": str(logs / "service.err.log"),
        "Umask": 0o077}
with target.open("wb") as file:
    plistlib.dump(data, file)
os.chmod(target, 0o600)
subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)], check=True)
print(target)
