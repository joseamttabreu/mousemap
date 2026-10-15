// Testes da lógica da extensão (extension/focus.js), rodados com gjs fora do GNOME Shell.
// Uso: gjs -m tests/extension/test_focus.js [--integration]
// Com --integration, espera um mousemapd no barramento de sessão com um perfil "org.mozilla.firefox".

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import System from 'system';

import {describeWindow, FocusReporter, BUS_NAME, OBJECT_PATH, INTERFACE} from '../../extension/focus.js';

let failures = 0;
function check(name, condition, detail = '') {
    print(`${condition ? 'ok  ' : 'FAIL'} ${name}${condition ? '' : `  ${detail}`}`);
    if (!condition)
        failures++;
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// --- objetos falsos ---------------------------------------------------------------------
const win = (wmClass) => ({get_wm_class: () => wmClass});
const app = (id, windowBacked = false) => ({get_id: () => id, is_window_backed: () => windowBacked});
const tracker = (map) => ({get_window_app: w => map.get(w) ?? null});

class FakeDisplay {
    constructor() {
        this.focus_window = null;
        this._handlers = new Map();
        this._next = 1;
    }

    connect(_signal, callback) {
        this._handlers.set(this._next, callback);
        return this._next++;
    }

    disconnect(id) {
        this._handlers.delete(id);
    }

    focus(window) {
        this.focus_window = window;
        for (const callback of this._handlers.values())
            callback();
    }
}

class RecordingConnection {
    constructor() {
        this.sent = [];
    }

    call(_bus, _path, _iface, method, params) {
        this.sent.push([method, params.deepUnpack()]);
    }
}

// --- describeWindow ---------------------------------------------------------------------
const firefox = win('firefox');
const legacy = win('xterm');
const map = new Map([[firefox, app('org.mozilla.firefox.desktop')], [legacy, app('window:7', true)]]);
check('sem janela em foco', eq(describeWindow(null, tracker(map)), ['', '']));
check('id sem .desktop + classe', eq(describeWindow(firefox, tracker(map)), ['org.mozilla.firefox', 'firefox']));
check('app sem .desktop usa só a classe', eq(describeWindow(legacy, tracker(map)), ['', 'xterm']));
check('janela sem app conhecido', eq(describeWindow(win('foo'), tracker(new Map())), ['', 'foo']));

// --- FocusReporter (sem D-Bus real) -----------------------------------------------------
{
    const display = new FakeDisplay();
    const connection = new RecordingConnection();
    const reporter = new FocusReporter(display, tracker(map), connection);
    reporter._watchId = 0;  // sem bus watch: a conexão falsa não é um GDBusConnection
    reporter._focusId = display.connect('notify::focus-window', () => reporter.report());
    display.focus(firefox);
    display.focus(firefox);  // mesmo foco: não reenvia
    display.focus(legacy);
    reporter.report(true);   // forçado: reenvia
    reporter.stop();
    check('envia só quando o foco muda, e vazio ao parar', eq(connection.sent, [
        ['SetActiveApp', ['org.mozilla.firefox', 'firefox']],
        ['SetActiveApp', ['', 'xterm']],
        ['SetActiveApp', ['', 'xterm']],
        ['SetActiveApp', ['', '']],
    ]), JSON.stringify(connection.sent));
    check('stop desconecta do display', display._handlers.size === 0);
}

// --- integração com o mousemapd real ------------------------------------------------------
function status() {
    const reply = Gio.DBus.session.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, 'GetStatus', null, null,
        Gio.DBusCallFlags.NONE, 2000, null);
    return reply.recursiveUnpack()[0];
}

function waitFor(condition, ms = 3000) {
    const context = GLib.MainContext.default();
    const deadline = GLib.get_monotonic_time() + ms * 1000;
    while (!condition() && GLib.get_monotonic_time() < deadline)
        context.iteration(false) || GLib.usleep(10000);
    return condition();
}

if (ARGV.includes('--integration')) {
    const display = new FakeDisplay();
    const reporter = new FocusReporter(display, tracker(map));
    reporter.start();
    check('integração: bus watch envia o foco inicial (vazio)', waitFor(() => status().focus_source === true));
    display.focus(firefox);
    check('integração: daemon aplica o perfil do Firefox',
        waitFor(() => status().profile === 'org.mozilla.firefox'), JSON.stringify(status()));
    display.focus(legacy);
    check('integração: app sem perfil volta ao padrão',
        waitFor(() => status().profile === '' && status().app === ''), JSON.stringify(status()));
    display.focus(firefox);
    waitFor(() => status().profile === 'org.mozilla.firefox');
    reporter.stop();
    check('integração: desativar a extensão limpa o foco',
        waitFor(() => status().app === '' && status().profile === ''), JSON.stringify(status()));
}

print(failures ? `${failures} falha(s)` : 'todos os testes passaram');
System.exit(failures ? 1 : 0);
