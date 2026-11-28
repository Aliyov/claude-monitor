"""D-Bus interface io.github.aliyov.Claudeville1 (see docs/CONTRACT.md)."""
import json
import logging

from gi.repository import Gio, GLib

from . import queries

log = logging.getLogger(__name__)

BUS_NAME = "io.github.aliyov.Claudeville"
OBJ_PATH = "/io/github/aliyov/Claudeville"
IFACE = "io.github.aliyov.Claudeville1"

XML = f"""
<node>
  <interface name="{IFACE}">
    <method name="GetSnapshot"><arg type="s" direction="out"/></method>
    <method name="GetSessionEvents">
      <arg type="s" name="session_id" direction="in"/><arg type="x" name="before_id" direction="in"/>
      <arg type="u" name="limit" direction="in"/><arg type="s" direction="out"/>
    </method>
    <method name="GetTimeline">
      <arg type="x" name="before_id" direction="in"/><arg type="u" name="limit" direction="in"/>
      <arg type="s" direction="out"/>
    </method>
    <method name="GetHistory">
      <arg type="s" name="query" direction="in"/><arg type="u" name="offset" direction="in"/>
      <arg type="u" name="limit" direction="in"/><arg type="s" direction="out"/>
    </method>
    <method name="GetSession"><arg type="s" name="session_id" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetStats"><arg type="u" name="days" direction="in"/><arg type="s" direction="out"/></method>
    <method name="GetConfig"><arg type="s" direction="out"/></method>
    <method name="SetConfig"><arg type="s" name="json" direction="in"/><arg type="s" direction="out"/></method>
    <signal name="SnapshotChanged"><arg type="x" name="revision"/></signal>
    <signal name="EventsAdded"><arg type="s" name="json"/></signal>
  </interface>
</node>
"""


class DBusService:
    def __init__(self, conn, engine, config):
        self.conn, self.engine, self.config = conn, engine, config
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.reg_id = conn.register_object(OBJ_PATH, info, self._call, None, None)
        engine.on_snapshot_changed = self._snapshot_changed
        engine.on_events = self._events_added

    def _snapshot_changed(self, rev):
        self.conn.emit_signal(None, OBJ_PATH, IFACE, "SnapshotChanged", GLib.Variant("(x)", (rev,)))

    def _events_added(self, evs):
        self.conn.emit_signal(None, OBJ_PATH, IFACE, "EventsAdded",
                              GLib.Variant("(s)", (json.dumps({"events": evs}, separators=(",", ":")),)))

    def _call(self, conn, sender, path, iface, method, params, inv):
        try:
            args = params.unpack()
            e = self.engine
            st = e.store
            if method == "GetSnapshot":
                out = e.snapshot()
            elif method == "GetSessionEvents":
                out = json.dumps(queries.events(st, args[0], args[1], args[2], e.projects()))
            elif method == "GetTimeline":
                out = json.dumps(queries.events(st, None, args[0], args[1], e.projects()))
            elif method == "GetHistory":
                out = json.dumps(queries.history(st, args[0], args[1], args[2], e.live_ids()))
            elif method == "GetSession":
                out = json.dumps(queries.session_detail(st, args[0], e.live_ids()))
            elif method == "GetStats":
                out = json.dumps(queries.stats(st, args[0]))
            elif method == "GetConfig":
                out = json.dumps(self.config.data)
            elif method == "SetConfig":
                self.config.update(json.loads(args[0]))
                out = json.dumps({"ok": True})
            else:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
                return
            inv.return_value(GLib.Variant("(s)", (out,)))
        except Exception as ex:
            log.exception("D-Bus %s failed", method)
            inv.return_dbus_error("io.github.aliyov.Claudeville.Error", str(ex))
