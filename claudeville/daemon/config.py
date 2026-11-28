"""User configuration (JSON), merged over defaults."""
import copy
import json
import logging
import os

from . import paths

log = logging.getLogger(__name__)

DEFAULTS = {
    "notifications": {
        "enabled": True,
        "on_finish": True,
        "on_error": True,
        "on_attention": True,
        "min_busy_seconds": 20,
    },
    "privacy": {"store_commands": True, "max_detail_chars": 200},
    "retention_days": 180,
    "sample_interval_ms": 2000,
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            continue  # ignore unknown keys
        if isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v)
        elif isinstance(v, type(base[k])) or (isinstance(base[k], (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool)):
            out[k] = v
    return out


class Config:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULTS)
        self._mtime = None
        self.reload()

    def reload(self) -> bool:
        """Re-read the file if it changed. Returns True when values changed."""
        try:
            st = os.stat(paths.CONFIG_PATH)
        except FileNotFoundError:
            changed = self._mtime is not None
            self._mtime = None
            if changed:
                self.data = copy.deepcopy(DEFAULTS)
            return changed
        if st.st_mtime == self._mtime:
            return False
        self._mtime = st.st_mtime
        try:
            with open(paths.CONFIG_PATH) as f:
                new = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError) as e:
            log.warning("config unreadable, keeping previous: %s", e)
            return False
        changed = new != self.data
        self.data = new
        return changed

    def update(self, values: dict) -> None:
        self.data = _merge(self.data, values)
        paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = paths.CONFIG_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, paths.CONFIG_PATH)
        self._mtime = os.stat(paths.CONFIG_PATH).st_mtime

    def __getitem__(self, k):
        return self.data[k]
