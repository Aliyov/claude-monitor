"""Preferences dialog — edits the daemon config via GetConfig/SetConfig.

The dashboard never touches ~/.claude. The Integrations group is read-only.
"""

from __future__ import annotations

import copy

from gi.repository import Adw, GLib, GObject, Gtk

DEFAULTS = {
    "notifications": {"enabled": True, "on_finish": True, "on_error": True,
                      "on_attention": True, "min_busy_seconds": 20},
    "privacy": {"store_commands": True, "max_detail_chars": 200},
    "retention_days": 180,
    "sample_interval_ms": 2000,
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, win) -> None:
        super().__init__(title="Preferences", search_enabled=False)
        self.win = win
        self.config: dict | None = None
        self._save_id = 0
        self._loading = True

        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        self.add(page)

        # notifications
        g = Adw.PreferencesGroup(title="Notifications",
                                 description="Desktop notifications are sent by the background service, "
                                             "even when this window is closed.")
        self.n_enabled = Adw.SwitchRow(title="Enable notifications")
        self.n_finish = Adw.SwitchRow(title="Agent finished", subtitle="When a session finishes a turn")
        self.n_error = Adw.SwitchRow(title="Errors", subtitle="API errors and failing tools")
        self.n_attention = Adw.SwitchRow(title="Needs attention", subtitle="Waiting for permission or input")
        self.n_min = Adw.SpinRow.new_with_range(0, 3600, 5)
        self.n_min.set_title("Minimum work time")
        self.n_min.set_subtitle("Only notify “finished” for turns longer than this (seconds)")
        for r in (self.n_enabled, self.n_finish, self.n_error, self.n_attention, self.n_min):
            g.add(r)
        self.n_enabled.bind_property("active", self.n_finish, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        self.n_enabled.bind_property("active", self.n_error, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        self.n_enabled.bind_property("active", self.n_attention, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        self.n_enabled.bind_property("active", self.n_min, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        page.add(g)

        # privacy
        g = Adw.PreferencesGroup(title="Privacy",
                                 description="Claude Monitor stores activity metadata only — never your prompts "
                                             "or Claude's replies. Everything stays on this computer.")
        self.p_cmds = Adw.SwitchRow(title="Store shell commands",
                                    subtitle="Keep the text of Bash commands in the activity history")
        self.p_max = Adw.SpinRow.new_with_range(40, 2000, 20)
        self.p_max.set_title("Maximum detail length")
        self.p_max.set_subtitle("Characters kept for commands and paths")
        g.add(self.p_cmds)
        g.add(self.p_max)
        page.add(g)

        # data
        g = Adw.PreferencesGroup(title="Data &amp; Performance")
        self.d_ret = Adw.SpinRow.new_with_range(7, 3650, 1)
        self.d_ret.set_title("Keep history for")
        self.d_ret.set_subtitle("Days of activity kept in the local database")
        self.d_sample = Adw.SpinRow.new_with_range(1000, 30000, 500)
        self.d_sample.set_title("Resource sampling interval")
        self.d_sample.set_subtitle("Milliseconds between CPU/memory samples; higher uses less power")
        g.add(self.d_ret)
        g.add(self.d_sample)
        page.add(g)

        # integrations (read-only)
        g = Adw.PreferencesGroup(
            title="Integrations",
            description="Optional Claude Code integrations are installed with the claude-monitor command-line "
                        "tool. This window only shows their state and never changes your Claude configuration.")
        self.i_status = Adw.ActionRow(title="Status-line integration",
                                      subtitle="Provides 5-hour and weekly plan-limit percentages")
        self.i_badge = Gtk.Label(valign=Gtk.Align.CENTER)
        self.i_badge.add_css_class("cm-pill")
        self.i_status.add_suffix(self.i_badge)
        g.add(self.i_status)
        page.add(g)
        self._update_integrations()

        for r in (self.n_enabled, self.n_finish, self.n_error, self.n_attention, self.p_cmds):
            r.connect("notify::active", self._changed)
        for r in (self.n_min, self.p_max, self.d_ret, self.d_sample):
            r.connect("notify::value", self._changed)
        self.set_sensitive(False)
        win.client.get_config(self._on_config)
        self.connect("closed", self._on_closed)

    def _update_integrations(self) -> None:
        snap = self.win.snapshot or {}
        usage = snap.get("usage") or {}
        installed = bool(usage.get("statusline_installed"))
        self.i_badge.set_label("Installed" if installed else "Not installed")
        for c in ("st-idle", "st-unknown"):
            self.i_badge.remove_css_class(c)
        self.i_badge.add_css_class("st-idle" if installed else "st-unknown")

    def _on_config(self, cfg, err) -> None:
        if err is not None:
            self.add_toast(Adw.Toast(title="Could not load settings from the service"))
            return
        self.config = _merge(DEFAULTS, cfg or {})
        c = self.config
        n = c["notifications"]
        self.n_enabled.set_active(bool(n.get("enabled")))
        self.n_finish.set_active(bool(n.get("on_finish")))
        self.n_error.set_active(bool(n.get("on_error")))
        self.n_attention.set_active(bool(n.get("on_attention")))
        self.n_min.set_value(float(n.get("min_busy_seconds") or 0))
        self.p_cmds.set_active(bool(c["privacy"].get("store_commands")))
        self.p_max.set_value(float(c["privacy"].get("max_detail_chars") or 200))
        self.d_ret.set_value(float(c.get("retention_days") or 180))
        self.d_sample.set_value(float(c.get("sample_interval_ms") or 2000))
        self._loading = False
        self.set_sensitive(True)

    def _collect(self) -> dict:
        c = copy.deepcopy(self.config or DEFAULTS)
        c["notifications"].update(
            enabled=self.n_enabled.get_active(), on_finish=self.n_finish.get_active(),
            on_error=self.n_error.get_active(), on_attention=self.n_attention.get_active(),
            min_busy_seconds=int(self.n_min.get_value()))
        c["privacy"].update(store_commands=self.p_cmds.get_active(), max_detail_chars=int(self.p_max.get_value()))
        c["retention_days"] = int(self.d_ret.get_value())
        c["sample_interval_ms"] = int(self.d_sample.get_value())
        return c

    def _changed(self, *_a) -> None:
        if self._loading:
            return
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(500, self._save)

    def _save(self) -> bool:
        self._save_id = 0
        cfg = self._collect()
        self.config = cfg
        self.win.client.set_config(cfg, self._on_saved)
        return False

    def _on_saved(self, res, err) -> None:
        if err is not None or not (res or {}).get("ok"):
            self.add_toast(Adw.Toast(title="Could not save settings"))

    def _on_closed(self, *_a) -> None:
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save()
