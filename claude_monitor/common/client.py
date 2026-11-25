"""Asynchronous D-Bus client for the Claude Monitor daemon.

The daemon speaks JSON-over-D-Bus (see docs/CONTRACT.md). This client:

* watches the bus name and reports availability changes,
* exposes async method calls that decode JSON and invoke a callback on the
  GLib main loop (never blocking the UI),
* fans out the ``SnapshotChanged`` / ``EventsAdded`` signals to subscribers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

BUS_NAME = "io.github.ClaudeMonitor"
OBJECT_PATH = "/io/github/ClaudeMonitor"
INTERFACE = "io.github.ClaudeMonitor1"

Callback = Callable[[Any, Exception | None], None]

# Method signatures: name -> GVariant type string of the arguments.
_SIGNATURES = {
    "GetSnapshot": "()",
    "GetSessionEvents": "(sxu)",
    "GetTimeline": "(xu)",
    "GetHistory": "(suu)",
    "GetSession": "(s)",
    "GetStats": "(u)",
    "GetConfig": "()",
    "SetConfig": "(s)",
}


class MonitorClient:
    """Single shared connection to the daemon."""

    def __init__(self) -> None:
        self._proxy: Gio.DBusProxy | None = None
        self._watch_id = 0
        self._available_cbs: list[Callable[[bool], None]] = []
        self._snapshot_cbs: list[Callable[[int], None]] = []
        self._events_cbs: list[Callable[[list[dict]], None]] = []
        self._cancellable = Gio.Cancellable()
        self.available = False

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        if self._watch_id:
            return
        self._watch_id = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_name_appeared,
            self._on_name_vanished,
        )

    def stop(self) -> None:
        self._cancellable.cancel()
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        self._proxy = None

    def on_available(self, cb: Callable[[bool], None]) -> None:
        self._available_cbs.append(cb)

    def on_snapshot_changed(self, cb: Callable[[int], None]) -> None:
        self._snapshot_cbs.append(cb)

    def on_events_added(self, cb: Callable[[list[dict]], None]) -> None:
        self._events_cbs.append(cb)

    def _set_available(self, value: bool) -> None:
        if value == self.available:
            return
        self.available = value
        for cb in list(self._available_cbs):
            try:
                cb(value)
            except Exception:  # pragma: no cover - UI callback bug
                log.exception("availability callback failed")

    def _on_name_appeared(self, conn: Gio.DBusConnection, name: str, owner: str) -> None:
        Gio.DBusProxy.new(
            conn,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            self._cancellable,
            self._on_proxy_ready,
        )

    def _on_proxy_ready(self, _src, res) -> None:
        try:
            proxy = Gio.DBusProxy.new_finish(res)
        except GLib.Error as e:
            log.warning("could not create proxy: %s", e.message)
            return
        self._proxy = proxy
        proxy.connect("g-signal", self._on_signal)
        self._set_available(True)

    def _on_name_vanished(self, _conn, _name) -> None:
        self._proxy = None
        self._set_available(False)

    def _on_signal(self, _proxy, _sender, signal: str, params: GLib.Variant) -> None:
        try:
            if signal == "SnapshotChanged":
                rev = params.unpack()[0]
                for cb in list(self._snapshot_cbs):
                    cb(rev)
            elif signal == "EventsAdded":
                payload = json.loads(params.unpack()[0])
                events = payload.get("events", []) if isinstance(payload, dict) else []
                for cb in list(self._events_cbs):
                    cb(events)
        except Exception:
            log.exception("signal handler failed for %s", signal)

    # ---------------------------------------------------------------- methods
    def call(self, method: str, args: tuple, callback: Callback, timeout_ms: int = 10000) -> None:
        """Call ``method`` with ``args``; ``callback(data, error)`` runs on the main loop."""
        proxy = self._proxy
        if proxy is None:
            GLib.idle_add(lambda: (callback(None, ConnectionError("Monitor service not running")), False)[1])
            return
        sig = _SIGNATURES.get(method, "()")
        variant = GLib.Variant(sig, args) if args else None

        def done(p, res):
            try:
                out = p.call_finish(res)
                raw = out.unpack()[0]
                data = json.loads(raw) if raw else None
            except GLib.Error as e:
                if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    return
                callback(None, RuntimeError(e.message))
                return
            except (ValueError, TypeError) as e:
                callback(None, e)
                return
            callback(data, None)

        proxy.call(method, variant, Gio.DBusCallFlags.NONE, timeout_ms, self._cancellable, done)

    # Convenience wrappers ---------------------------------------------------
    def get_snapshot(self, cb: Callback) -> None:
        self.call("GetSnapshot", (), cb)

    def get_session_events(self, session_id: str, before_id: int, limit: int, cb: Callback) -> None:
        self.call("GetSessionEvents", (session_id, int(before_id), int(limit)), cb)

    def get_timeline(self, before_id: int, limit: int, cb: Callback) -> None:
        self.call("GetTimeline", (int(before_id), int(limit)), cb)

    def get_history(self, query: str, offset: int, limit: int, cb: Callback) -> None:
        self.call("GetHistory", (query or "", int(offset), int(limit)), cb)

    def get_session(self, session_id: str, cb: Callback) -> None:
        self.call("GetSession", (session_id,), cb)

    def get_stats(self, days: int, cb: Callback) -> None:
        self.call("GetStats", (int(days),), cb, timeout_ms=30000)

    def get_config(self, cb: Callback) -> None:
        self.call("GetConfig", (), cb)

    def set_config(self, config: dict, cb: Callback) -> None:
        self.call("SetConfig", (json.dumps(config),), cb)
