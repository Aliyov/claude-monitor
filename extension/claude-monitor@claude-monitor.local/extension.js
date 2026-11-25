// Claude Monitor — GNOME Shell extension entry point.
//
// Thin top-bar UI over the claude-monitord D-Bus service. Everything is
// created in enable() and torn down in disable(); nothing lives at module scope.

import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {MonitorClient} from './client.js';
import {Pulser} from './views.js';
import {Indicator} from './indicator.js';

const DASHBOARD_BIN = 'claude-monitor-dashboard';
const DASHBOARD_DESKTOP_ID = 'io.github.ClaudeMonitor.Dashboard.desktop';

export default class ClaudeMonitorExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._icon = Gio.FileIcon.new(
            Gio.File.new_for_path(`${this.path}/icons/claude-monitor-symbolic.svg`));
        this._pulser = new Pulser();
        this._pulser.setEnabled(!this._settings.get_boolean('reduce-animations'));
        this._tickId = 0;

        this._indicator = new Indicator({
            settings: this._settings,
            pulser: this._pulser,
            icon: this._icon,
            onOpenDashboard: () => this._openDashboard(),
            onOpenPrefs: () => this.openPreferences(),
        });
        this._indicator.connect('menu-open-changed', () => this._syncTicker());
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        this._client = new MonitorClient();
        this._client.connect('snapshot', (_c, snap) => {
            this._indicator?.setSnapshot(snap);
            this._syncTicker();
        });
        this._client.connect('online-changed', (_c, online) => {
            this._indicator?.setOnline(online);
            this._syncTicker();
        });

        this._settings.connectObject(
            'changed::reduce-animations', () => {
                this._pulser.setEnabled(!this._settings.get_boolean('reduce-animations'));
            },
            this);

        this._client.start();
    }

    disable() {
        this._settings?.disconnectObject(this);
        this._stopTicker();

        this._client?.stop();
        this._client = null;

        this._indicator?.destroy();
        this._indicator = null;

        this._pulser?.destroy();
        this._pulser = null;
        this._icon = null;
        this._settings = null;
    }

    // --- Countdown ticker -------------------------------------------------
    // Runs only while the menu (and so a countdown) is open. Ticks every
    // second when a reset is < 1 h away (seconds are shown), otherwise 15 s.

    _syncTicker() {
        const active = !!this._indicator?.menuOpen;
        this._pulser?.setActive(active);
        this._stopTicker();
        if (active)
            this._tick();
    }

    _tick() {
        this._tickId = 0;
        const now = Date.now();
        if (!this._indicator?.menuOpen || !this._indicator.tick(now))
            return;
        const nearest = this._indicator.nearestResetSeconds(now);
        const soon = Number.isFinite(nearest) && nearest < 3600;
        this._tickId = GLib.timeout_add(
            GLib.PRIORITY_LOW, soon ? 1000 : 15000, () => {
                this._tick();
                return GLib.SOURCE_REMOVE;
            });
    }

    _stopTicker() {
        if (this._tickId) {
            GLib.source_remove(this._tickId);
            this._tickId = 0;
        }
    }

    // --- Launching the dashboard -----------------------------------------

    _openDashboard() {
        const candidates = [
            GLib.find_program_in_path(DASHBOARD_BIN),
            GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', DASHBOARD_BIN]),
        ].filter(p => p && GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE));

        for (const path of candidates) {
            try {
                const proc = Gio.Subprocess.new([path], Gio.SubprocessFlags.NONE);
                proc.wait_async(null, null); // reap the child, avoid zombies
                return;
            } catch (e) {
                console.warn(`[claude-monitor] failed to launch ${path}: ${e.message}`);
            }
        }

        const app = GioUnix.DesktopAppInfo.new(DASHBOARD_DESKTOP_ID);
        if (app) {
            try {
                app.launch([], global.create_app_launch_context(0, -1));
                return;
            } catch (e) {
                console.warn(`[claude-monitor] failed to launch ${DASHBOARD_DESKTOP_ID}: ${e.message}`);
            }
        }
        Main.notify('Claude Monitor', 'Dashboard is not installed.');
    }
}
