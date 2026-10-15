"""mousemapd: captura os mouses, aplica o remapeamento e atende a GUI pelo D-Bus."""

import argparse
import os
import signal
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import evdev
from evdev import UInput
from evdev.uinput import UInputError
from gi.repository import Gio, GLib

try:
    from gi.repository import GLibUnix
    _signal_add = GLibUnix.signal_add
except ImportError:  # PyGObject antigo
    _signal_add = GLib.unix_signal_add

from .. import config as cfg
from .. import keys
from ..config import TRIGGERS
from ..i18n import _
from . import device
from .dbus_service import DBusService
from .engine import Engine, SharedKeyboard

RETRY_SECONDS = 2
LEARN_SECONDS = 10
MOUSE_PROFILE_PREFIX = "mouse:"  # TestProfileAction("mouse:<nome>", …) testa o perfil de um mouse


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def sd_notify(message):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(message.encode())
    except OSError:
        pass


def glib_schedule(ms, function):
    GLib.timeout_add(ms, lambda: function() or GLib.SOURCE_REMOVE)


@dataclass
class Session:
    """Um mouse capturado: dispositivo físico, mouse virtual, motor e a fonte do loop principal."""
    dev: evdev.InputDevice
    out: UInput
    engine: Engine
    watch: int = 0

    @property
    def name(self):
        return self.dev.name


class Daemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.loop = GLib.MainLoop()
        self.state = "starting"       # running | waiting_device | no_permission
        self.error = ""               # erro de configuração (a última válida segue em uso)
        self.config = cfg.Config()
        self.keyboard = None          # SharedKeyboard, criado quando há um mouse para remapear
        self.sessions = {}            # caminho do evdev -> Session
        self.learning = False
        self._learn_timeout = None
        self._reload_timeout = None
        self._published = None
        self.exit_code = 0
        self.dbus = None
        self.app_id = ""              # aplicativo em foco, informado pela extensão do GNOME Shell
        self.wm_class = ""
        self.focus_source = False     # a extensão já informou o foco nesta execução
        self._announced = ("", "")    # (app, perfil) do último ActiveAppChanged

    @property
    def engines(self):
        return [s.engine for s in self.sessions.values()]

    # --- ciclo de vida -------------------------------------------------------------------

    def run(self):
        try:
            self.config = cfg.load(self.config_path)
        except cfg.ConfigError as err:
            self.error = str(err)
            log(f"Configuração inválida, usando padrões: {err}")
        for warning in self.config.warnings:
            log(f"Aviso: {warning}")
        self.dbus = DBusService(self, self._fatal)
        self._monitor_config()
        _signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        _signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit)
        GLib.timeout_add_seconds(RETRY_SECONDS, self._retry)
        watchdog = int(os.environ.get("WATCHDOG_USEC", "0"))
        if watchdog:
            GLib.timeout_add(max(watchdog // 2000, 500), lambda: sd_notify("WATCHDOG=1") or True)
        self._connect()
        sd_notify("READY=1")
        self.loop.run()
        self._disconnect_all()
        if self.keyboard:
            self.keyboard.device.close()
        self.dbus.close()
        return self.exit_code

    def quit(self):
        sd_notify("STOPPING=1")
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def _fatal(self, message):
        log(message)
        self.exit_code = 1
        self.loop.quit()

    def _update_state(self, no_permission=False):
        state = "running" if self.sessions else ("no_permission" if no_permission else "waiting_device")
        if state != self.state:
            self.state = state
            if state == "waiting_device":
                log("Aguardando o mouse conectar...")
            elif state == "no_permission":
                log("Sem permissão para o mouse ou para /dev/uinput.")
        self._publish_status()

    def _publish_status(self):
        status = self.status()
        if self.dbus and status != self._published:  # só avisa a GUI quando algo mudou
            self._published = status
            self.dbus.status_changed(status)

    # --- dispositivos --------------------------------------------------------------------

    def _retry(self):
        self._connect()  # também pega um segundo mouse configurado que conectou depois
        return GLib.SOURCE_CONTINUE

    def _connect(self):
        connected = {s.dev.path for s in self.sessions.values()}
        targets = [t for t in device.pick_many(device.list_mice(), self.config.devices) if t.path not in connected]
        if not self.config.devices and self.sessions:
            targets = []  # automático: um mouse só
        no_permission = False
        for target in targets:
            try:
                self._open(target)
            except (PermissionError, UInputError):
                no_permission = True
            except OSError as err:
                log(f"Falha ao capturar {target.path}: {err}")
        self._update_state(no_permission)

    def _open(self, target):
        if self.keyboard is None:  # só cria o teclado virtual quando há um mouse para remapear
            self.keyboard = SharedKeyboard(
                UInput({evdev.ecodes.EV_KEY: keys.KEYBOARD_KEYS}, name="mousemap teclado virtual"))
        dev = evdev.InputDevice(target.path)
        out = None
        try:
            out = UInput.from_device(dev, name=f"{device.VIRTUAL_PREFIX}: {dev.name}")
            dev.grab()
        except OSError:
            if out:
                out.close()
            dev.close()
            raise
        engine = Engine(self.config, self.keyboard, out, on_learn=self._on_learn,
                        schedule=glib_schedule, mouse_name=dev.name)
        engine.set_app(self.app_id, self.wm_class)
        engine.learn = self.learning
        session = Session(dev, out, engine)
        session.watch = GLib.io_add_watch(dev.fd, GLib.PRIORITY_HIGH, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                                          self._on_input, dev.path)
        self.sessions[dev.path] = session
        log(f"Remapeamento ativo em {dev.path} ({dev.name}).")

    def _close(self, path, remove_watch=True):
        session = self.sessions.pop(path, None)
        if not session:
            return
        session.engine.release_all()
        session.engine.mouse = None
        if remove_watch and session.watch:
            GLib.source_remove(session.watch)
        try:
            session.dev.ungrab()
        except OSError:
            pass
        session.dev.close()
        session.out.close()

    def _disconnect_all(self):
        for path in list(self.sessions):
            self._close(path)

    def _on_input(self, _fd, condition, path):
        session = self.sessions.get(path)
        if not session:
            return GLib.SOURCE_REMOVE
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            return self._lost(path)
        try:
            for ev in session.dev.read():
                if not session.engine.handle(ev):
                    session.out.write_event(ev)
        except BlockingIOError:
            pass
        except OSError:
            return self._lost(path)
        return GLib.SOURCE_CONTINUE

    def _lost(self, path):
        log(f"Mouse desconectado: {path}.")
        self._close(path, remove_watch=False)  # a fonte é removida ao retornar SOURCE_REMOVE
        self._update_state()
        return GLib.SOURCE_REMOVE

    # --- configuração --------------------------------------------------------------------

    def _monitor_config(self):
        directory = Gio.File.new_for_path(str(self.config_path.parent))
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self._monitor = directory.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except (OSError, GLib.Error) as err:
            log(f"Sem monitoramento da configuração: {err}")
            return
        self._monitor.connect("changed", self._on_config_changed)

    def _on_config_changed(self, _monitor, file, other, _event):
        names = {f.get_basename() for f in (file, other) if f}
        if self.config_path.name not in names:
            return
        if self._reload_timeout:
            GLib.source_remove(self._reload_timeout)
        self._reload_timeout = GLib.timeout_add(300, self._reload_from_monitor)

    def _reload_from_monitor(self):
        self._reload_timeout = None
        self.reload()
        return GLib.SOURCE_REMOVE

    def reload(self):
        try:
            new = cfg.load(self.config_path)
            for engine in self.engines:
                engine.configure(new)
        except (cfg.ConfigError, ValueError) as err:
            self.error = str(err)
            log(f"Configuração inválida, mantendo a anterior: {err}")
            self._publish_status()
            return False, self.error
        devices_changed = new.devices != self.config.devices
        self.config, self.error = new, ""
        log("Configuração recarregada.")
        for engine in self.engines:
            engine.cancel_macro()  # macro em andamento é da configuração anterior
        self._announce_app()  # o perfil do app em foco pode ter sido criado ou removido
        if devices_changed:
            self._disconnect_all()
            self._connect()
        self._publish_status()
        return True, ""

    # --- API para o D-Bus ----------------------------------------------------------------

    @property
    def profile(self):
        engines = self.engines
        if engines:
            return engines[0].profile
        return cfg.find_profile(self.config, self.app_id, self.wm_class)

    def set_active_app(self, app_id, wm_class):
        self.focus_source = True
        self.app_id, self.wm_class = app_id.removesuffix(".desktop"), wm_class
        for engine in self.engines:
            engine.set_app(self.app_id, self.wm_class)
        self._announce_app()

    def _announce_app(self):
        current = (self.app_id, self.profile)
        if current != self._announced:
            self._announced = current
            if self.dbus:
                self.dbus.active_app_changed(*current)

    def _test(self, trigger, profile):
        """profile: None = vigente, "" = padrão, "<app>" = perfil do app, "mouse:<nome>" = perfil do mouse."""
        if trigger not in TRIGGERS:
            return False, _("gatilho desconhecido: {}").format(trigger)
        if not self.engines:
            return False, _("nenhum mouse capturado")
        engine = self.engines[0]
        if profile and profile.startswith(MOUSE_PROFILE_PREFIX):
            name = profile.removeprefix(MOUSE_PROFILE_PREFIX)
            engine = next((s.engine for s in self.sessions.values() if s.name == name), None)
            if engine is None:
                return False, _("mouse não conectado: {}").format(name)
            profile = ""
        elif profile and profile not in self.config.apps:
            return False, _("perfil desconhecido: {}").format(profile)
        if not engine.test(trigger, profile=profile):
            return False, _("este botão está no comportamento padrão ou desativado")
        return True, ""

    def test_action(self, trigger):
        return self._test(trigger, None)

    def test_profile_action(self, profile, trigger):
        return self._test(trigger, profile)

    def status(self):
        names = [s.name for s in self.sessions.values()]
        return {
            "state": self.state,
            "device": ", ".join(names or self.config.devices),
            "devices": names,
            "path": next(iter(self.sessions), ""),
            "error": self.error,
            "config_path": str(self.config_path),
            "learning": self.learning,
            "app": self.app_id,
            "profile": self.profile,
            "focus_source": self.focus_source,
        }

    def list_devices(self):
        return [{**asdict(m), "accessible": m.accessible} for m in device.list_mice()]

    def set_learn_mode(self, enabled):
        if enabled and not self.sessions:
            raise RuntimeError(_("nenhum mouse capturado"))
        self.learning = enabled
        for engine in self.engines:
            engine.learn = enabled
        if self._learn_timeout:
            GLib.source_remove(self._learn_timeout)
            self._learn_timeout = None
        if enabled:
            self._learn_timeout = GLib.timeout_add_seconds(LEARN_SECONDS, self._learn_expired)
        self._publish_status()

    def _learn_expired(self):
        self._learn_timeout = None
        self.set_learn_mode(False)
        return GLib.SOURCE_REMOVE

    def _on_learn(self, trigger):
        self.dbus.trigger_pressed(trigger)


def main():
    parser = argparse.ArgumentParser(prog="mousemapd", description="Serviço de remapeamento do mousemap.")
    parser.add_argument("--config", type=Path, default=cfg.config_path())
    parser.add_argument("--check", action="store_true", help="valida a configuração e sai")
    parser.add_argument("--list", action="store_true", help="lista os mouses detectados e sai")
    parser.add_argument("--diagnose", action="store_true",
                        help="diagnóstico guiado: mostra o evento que cada botão extra envia")
    args = parser.parse_args()

    if args.diagnose:
        from . import diagnose
        try:
            devices = cfg.load(args.config).devices
        except cfg.ConfigError:
            devices = []
        return diagnose.run(devices[0] if devices else "")

    if args.check:
        try:
            config = cfg.load(args.config)
        except cfg.ConfigError as err:
            sys.exit(f"Erro em {args.config}: {err}")
        for warning in config.warnings:
            print(f"Aviso: {warning}")
        print(f"mouses: {', '.join(config.devices) or 'automático'}")
        for trigger in TRIGGERS:
            print(f"{trigger:13} -> {config.buttons[trigger].describe()}")
        for table, title in ((config.mice, "mouse"), (config.apps, "app")):
            for key, profile in table.items():
                changes = ", ".join(f"{t} -> {a.describe()}" for t, a in profile.buttons.items()) or "nada"
                print(f"[{title} {key}] {changes}")
        return 0
    if args.list:
        for m in device.list_mice():
            access = "" if m.accessible else "  (sem permissão)"
            print(f"{m.path:20} {m.bus:10} {m.name}  [{', '.join(m.triggers) or 'sem botões extras'}]{access}")
        return 0

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # comandos disparados não viram zumbis
    return Daemon(args.config).run()


if __name__ == "__main__":
    sys.exit(main())
