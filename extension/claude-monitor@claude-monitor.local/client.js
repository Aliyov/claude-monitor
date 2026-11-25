// Async D-Bus client for the Claude Monitor daemon.
//
// - Watches the bus name, so the daemon can start/stop/restart freely.
// - No polling: a snapshot is fetched once on connect and then only when the
//   daemon emits SnapshotChanged (already coalesced to <= 1 Hz daemon-side).
// - Never blocks the shell: every call is asynchronous and cancellable.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';

export const BUS_NAME = 'io.github.ClaudeMonitor';
export const OBJECT_PATH = '/io/github/ClaudeMonitor';
export const INTERFACE = 'io.github.ClaudeMonitor1';

/**
 * Signals:
 *  - 'snapshot' (snapshot)  new snapshot object
 *  - 'online-changed' (online: boolean)
 */
export class MonitorClient extends EventEmitter {
    constructor() {
        super();
        this.online = false;
        this.snapshot = null;
        this._watchId = 0;
        this._signalId = 0;
        this._cancellable = null;
        this._inFlight = false;
        this._pending = false;
        this._lastRevision = -1;
    }

    start() {
        this._cancellable = new Gio.Cancellable();
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._onAppeared(),
            () => this._onVanished());
    }

    stop() {
        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = 0;
        }
        this._unsubscribe();
        this._cancellable?.cancel();
        this._cancellable = null;
        this.snapshot = null;
        this.online = false;
    }

    _unsubscribe() {
        if (this._signalId) {
            Gio.DBus.session.signal_unsubscribe(this._signalId);
            this._signalId = 0;
        }
    }

    _onAppeared() {
        this._unsubscribe();
        this._signalId = Gio.DBus.session.signal_subscribe(
            BUS_NAME, INTERFACE, 'SnapshotChanged', OBJECT_PATH, null,
            Gio.DBusSignalFlags.NONE,
            (_conn, _sender, _path, _iface, _signal, params) => {
                let revision = -1;
                try {
                    [revision] = params.deep_unpack();
                } catch {
                    // Malformed signal: refetch anyway.
                }
                if (revision !== this._lastRevision)
                    this.refresh();
            });
        this._setOnline(true);
        this.refresh();
    }

    _onVanished() {
        this._unsubscribe();
        this._lastRevision = -1;
        this.snapshot = null;
        this._setOnline(false);
    }

    _setOnline(online) {
        if (this.online === online)
            return;
        this.online = online;
        this.emit('online-changed', online);
    }

    /** Fetch a fresh snapshot; overlapping requests are coalesced. */
    refresh() {
        if (!this.online || !this._cancellable)
            return;
        if (this._inFlight) {
            this._pending = true;
            return;
        }
        this._inFlight = true;
        this._callJson('GetSnapshot', null).then(snapshot => {
            if (snapshot && typeof snapshot === 'object') {
                this.snapshot = snapshot;
                if (Number.isFinite(snapshot.revision))
                    this._lastRevision = snapshot.revision;
                this.emit('snapshot', snapshot);
            }
        }).catch(e => {
            if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                console.debug(`[claude-monitor] GetSnapshot failed: ${e.message}`);
        }).finally(() => {
            this._inFlight = false;
            if (this._pending) {
                this._pending = false;
                this.refresh();
            }
        });
    }

    /** Call a daemon method returning a single JSON string. */
    _callJson(method, params) {
        const cancellable = this._cancellable;
        return new Promise((resolve, reject) => {
            Gio.DBus.session.call(
                BUS_NAME, OBJECT_PATH, INTERFACE, method, params,
                new GLib.VariantType('(s)'),
                Gio.DBusCallFlags.NO_AUTO_START,
                5000,
                cancellable,
                (conn, res) => {
                    try {
                        const reply = conn.call_finish(res);
                        const [json] = reply.deep_unpack();
                        resolve(JSON.parse(json));
                    } catch (e) {
                        reject(e);
                    }
                });
        });
    }
}
