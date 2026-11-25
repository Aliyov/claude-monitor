"""Filesystem locations. The daemon only ever *reads* CLAUDE_DIR."""
import os
import re
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", HOME / ".claude"))
SESSIONS_DIR = CLAUDE_DIR / "sessions"
PROJECTS_DIR = CLAUDE_DIR / "projects"
CLAUDE_SETTINGS = CLAUDE_DIR / "settings.json"

_xdg_data = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
_xdg_state = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state"))
_xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))

DATA_DIR = Path(os.environ.get("CLAUDE_MONITOR_DATA_DIR", _xdg_data / "claude-monitor"))
STATE_DIR = Path(os.environ.get("CLAUDE_MONITOR_STATE_DIR", _xdg_state / "claude-monitor"))
CONFIG_DIR = _xdg_config / "claude-monitor"

DB_PATH = DATA_DIR / "monitor.db"
CONFIG_PATH = CONFIG_DIR / "config.json"
STATUSLINE_DIR = STATE_DIR / "statusline"
HOOKS_DIR = STATE_DIR / "hooks"


def project_dir_for_cwd(cwd: str) -> Path:
    """Claude Code encodes a project's cwd by replacing non-alphanumerics with '-'."""
    return PROJECTS_DIR / re.sub(r"[^A-Za-z0-9]", "-", cwd)


def ensure_dirs() -> None:
    for d in (DATA_DIR, STATUSLINE_DIR, HOOKS_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
