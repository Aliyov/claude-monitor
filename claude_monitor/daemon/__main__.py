"""claude-monitord entry point: `python3 -m claude_monitor.daemon`."""
import argparse
import logging
import signal
import sys

from gi.repository import Gio, GLib

from . import paths
from .config import Config
from .dbus_service import BUS_NAME, DBusService
from .engine import Engine
from .ingest import Ingestor
from .notifier import Notifier
from .store import Store

log = logging.getLogger("claude-monitord")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="claude-monitord")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    paths.ensure_dirs()
    loop = GLib.MainLoop()
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    state = {}

    def on_acquired(_conn, _name):
        config = Config()
        store = Store(paths.DB_PATH)
        ing = Ingestor(store, config, lambda evs: None)
        engine = Engine(store, config, ing, Notifier(conn))
        state.update(store=store, engine=engine, svc=DBusService(conn, engine, config))
        engine.start()
        log.info("running (db=%s)", paths.DB_PATH)

    def on_lost(_conn, _name):
        if not state:
            log.error("another claude-monitord already owns %s; exiting", BUS_NAME)
        loop.quit()

    Gio.bus_own_name_on_connection(conn, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
                                   on_acquired, on_lost)

    def stop():
        loop.quit()
        return GLib.SOURCE_REMOVE

    try:
        from gi.repository import GLibUnix
        add_signal = GLibUnix.signal_add
    except ImportError:
        add_signal = GLib.unix_signal_add
    add_signal(GLib.PRIORITY_HIGH, signal.SIGTERM, stop)
    add_signal(GLib.PRIORITY_HIGH, signal.SIGINT, stop)
    try:
        loop.run()
    finally:
        if "store" in state:
            state["store"].close()
    return 0 if state else 1


if __name__ == "__main__":
    sys.exit(main())
