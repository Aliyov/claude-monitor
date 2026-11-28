"""Desktop notifications via org.freedesktop.Notifications (async, never blocks)."""
import logging
import shutil
import subprocess

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)
APP_ICON = "io.github.aliyov.Claudeville"


class Notifier:
    def __init__(self, conn):
        self.conn = conn
        self._ids = {}  # key -> notification id (replace instead of stacking)
        self._open_for = {}
        conn.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                              "ActionInvoked", "/org/freedesktop/Notifications", None,
                              Gio.DBusSignalFlags.NONE, self._on_action)

    def send(self, key, summary, body, urgency=1):
        hints = {"urgency": GLib.Variant("y", urgency),
                 "desktop-entry": GLib.Variant("s", "io.github.aliyov.Claudeville.Dashboard")}
        params = GLib.Variant("(susssasa{sv}i)", (
            "Claudeville", self._ids.get(key, 0), APP_ICON, summary, body,
            ["default", "Open Dashboard"], hints, -1))

        def done(conn, res):
            try:
                nid = conn.call_finish(res).unpack()[0]
                self._ids[key] = nid
                self._open_for[nid] = key
            except GLib.Error as e:
                log.warning("notification failed: %s", e.message)

        self.conn.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                       "org.freedesktop.Notifications", "Notify", params, GLib.VariantType("(u)"),
                       Gio.DBusCallFlags.NONE, 3000, None, done)

    def _on_action(self, conn, sender, path, iface, signal, params):
        nid, action = params.unpack()
        if nid in self._open_for and action == "default":
            launch_dashboard()


def launch_dashboard():
    exe = shutil.which("claudeville-dashboard")
    if exe:
        subprocess.Popen([exe], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    app = Gio.DesktopAppInfo.new("io.github.aliyov.Claudeville.Dashboard.desktop")
    if app:
        app.launch([], None)
