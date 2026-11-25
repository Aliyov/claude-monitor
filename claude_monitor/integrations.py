"""Opt-in integration with Claude Code's settings.json (status-line tee).

Safety rules:
  * A timestamped backup of settings.json is made before any change.
  * Only the `statusLine` key is touched; every other key is preserved.
  * A pre-existing status-line command is kept and chained, so the user's
    status line keeps working, and is restored verbatim on uninstall.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

from claude_monitor.daemon import paths

TEE = "claude-monitor-statusline"
CHAIN = paths.CONFIG_DIR / "statusline-chain"
SAVED = paths.CONFIG_DIR / "statusline-original.json"
BACKUPS = paths.DATA_DIR / "backups"


def _load():
    try:
        with open(paths.CLAUDE_SETTINGS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write(settings):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    if paths.CLAUDE_SETTINGS.exists():
        shutil.copy2(paths.CLAUDE_SETTINGS, BACKUPS / f"settings.json.{int(time.time())}")
    tmp = paths.CLAUDE_SETTINGS.with_name(".settings.json.claude-monitor.tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    if paths.CLAUDE_SETTINGS.exists():
        os.chmod(tmp, paths.CLAUDE_SETTINGS.stat().st_mode & 0o777)
    os.replace(tmp, paths.CLAUDE_SETTINGS)


def install_statusline(tee_path):
    s = _load()
    cur = s.get("statusLine")
    if cur and TEE in (cur.get("command") or ""):
        print("status-line tee already installed")
        return
    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SAVED.write_text(json.dumps({"statusLine": cur}))
    if cur and cur.get("command"):
        CHAIN.write_text(cur["command"])
    elif CHAIN.exists():
        CHAIN.unlink()
    new = dict(cur or {})
    new["type"] = "command"
    new["command"] = str(tee_path)
    s["statusLine"] = new
    _write(s)
    print("status-line tee installed" + (" (chained to your previous command)" if cur else ""))


def uninstall_statusline():
    s = _load()
    cur = s.get("statusLine")
    if not cur or TEE not in (cur.get("command") or ""):
        print("status-line tee not installed; nothing to do")
        return
    orig = None
    if SAVED.exists():
        orig = json.loads(SAVED.read_text()).get("statusLine")
    if orig:
        s["statusLine"] = orig
    else:
        s.pop("statusLine", None)
    _write(s)
    for p in (SAVED, CHAIN):
        if p.exists():
            p.unlink()
    print("status-line tee removed" + (" (previous status line restored)" if orig else ""))


def main(argv):
    if len(argv) >= 1 and argv[0] == "install-statusline":
        install_statusline(Path(argv[1]) if len(argv) > 1 else Path.home() / ".local/bin" / TEE)
    elif argv and argv[0] == "uninstall-statusline":
        uninstall_statusline()
    else:
        print("usage: integrations.py install-statusline [path] | uninstall-statusline")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
