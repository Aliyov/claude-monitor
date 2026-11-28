// Reusable view components for the top-bar menu.
// Every view updates in place (diffed by key); nothing is rebuilt per snapshot.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

import {
    STATUS_LABELS, statusClass, formatBytes, formatCpu, formatPercent,
    formatDuration, formatAgo, readWindow, usageLevel, truncate, describeCurrent,
} from './format.js';

const VERTICAL = Clutter.Orientation.VERTICAL;
const BAR_WIDTH = 96;
const STATUS_CLASSES = ['busy', 'waiting', 'blocked', 'idle', 'unknown'];
const LEVEL_CLASSES = ['normal', 'warning', 'critical', 'none'];
const STALE_MS = 15 * 60 * 1000;

function setExclusiveClass(actor, prefix, classes, active) {
    for (const c of classes) {
        if (c === active)
            actor.add_style_class_name(`${prefix}${c}`);
        else
            actor.remove_style_class_name(`${prefix}${c}`);
    }
}

function ellipsize(label) {
    label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
    label.clutter_text.line_wrap = false;
    return label;
}

/**
 * Shared low-frequency "breathing" for busy status dots.
 * One timer for all dots; it only runs while at least one dot is registered
 * and the owner is active. Each beat is a short ease, then the compositor
 * idles until the next beat, keeping redraw cost tiny.
 */
export class Pulser {
    constructor() {
        this._dots = new Set();
        this._timerId = 0;
        this._enabled = true;
        this._active = false;
    }

    setEnabled(enabled) {
        this._enabled = enabled;
        this._sync();
    }

    setActive(active) {
        this._active = active;
        this._sync();
    }

    add(dot) {
        this._dots.add(dot);
        this._sync();
    }

    remove(dot) {
        if (!this._dots.delete(dot))
            return;
        dot.remove_all_transitions();
        dot.opacity = 255;
        this._sync();
    }

    _sync() {
        const want = this._enabled && this._active && this._dots.size > 0;
        if (want && !this._timerId) {
            this._timerId = GLib.timeout_add(GLib.PRIORITY_LOW, 2400, () => {
                this._beat();
                return GLib.SOURCE_CONTINUE;
            });
            this._beat();
        } else if (!want && this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
            for (const dot of this._dots) {
                dot.remove_all_transitions();
                dot.opacity = 255;
            }
        }
    }

    _beat() {
        for (const dot of this._dots) {
            if (!dot.mapped)
                continue;
            dot.ease({
                opacity: 70,
                duration: 600,
                mode: Clutter.AnimationMode.EASE_IN_OUT_SINE,
                onComplete: () => dot.ease({
                    opacity: 255,
                    duration: 600,
                    mode: Clutter.AnimationMode.EASE_IN_OUT_SINE,
                }),
            });
        }
    }

    destroy() {
        this._enabled = false;
        this._sync();
        this._dots.clear();
    }
}

export const StatusDot = GObject.registerClass(
class StatusDot extends St.Widget {
    _init() {
        super._init({
            style_class: 'cm-dot cm-dot-unknown',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._status = 'unknown';
    }

    setStatus(status) {
        const cls = statusClass(status);
        if (cls === this._status)
            return;
        this._status = cls;
        setExclusiveClass(this, 'cm-dot-', STATUS_CLASSES, cls);
    }

    get status() {
        return this._status;
    }
});

const UsageRow = GObject.registerClass(
class UsageRow extends St.BoxLayout {
    _init(title) {
        super._init({style_class: 'cm-usage-row', x_expand: true});
        this._title = new St.Label({
            text: title,
            style_class: 'cm-usage-title',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._bar = new St.Widget({
            style_class: 'cm-bar',
            width: BAR_WIDTH,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._fill = new St.Widget({style_class: 'cm-bar-fill cm-level-none', width: 0});
        this._bar.add_child(this._fill);
        this._pct = new St.Label({
            text: '—',
            style_class: 'cm-usage-pct',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._reset = new St.Label({
            text: '',
            style_class: 'cm-usage-reset',
            x_expand: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._title);
        this.add_child(this._bar);
        this.add_child(this._pct);
        this.add_child(this._reset);
        this._win = null;
        this._lastPct = null;
    }

    setWindow(win) {
        this._win = win;
        this.tick(Date.now());
    }

    /** Re-render from stored window data; returns true if a countdown is shown. */
    tick(nowMs) {
        const r = readWindow(this._win, nowMs);
        if (r.state === 'ok') {
            if (r.pct !== this._lastPct) {
                this._lastPct = r.pct;
                const w = Math.round(BAR_WIDTH * Math.min(100, Math.max(0, r.pct)) / 100);
                this._fill.ease({
                    width: w,
                    duration: 400,
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                });
                setExclusiveClass(this._fill, 'cm-level-', LEVEL_CLASSES, usageLevel(r.pct));
                this._pct.text = formatPercent(r.pct);
            }
            this._reset.text = r.secondsLeft !== null ? `resets ${formatDuration(r.secondsLeft)}` : '';
            return r.secondsLeft !== null;
        }
        // 'reset' (window rolled over, old value invalid) or 'none' (unknown):
        // never show a stale or invented percentage.
        if (this._lastPct !== null) {
            this._lastPct = null;
            this._fill.remove_all_transitions();
            this._fill.width = 0;
            setExclusiveClass(this._fill, 'cm-level-', LEVEL_CLASSES, 'none');
        }
        this._pct.text = '—';
        this._reset.text = r.state === 'reset' ? 'reset · awaiting update' : '';
        return false;
    }
});

export const UsageView = GObject.registerClass(
class UsageView extends St.BoxLayout {
    _init() {
        super._init({orientation: VERTICAL, style_class: 'cm-usage', x_expand: true});
        this._five = new UsageRow('5h');
        this._week = new UsageRow('7d');
        this._limit = ellipsize(new St.Label({style_class: 'cm-limit-hit', visible: false}));
        this._hint = ellipsize(new St.Label({style_class: 'cm-hint', visible: false}));
        this._asOf = ellipsize(new St.Label({style_class: 'cm-hint', visible: false}));
        this.add_child(this._five);
        this.add_child(this._week);
        this.add_child(this._limit);
        this.add_child(this._hint);
        this.add_child(this._asOf);
        this._usage = null;
    }

    update(usage) {
        this._usage = usage ?? null;
        const has = this._hasLimits();
        this._five.visible = has;
        this._week.visible = has;
        if (has) {
            this._five.setWindow(usage.five_hour ?? null);
            this._week.setWindow(usage.seven_day ?? null);
            this._hint.visible = false;
        } else {
            this._hint.visible = true;
            this._hint.text = usage?.statusline_installed
                ? 'Limits: — · waiting for Claude Code to report'
                : 'Limits: — · enable status-line integration';
        }
        this.tick(Date.now());
    }

    _hasLimits() {
        const u = this._usage;
        return !!u && u.source !== 'none' && (!!u.five_hour || !!u.seven_day);
    }

    /** Refresh countdowns. Returns true while anything is counting down. */
    tick(nowMs) {
        let counting = false;
        if (this._hasLimits()) {
            counting = this._five.tick(nowMs) || counting;
            counting = this._week.tick(nowMs) || counting;
        }
        const hit = this._usage?.last_limit_hit;
        if (hit && Number.isFinite(hit.resets_at) && hit.resets_at * 1000 > nowMs) {
            const left = hit.resets_at - nowMs / 1000;
            this._limit.text = `Limit reached · resets in ${formatDuration(left)}`;
            this._limit.visible = true;
            counting = true;
        } else {
            this._limit.visible = false;
        }
        const asOf = this._usage?.as_of;
        if (this._hasLimits() && Number.isFinite(asOf) && nowMs - asOf > STALE_MS) {
            this._asOf.text = `Limits as of ${formatAgo(asOf, nowMs)}`;
            this._asOf.visible = true;
        } else {
            this._asOf.visible = false;
        }
        return counting;
    }

    /** Smallest seconds-until-reset currently displayed, or null. */
    nearestResetSeconds(nowMs) {
        const u = this._usage;
        if (!u)
            return null;
        const cands = [u.five_hour?.resets_at, u.seven_day?.resets_at, u.last_limit_hit?.resets_at]
            .filter(Number.isFinite)
            .map(s => s - nowMs / 1000)
            .filter(s => s > 0);
        return cands.length ? Math.min(...cands) : null;
    }
});

const SessionRow = GObject.registerClass(
class SessionRow extends St.BoxLayout {
    _init(pulser, onActivate) {
        super._init({
            orientation: VERTICAL,
            style_class: 'cm-session',
            reactive: true,
            track_hover: true,
            x_expand: true,
        });
        this._pulser = pulser;
        const top = new St.BoxLayout({style_class: 'cm-session-top', x_expand: true});
        this._dot = new StatusDot();
        this._project = ellipsize(new St.Label({
            style_class: 'cm-session-project',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._agents = new St.Label({
            style_class: 'cm-badge',
            visible: false,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._status = new St.Label({
            style_class: 'cm-session-status',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._res = new St.Label({
            style_class: 'cm-session-res',
            y_align: Clutter.ActorAlign.CENTER,
        });
        top.add_child(this._dot);
        top.add_child(this._project);
        top.add_child(this._agents);
        top.add_child(this._status);
        top.add_child(this._res);
        this._activity = ellipsize(new St.Label({style_class: 'cm-session-activity', x_expand: true}));
        this.add_child(top);
        this.add_child(this._activity);

        if (onActivate) {
            this._click = new Clutter.ClickGesture();
            this._click.connect('recognize', () => onActivate(this._sessionId));
            this.add_action(this._click);
        }
        this.connect('destroy', () => this._pulser.remove(this._dot));
    }

    update(s, compact) {
        this._sessionId = s.session_id;
        this._dot.setStatus(s.status);
        if (this._dot.status === 'busy')
            this._pulser.add(this._dot);
        else
            this._pulser.remove(this._dot);

        this._project.text = s.project || s.name || truncate(s.session_id, 8);
        const running = (s.agents ?? []).filter(a => a.status === 'running').length;
        this._agents.visible = running > 0;
        this._agents.text = `${running} agent${running === 1 ? '' : 's'}`;
        this._status.text = STATUS_LABELS[statusClass(s.status)];
        setExclusiveClass(this._status, 'cm-text-', STATUS_CLASSES, statusClass(s.status));

        this._res.visible = !compact;
        const ctx = Number.isFinite(s.context_percent) ? ` · ctx ${formatPercent(s.context_percent)}` : '';
        this._res.text = `${formatCpu(s.cpu_percent)} · ${formatBytes(s.rss_bytes)}${ctx}`;

        const activity = describeCurrent(s);
        this._activity.visible = !compact && activity.length > 0;
        this._activity.text = truncate(activity, 80);
    }
});

/** List of live sessions, diffed by session_id. */
export const SessionList = GObject.registerClass(
class SessionList extends St.BoxLayout {
    _init(pulser, onActivate) {
        super._init({orientation: VERTICAL, style_class: 'cm-sessions', x_expand: true});
        this._pulser = pulser;
        this._onActivate = onActivate;
        this._rows = new Map();
        this._empty = new St.Label({style_class: 'cm-hint', text: 'No active Claude Code sessions'});
        this._more = new St.Label({style_class: 'cm-hint', visible: false});
        this.add_child(this._empty);
        this.add_child(this._more);
    }

    update(sessions, maxShown, compact) {
        const list = [...(sessions ?? [])].sort(sessionOrder);
        const shown = list.slice(0, Math.max(1, maxShown));
        const keep = new Set(shown.map(s => s.session_id));

        for (const [id, row] of this._rows) {
            if (!keep.has(id)) {
                row.destroy();
                this._rows.delete(id);
            }
        }
        shown.forEach((s, i) => {
            let row = this._rows.get(s.session_id);
            if (!row) {
                row = new SessionRow(this._pulser, this._onActivate);
                this._rows.set(s.session_id, row);
                this.insert_child_at_index(row, i);
                row.opacity = 0;
                row.ease({opacity: 255, duration: 250, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
            } else if (this.get_child_at_index(i) !== row) {
                this.set_child_at_index(row, i);
            }
            row.update(s, compact);
        });

        this._empty.visible = list.length === 0;
        const extra = list.length - shown.length;
        this._more.visible = extra > 0;
        this._more.text = `+${extra} more session${extra === 1 ? '' : 's'}`;
    }
});

const STATUS_RANK = {waiting: 0, blocked: 1, busy: 2, idle: 3, unknown: 4};

/** Sessions needing attention first, then busy, then most recently active. */
function sessionOrder(a, b) {
    const ra = STATUS_RANK[statusClass(a.status)];
    const rb = STATUS_RANK[statusClass(b.status)];
    if (ra !== rb)
        return ra - rb;
    return (b.last_activity_at ?? b.started_at ?? 0) - (a.last_activity_at ?? a.started_at ?? 0);
}

/** Aggregate status for a set of sessions (for the pill / panel dot). */
export function aggregateStatus(sessions) {
    if (!sessions?.length)
        return 'unknown';
    let best = 'unknown';
    for (const s of sessions) {
        const st = statusClass(s.status);
        if (STATUS_RANK[st] < STATUS_RANK[best])
            best = st;
    }
    return best;
}
