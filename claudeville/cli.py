"""`claudeville` command-line client (talks to the daemon over D-Bus)."""
import argparse
import json
import sys
import time

from gi.repository import Gio, GLib

BUS, PATH, IFACE = "io.github.aliyov.Claudeville", "/io/github/aliyov/Claudeville", "io.github.aliyov.Claudeville1"


def call(method, sig=None, args=()):
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    params = GLib.Variant(sig, tuple(args)) if sig else None
    r = conn.call_sync(BUS, PATH, IFACE, method, params, GLib.VariantType("(s)"),
                       Gio.DBusCallFlags.NONE, 5000, None)
    return json.loads(r.unpack()[0])


def _ago(ms):
    if not ms:
        return "—"
    s = int(time.time() - ms / 1000)
    return f"{s}s ago" if s < 60 else f"{s // 60}m ago" if s < 3600 else f"{s // 3600}h ago"


def _mb(b):
    return "—" if b is None else f"{b / 1048576:.0f} MB"


def _tok(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def _until(sec):
    if not sec:
        return ""
    d = int(sec - time.time())
    return f" (resets in {d // 3600}h {d % 3600 // 60}m)" if d > 0 else ""


def cmd_status(_a):
    s = call("GetSnapshot")
    u = s["usage"]
    print("Usage limits:", "unavailable (status-line integration not installed)"
          if u["source"] == "none" else f"as of {_ago(u['as_of'])}")
    for k, label in (("five_hour", "5-hour"), ("seven_day", "weekly")):
        w = u.get(k)
        if w:
            print(f"  {label:7} {w['used_percentage']:5.1f}%{_until(w['resets_at'])}")
    t = u["tokens_today"]
    print(f"Tokens today: out {_tok(t['output'])}, in {_tok(t['input'])}, cache read {_tok(t['cache_read'])}")
    tt = s["totals"]
    print(f"\nLive sessions: {tt['live']}  busy {tt['busy']}  waiting {tt['waiting']}  "
          f"agents {tt['agents_running']}  CPU {tt['cpu_percent']}%  RAM {_mb(tt['rss_bytes'])}")
    for x in s["sessions"]:
        cur = x["current"]
        print(f"  [{x['status']:7}] {x['project']:<20} pid {x['pid']:<7} CPU {x['cpu_percent'] or 0:5.1f}% "
              f"RAM {_mb(x['rss_bytes']):>7}  {x['tool_calls']} tools")
        if cur:
            print(f"            ↳ {cur['tool']}: {cur['summary']}")
        for a in x["agents"]:
            if a["status"] == "running":
                print(f"            ⤷ agent {a['type']}: {a['description']}")
    idx = s["daemon"]["indexing"]
    if idx["active"]:
        print(f"\nIndexing history: {idx['files_done']}/{idx['files_total']} files")


def cmd_timeline(a):
    for e in reversed(call("GetTimeline", "(xu)", (0, a.n))["events"]):
        t = time.strftime("%H:%M:%S", time.localtime(e["ts"] / 1000))
        print(f"{t} {e['project'] or '':<18} {e['kind']:<14} {e['tool'] or '':<10} {e['summary']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="claudeville")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="usage, live sessions and agents")
    t = sub.add_parser("timeline", help="recent activity")
    t.add_argument("-n", type=int, default=30)
    a = ap.parse_args(argv)
    try:
        {"timeline": cmd_timeline}.get(a.cmd, cmd_status)(a)
    except GLib.Error as e:
        print("Claudeville service is not running:", e.message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
