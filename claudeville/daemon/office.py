"""Department slots for the office View.

Rules (agreed with the user):
- Slot 0 always exists; dark when no session uses it; never removed.
- Each live session (even two in one project) occupies its own slot.
- A new session takes a free (dark) slot, preferring one that last hosted the
  same project, else the lowest free slot; if none is free a slot is added.
- When a session ends its slot goes dark but remembers what it last hosted.
- Dark slots other than slot 0 are removed after EXPIRE_MS without use.
"""
import json

EXPIRE_MS = 48 * 3600 * 1000
KV_KEY = "office_slots"


class Office:
    def __init__(self, store):
        self.store = store
        try:
            self.slots = json.loads(store.kv_get(KV_KEY, "[]"))
            if not isinstance(self.slots, list):
                self.slots = []
        except ValueError:
            self.slots = []
        if not self.slots:
            self.slots = [_empty()]

    def update(self, live, now):
        """live: list of dicts with session_id, cwd, project, model, effort,
        started_at. Returns True if slot assignment changed."""
        before = json.dumps(self.slots, sort_keys=True)
        by_sid = {s["session_id"]: s for s in live}
        for sl in self.slots:
            sid = sl.get("session_id")
            if sid and sid not in by_sid:
                sl["session_id"] = None
                sl["last_used_at"] = now
            elif sid:
                s = by_sid[sid]
                sl["model"] = s.get("model") or sl.get("model")
                sl["effort"] = s.get("effort") or sl.get("effort")
        taken = {sl.get("session_id") for sl in self.slots if sl.get("session_id")}
        for s in sorted(live, key=lambda s: (s.get("started_at") or 0, s["session_id"])):
            if s["session_id"] in taken:
                continue
            free = [sl for sl in self.slots if not sl.get("session_id")]
            same = [sl for sl in free if sl.get("cwd") == s.get("cwd")] or \
                   [sl for sl in free if sl.get("project") == s.get("project")]
            sl = (same or free or [None])[0]
            if sl is None:
                sl = _empty()
                self.slots.append(sl)
            sl.update(session_id=s["session_id"], cwd=s.get("cwd"), project=s.get("project"),
                      model=s.get("model"), effort=s.get("effort"), last_used_at=now)
            taken.add(s["session_id"])
        self.slots = [sl for i, sl in enumerate(self.slots)
                      if i == 0 or sl.get("session_id")
                      or now - (sl.get("last_used_at") or 0) < EXPIRE_MS]
        after = json.dumps(self.slots, sort_keys=True)
        if after != before:
            # last_used_at of lit slots is refreshed only on assignment, so this
            # writes only when the layout really changed
            self.store.kv_set(KV_KEY, after)
            return True
        return False

    def departments(self, rosters):
        out = []
        for i, sl in enumerate(self.slots):
            cwd = sl.get("cwd")
            roster = rosters.roster(cwd, sl.get("model"), sl.get("effort")) if cwd else \
                {"source": "default", "root": None, "agents": [], "private_room": None}
            out.append({"slot": i, "lit": bool(sl.get("session_id")),
                        "session_id": sl.get("session_id"), "project": sl.get("project"),
                        "cwd": cwd, "last_used_at": sl.get("last_used_at"), "roster": roster})
        return out


def _empty():
    return {"session_id": None, "cwd": None, "project": None, "model": None, "effort": None,
            "last_used_at": None}
