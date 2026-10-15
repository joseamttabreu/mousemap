// Informa ao mousemapd o aplicativo em foco (SPEC §14).
// Sem dependência do GNOME Shell: recebe display, rastreador de janelas e conexão D-Bus,
// para poder ser testado com gjs fora do Shell.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const BUS_NAME = 'io.github.mousemap.Daemon';
export const OBJECT_PATH = '/io/github/mousemap';
export const INTERFACE = 'io.github.mousemap.Daemon1';

/**
 * Janela em foco -> [id do aplicativo, classe da janela]. Nunca usa o título.
 * Apps sem .desktop ("window-backed") ficam só com a classe da janela.
 */
export function describeWindow(window, tracker) {
    if (!window)
        return ['', ''];
    const wmClass = window.get_wm_class() ?? '';
    const app = tracker.get_window_app(window);
    if (!app || app.is_window_backed())
        return ['', wmClass];
    return [(app.get_id() ?? '').replace(/\.desktop$/, ''), wmClass];
}

export class FocusReporter {
    constructor(display, tracker, connection = Gio.DBus.session) {
        this._display = display;
        this._tracker = tracker;
        this._connection = connection;
        this._last = null;
        this._focusId = 0;
        this._watchId = 0;
    }

    start() {
        this._focusId = this._display.connect('notify::focus-window', () => this.report());
        // Daemon (re)apareceu no barramento: reenvia o foco atual.
        this._watchId = Gio.bus_watch_name_on_connection(this._connection, BUS_NAME,
            Gio.BusNameWatcherFlags.NONE, () => this.report(true), null);
    }

    stop() {
        if (this._focusId)
            this._display.disconnect(this._focusId);
        if (this._watchId)
            Gio.bus_unwatch_name(this._watchId);
        this._focusId = this._watchId = 0;
        this._last = null;
        this._send('', '');
    }

    report(force = false) {
        const [appId, wmClass] = describeWindow(this._display.focus_window, this._tracker);
        const key = `${appId}\n${wmClass}`;
        if (!force && key === this._last)
            return;
        this._last = key;
        this._send(appId, wmClass);
    }

    _send(appId, wmClass) {
        // Assíncrono e sem ativação automática: mudar o foco nunca inicia nem espera o daemon.
        this._connection.call(BUS_NAME, OBJECT_PATH, INTERFACE, 'SetActiveApp',
            new GLib.Variant('(ss)', [appId, wmClass]), null,
            Gio.DBusCallFlags.NO_AUTO_START, 1000, null, (connection, result) => {
                try {
                    connection.call_finish(result);
                } catch {
                    // Daemon ausente ou reiniciando: o bus watch reenvia quando ele voltar.
                }
            });
    }
}
