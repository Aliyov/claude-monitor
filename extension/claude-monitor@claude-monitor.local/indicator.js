// Top-bar indicator: session count + 5-hour usage, with a detail menu.

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {UsageView, SessionList, StatusDot, aggregateStatus} from './views.js';
import {formatPercent, readWindow} from './format.js';

export const Indicator = GObject.registerClass({
    Signals: {'menu-open-changed': {}},
}, class Indicator extends PanelMenu.Button {
    _init({settings, pulser, icon, onOpenDashboard, onOpenPrefs}) {
        super._init(0.5, 'Claude Monitor', false);
        this._settings = settings;
        this._snapshot = null;
        this._online = false;

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box cm-panel-box'});
        this._icon = new St.Icon({gicon: icon, style_class: 'system-status-icon cm-panel-icon'});
        this._dot = new StatusDot();
        this._dot.add_style_class_name('cm-panel-dot');
        this._label = new St.Label({
            text: '—',
            style_class: 'cm-panel-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._dot);
        box.add_child(this._label);
        this.add_child(box);

        // Menu content (actors reused; only refreshed while the menu is open).
        this._offlineItem = new PopupMenu.PopupMenuItem(
            'Monitor service not running', {reactive: false, can_focus: false});
        this._offlineItem.add_style_class_name('cm-offline');
        this.menu.addMenuItem(this._offlineItem);

        this._usage = new UsageView();
        const usageItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        usageItem.add_child(this._usage);
        this.menu.addMenuItem(usageItem);
        this._usageItem = usageItem;

        this._midSep = new PopupMenu.PopupSeparatorMenuItem();
        this.menu.addMenuItem(this._midSep);

        this._sessions = new SessionList(pulser, () => {
            this.menu.close();
            onOpenDashboard();
        });
        const sessionsItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        sessionsItem.add_style_class_name('cm-menu-sessions');
        sessionsItem.add_child(this._sessions);
        this.menu.addMenuItem(sessionsItem);
        this._sessionsItem = sessionsItem;

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this.menu.addAction('Open Dashboard', () => onOpenDashboard());
        this.menu.addAction('Preferences', () => onOpenPrefs());

        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._renderMenu();
            this.emit('menu-open-changed');
        });
        this._renderButton();
    }

    get menuOpen() {
        return this.menu.isOpen;
    }

    setOnline(online) {
        this._online = online;
        if (!online)
            this._snapshot = null;
        this._renderButton();
        if (this.menu.isOpen)
            this._renderMenu();
    }

    setSnapshot(snapshot) {
        this._snapshot = snapshot;
        this._online = true;
        this._renderButton();
        if (this.menu.isOpen)
            this._renderMenu();
    }

    tick(nowMs) {
        return this.menu.isOpen ? this._usage.tick(nowMs) : false;
    }

    nearestResetSeconds(nowMs) {
        return this._usage.nearestResetSeconds(nowMs);
    }

    _renderButton() {
        const snap = this._snapshot;
        if (!this._online || !snap) {
            this._label.text = this._online ? '…' : '—';
            this._dot.setStatus('unknown');
            this.add_style_class_name('cm-panel-offline');
            this.remove_style_class_name('cm-attention');
            return;
        }
        this.remove_style_class_name('cm-panel-offline');
        const sessions = snap.sessions ?? [];
        this._dot.setStatus(aggregateStatus(sessions));
        const parts = [`${sessions.length}`];
        const five = readWindow(snap.usage?.five_hour);
        if (five.state === 'ok')
            parts.push(formatPercent(five.pct));
        this._label.text = parts.join('  ');
        if ((snap.totals?.waiting ?? 0) > 0)
            this.add_style_class_name('cm-attention');
        else
            this.remove_style_class_name('cm-attention');
    }

    _renderMenu() {
        const snap = this._snapshot;
        const online = this._online && !!snap;
        this._offlineItem.visible = !this._online;
        this._usageItem.visible = online;
        this._midSep.visible = online;
        this._sessionsItem.visible = online;
        if (!online)
            return;
        this._usage.update(snap.usage);
        this._sessions.update(
            snap.sessions ?? [],
            this._settings.get_int('max-sessions'),
            this._settings.get_boolean('compact-mode'));
    }
});
