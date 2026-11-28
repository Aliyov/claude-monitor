"""Agent rosters for the office View: who works in a project.

A project's team is what Claude Code itself can launch: the subagent
definitions in `<project>/.claude/agents/*.md` plus the user's personal ones in
`~/.claude/agents/*.md` (a project agent wins over a user agent of the same
name, as in Claude Code). Only the YAML frontmatter is read (name,
description, model, effort). CLAUDE.md prose is deliberately not parsed: it is
free text and Claude Code cannot launch agents that have no definition file.

Pure file reading; never writes anything and costs no tokens.
"""
import hashlib
import os
import re
import time

from . import paths

FAMILY_RANK = {"fable": 4, "opus": 3, "sonnet": 2, "haiku": 1}
EFFORT_RANK = {"max": 5, "xhigh": 4, "high": 3, "medium": 2, "low": 1}
_MODEL_RE = re.compile(r"(fable|opus|sonnet|haiku)(?:[-_ ]?(\d+)(?:[-_.](\d+))?)?", re.I)
RECHECK_S = 3.0


def parse_frontmatter(text):
    """Minimal YAML frontmatter reader: flat `key: value` pairs, quoted
    strings, and `|` / `>` block scalars. Unknown syntax is skipped."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out, i = {}, 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        i += 1
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                if lines[i].strip() == "---":
                    break
                block.append(lines[i].strip())
                i += 1
            val = ("\n" if val.startswith("|") else " ").join(b for b in block if b)
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def model_family(model):
    m = _MODEL_RE.search(model or "")
    return m.group(1).lower() if m else None


def model_version(model):
    """(major, minor) from a full model id; None for aliases like 'opus'."""
    m = _MODEL_RE.search(model or "")
    if not m or m.group(2) is None:
        return None
    return (int(m.group(2)), int(m.group(3) or 0))


def rank_key(model, effort):
    """Higher sorts first. Family, then version (an alias = newest), then effort."""
    fam = FAMILY_RANK.get(model_family(model), 0)
    ver = model_version(model)
    ver_key = (999, 999) if ver is None and fam else (ver or (0, 0))
    return (fam, ver_key, EFFORT_RANK.get((effort or "").lower(), 0))


def find_project_root(cwd):
    """Nearest ancestor of cwd (inclusive) with `.claude/agents`; stops at the
    git root or at $HOME (whose .claude is the user level, not a project)."""
    if not cwd:
        return None
    home = str(paths.HOME)
    d = os.path.abspath(cwd)
    while True:
        if d == home or d == os.path.dirname(d):
            return None
        if os.path.isdir(os.path.join(d, ".claude", "agents")):
            return d
        if os.path.exists(os.path.join(d, ".git")):
            return None
        d = os.path.dirname(d)


class _DirCache:
    __slots__ = ("checked", "sig", "agents")

    def __init__(self):
        self.checked, self.sig, self.agents = 0.0, None, []


class Rosters:
    def __init__(self):
        self._dirs = {}    # agents dir -> _DirCache
        self._roots = {}   # cwd -> (checked, root)

    def _root(self, cwd, now):
        hit = self._roots.get(cwd)
        if hit and now - hit[0] < RECHECK_S * 10:
            return hit[1]
        root = find_project_root(cwd)
        self._roots[cwd] = (now, root)
        return root

    def _read_dir(self, d, scope, now):
        c = self._dirs.setdefault(d, _DirCache())
        if now - c.checked < RECHECK_S and c.sig is not None:
            return c.agents
        c.checked = now
        try:
            files = sorted((e.name, e.stat().st_mtime_ns) for e in os.scandir(d)
                           if e.name.endswith(".md") and e.is_file())
        except OSError:
            files = []
        sig = tuple(files)
        if sig == c.sig:
            return c.agents
        c.sig = sig
        agents = []
        for name, _ in files:
            try:
                with open(os.path.join(d, name), encoding="utf-8", errors="replace") as f:
                    fm = parse_frontmatter(f.read(16384))
            except OSError:
                continue
            agent_name = (fm.get("name") or name[:-3]).strip()
            if not agent_name:
                continue
            agents.append({
                "name": agent_name,
                "description": (fm.get("description") or "").strip()[:300] or None,
                "model": (fm.get("model") or "").strip() or None,   # alias, full id, 'inherit' or None
                "effort": (fm.get("effort") or "").strip().lower() or None,
                "scope": scope,
            })
        c.agents = agents
        return agents

    def changed(self, cwds):
        """True if any watched agents dir changed (cheap: listdir + stat)."""
        now = time.monotonic()
        before = {d: c.sig for d, c in self._dirs.items()}
        for cwd in cwds:
            self.roster(cwd, None, None, now=now)
        return any(before.get(d) != c.sig for d, c in self._dirs.items() if d in before)

    def roster(self, cwd, session_model, session_effort, now=None):
        """Team for a project. Model 'inherit'/missing resolves to the session's
        model, missing effort to the session's effort, for ranking only; the
        reported fields keep what the file says."""
        now = time.monotonic() if now is None else now
        root = self._root(cwd, now)
        merged = {a["name"]: a for a in self._read_dir(str(paths.CLAUDE_DIR / "agents"), "user", now)}
        if root:
            merged.update({a["name"]: a for a in self._read_dir(os.path.join(root, ".claude", "agents"),
                                                                 "project", now)})
        agents = []
        for a in merged.values():
            eff_model = a["model"] if a["model"] and a["model"] != "inherit" else session_model
            eff_effort = a["effort"] or session_effort
            agents.append(dict(a, _key=rank_key(eff_model, eff_effort),
                               _tie=hashlib.sha1(f"{root or cwd}\0{a['name']}".encode()).hexdigest()))
        agents.sort(key=lambda a: (tuple(-x for x in _flat(a["_key"])), a["_tie"]))
        private = agents[0]["name"] if agents else None
        out = []
        for i, a in enumerate(agents):
            a = {k: v for k, v in a.items() if not k.startswith("_")}
            a["rank"] = i
            a["room"] = "private" if a["name"] == private else "desk"
            out.append(a)
        return {"source": "agents" if out else "default", "root": root, "agents": out,
                "private_room": private}


def _flat(key):
    fam, (vmaj, vmin), eff = key
    return (fam, vmaj, vmin, eff)
