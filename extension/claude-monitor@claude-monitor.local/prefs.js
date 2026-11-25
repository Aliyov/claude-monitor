import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class ClaudeMonitorPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window.set_default_size(520, 420);

        const page = new Adw.PreferencesPage({
            title: 'General',
            icon_name: 'preferences-system-symbolic',
        });
        window.add(page);

        const menu = new Adw.PreferencesGroup({
            title: 'Top-bar menu',
            description: 'Claude Monitor shows data from the local claude-monitord service only.',
        });
        page.add(menu);

        const maxSessions = new Adw.SpinRow({
            title: 'Sessions shown',
            subtitle: 'Sessions needing attention are listed first',
            adjustment: new Gtk.Adjustment({
                lower: 1, upper: 20, step_increment: 1, page_increment: 5,
            }),
        });
        settings.bind('max-sessions', maxSessions, 'value', Gio.SettingsBindFlags.DEFAULT);
        menu.add(maxSessions);

        menu.add(this._switch(settings, 'compact-mode', 'Compact mode',
            'Hide the activity and CPU / memory lines'));
        menu.add(this._switch(settings, 'reduce-animations', 'Reduce animations',
            'Disable the pulsing status dot'));
    }

    _switch(settings, key, title, subtitle) {
        const row = new Adw.SwitchRow({title, subtitle});
        settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT);
        return row;
    }
}
