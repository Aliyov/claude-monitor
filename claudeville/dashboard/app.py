"""Dashboard application entry point."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..common.client import MonitorClient  # noqa: E402

APP_ID = "io.github.aliyov.Claudeville.Dashboard"
HERE = Path(__file__).resolve().parent


def _data_icon_dir() -> Path | None:
    """Locate the app icon: installed hicolor theme or the source tree."""
    src = HERE.parent.parent / "data" / "icons"
    return src if src.is_dir() else None


class DashboardApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.client = MonitorClient()
        self.window = None
        GLib.set_application_name("Claudeville")
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)
        quit_ = Gio.SimpleAction.new("quit", None)
        quit_.connect("activate", lambda *_: self.quit())
        self.add_action(quit_)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display)
        theme.add_search_path(str(HERE / "icons"))
        icon_dir = _data_icon_dir()
        if icon_dir:
            theme.add_search_path(str(icon_dir))
        provider = Gtk.CssProvider()
        provider.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name("io.github.aliyov.Claudeville")
        self.client.start()

    def do_activate(self) -> None:
        if self.window is None:
            from .window import MainWindow
            self.window = MainWindow(self, self.client)
        self.window.present()

    def do_shutdown(self) -> None:
        self.client.stop()
        Adw.Application.do_shutdown(self)

    def _on_about(self, *_a) -> None:
        dlg = Adw.AboutDialog(
            application_name="Claudeville",
            application_icon="io.github.aliyov.Claudeville",
            version=__version__,
            developer_name="Claudeville contributors",
            comments="Local, private monitoring for Claude Code sessions.\n"
                     "Reads only local files — no tokens, no API calls.",
            license_type=Gtk.License.MIT_X11,
        )
        dlg.present(self.window)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("CLAUDEVILLE_LOG", "WARNING"),
                        format="%(levelname)s %(name)s: %(message)s")
    app = DashboardApp()
    return app.run(argv if argv is not None else sys.argv)
