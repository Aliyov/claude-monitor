// Pure formatting helpers. No GNOME imports so they stay trivially testable.

export const STATUS_LABELS = {
    busy: 'Working',
    waiting: 'Needs you',
    blocked: 'Blocked',
    idle: 'Idle',
    unknown: 'Unknown',
};

export function statusClass(status) {
    return STATUS_LABELS[status] ? status : 'unknown';
}

export function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || !Number.isFinite(bytes))
        return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = bytes;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function formatCpu(pct) {
    if (pct === null || pct === undefined || !Number.isFinite(pct))
        return '—';
    return `${pct >= 10 ? Math.round(pct) : pct.toFixed(1)}%`;
}

export function formatPercent(pct) {
    if (pct === null || pct === undefined || !Number.isFinite(pct))
        return '—';
    return `${Math.round(pct)}%`;
}

/** Duration in seconds → compact "2d 4h", "1h 05m", "12m 30s", "45s". */
export function formatDuration(totalSeconds) {
    if (!Number.isFinite(totalSeconds))
        return '—';
    const s = Math.max(0, Math.floor(totalSeconds));
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (d > 0)
        return `${d}d ${h}h`;
    if (h > 0)
        return `${h}h ${String(m).padStart(2, '0')}m`;
    if (m > 0)
        return `${m}m ${String(sec).padStart(2, '0')}s`;
    return `${sec}s`;
}

/** Milliseconds timestamp → "just now", "5m ago", "2h ago", "3d ago". */
export function formatAgo(ms, nowMs = Date.now()) {
    if (!Number.isFinite(ms))
        return '—';
    const s = Math.max(0, Math.round((nowMs - ms) / 1000));
    if (s < 45)
        return 'just now';
    if (s < 3600)
        return `${Math.round(s / 60)}m ago`;
    if (s < 86400)
        return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
}

export function truncate(text, max) {
    if (!text)
        return '';
    const oneLine = String(text).replace(/\s+/g, ' ').trim();
    return oneLine.length > max ? `${oneLine.slice(0, max - 1)}…` : oneLine;
}

/** Usage severity class for a used percentage. */
export function usageLevel(pct) {
    if (!Number.isFinite(pct))
        return 'none';
    if (pct >= 90)
        return 'critical';
    if (pct >= 70)
        return 'warning';
    return 'normal';
}

/**
 * Interpret one usage window honestly.
 * Returns {state: 'ok'|'reset'|'none', pct, secondsLeft}.
 *  - 'none'  : no data for this window
 *  - 'reset' : resets_at has passed; the old percentage is no longer valid
 *  - 'ok'    : percentage valid, secondsLeft until reset (may be null)
 */
export function readWindow(win, nowMs = Date.now()) {
    if (!win || !Number.isFinite(win.used_percentage))
        return {state: 'none', pct: null, secondsLeft: null};
    if (Number.isFinite(win.resets_at)) {
        const left = win.resets_at - nowMs / 1000;
        if (left <= 0)
            return {state: 'reset', pct: null, secondsLeft: 0};
        return {state: 'ok', pct: win.used_percentage, secondsLeft: left};
    }
    return {state: 'ok', pct: win.used_percentage, secondsLeft: null};
}

/** One-line description of what a session is doing. */
export function describeCurrent(session) {
    const cur = session?.current;
    if (!cur)
        return '';
    const tool = cur.tool ?? '';
    const summary = cur.summary ?? '';
    if (tool && summary)
        return `${tool} · ${summary}`;
    return tool || summary;
}
