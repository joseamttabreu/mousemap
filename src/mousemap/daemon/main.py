"""mousemapd: captura o mouse, aplica o remapeamento e atende a GUI pelo D-Bus."""

import argparse
import os
import signal
import socket
import sys
from dataclasses import asdict
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
from .engine import Engine

RETRY_SECONDS = 2
LEARN_SECONDS = 10


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


class Daemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.loop = GLib.MainLoop()
        self.state = "starting"       # running | waiting_device | no_permission
        self.error = ""               # erro de configuração (a última válida segue em uso)
        self.config = cfg.Config()
        self.keyboard = None
        self.engine = None
        self.dev = None
        self.mouse_out = None
        self._watch = None
        self._learn_timeout = None
        self._reload_timeout = None
        self.exit_code = 0
        self.dbus = None
        self.app_id = ""              # aplicativo em foco, informado pela extensão do GNOME Shell
        self.wm_class = ""
        self.focus_source = False     # a extensão já informou o foco nesta execução
        self._announced = ("", "")    # (app, perfil) do último ActiveAppChanged

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
        self._disconnect()
        if self.keyboard:
            self.keyboard.close()
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

    def _set_state(self, state):
        if state == self.state:
            return
        self.state = state
        log({"running": f"Remapeamento ativo em {self.dev.path if self.dev else ''}.",
             "waiting_device": "Aguardando o mouse conectar...",
             "no_permission": "Sem permissão para o mouse ou para /dev/uinput."}.get(state, state))
        self._publish_status()

    def _publish_status(self):
        if self.dbus:
            self.dbus.status_changed(self.status())

    # --- dispositivo ---------------------------------------------------------------------

    def _retry(self):
        if self.state != "running":
            self._connect()
        return GLib.SOURCE_CONTINUE

    def _connect(self):
        if self.dev:
            return
        target = device.pick(device.list_mice(), self.config.device)
        if target is None:
            self._set_state("waiting_device")
            return
        try:
            if self.keyboard is None:  # só cria o teclado virtual quando há um mouse para remapear
                self.keyboard = UInput({evdev.ecodes.EV_KEY: keys.KEYBOARD_KEYS}, name="mousemap teclado virtual")
                self.engine = Engine(self.config, self.keyboard, on_learn=self._on_learn)
                self.engine.set_app(self.app_id, self.wm_class)
            dev = evdev.InputDevice(target.path)
        except (PermissionError, UInputError):
            self._set_state("no_permission")
            return
        except OSError as err:
            log(f"Falha ao abrir o mouse: {err}")
            self._set_state("waiting_device")
            return
        try:
            self.mouse_out = UInput.from_device(dev, name=f"{device.VIRTUAL_PREFIX}: {dev.name}")
            dev.grab()
        except OSError as err:
            log(f"Falha ao capturar {dev.path}: {err}")
            if self.mouse_out:
                self.mouse_out.close()
                self.mouse_out = None
            dev.close()
            self._set_state("no_permission" if isinstance(err, PermissionError) else "waiting_device")
            return
        self.dev = dev
        self.engine.mouse = self.mouse_out
        self._watch = GLib.io_add_watch(dev.fd, GLib.PRIORITY_HIGH,
                                        GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_input)
        self._set_state("running")

    def _disconnect(self):
        if self.engine:
            self.engine.release_all()
            self.engine.mouse = None
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = None
        if self.dev:
            try:
                self.dev.ungrab()
            except OSError:
                pass
            self.dev.close()
            self.dev = None
        if self.mouse_out:
            self.mouse_out.close()
            self.mouse_out = None

    def _on_input(self, _fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            return self._lost()
        try:
            for ev in self.dev.read():
                if not self.engine.handle(ev):
                    self.mouse_out.write_event(ev)
        except BlockingIOError:
            pass
        except OSError:
            return self._lost()
        return GLib.SOURCE_CONTINUE

    def _lost(self):
        log("Mouse desconectado.")
        self._watch = None  # a fonte é removida ao retornar SOURCE_REMOVE
        self._disconnect()
        self._set_state("waiting_device")
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
            if self.engine:
                self.engine.configure(new)
        except (cfg.ConfigError, ValueError) as err:
            self.error = str(err)
            log(f"Configuração inválida, mantendo a anterior: {err}")
            self._publish_status()
            return False, self.error
        device_changed = new.device != self.config.device
        self.config, self.error = new, ""
        log("Configuração recarregada.")
        self._announce_app()  # o perfil do app em foco pode ter sido criado ou removido
        if device_changed:
            self._disconnect()
            self.state = "waiting_device"
            self._connect()
        self._publish_status()
        return True, ""

    # --- API para o D-Bus ----------------------------------------------------------------

    @property
    def profile(self):
        if self.engine:
            return self.engine.profile
        return cfg.find_profile(self.config, self.app_id, self.wm_class)

    def set_active_app(self, app_id, wm_class):
        self.focus_source = True
        self.app_id, self.wm_class = app_id.removesuffix(".desktop"), wm_class
        if self.engine:
            self.engine.set_app(self.app_id, self.wm_class)
        self._announce_app()

    def _announce_app(self):
        current = (self.app_id, self.profile)
        if current != self._announced:
            self._announced = current
            if self.dbus:
                self.dbus.active_app_changed(*current)

    def test_profile_action(self, app_id, trigger):
        if trigger not in TRIGGERS:
            return False, _("gatilho desconhecido: {}").format(trigger)
        if app_id and app_id not in self.config.apps:
            return False, _("perfil desconhecido: {}").format(app_id)
        if not self.engine:
            return False, _("serviço sem acesso ao /dev/uinput")
        if not self.engine.test(trigger, profile=app_id):
            return False, _("este botão está no comportamento padrão ou desativado")
        return True, ""

    def status(self):
        return {
            "state": self.state,
            "device": self.dev.name if self.dev else self.config.device,
            "path": self.dev.path if self.dev else "",
            "error": self.error,
            "config_path": str(self.config_path),
            "learning": bool(self.engine and self.engine.learn),
            "app": self.app_id,
            "profile": self.profile,
            "focus_source": self.focus_source,
        }

    def list_devices(self):
        return [{**asdict(m), "accessible": m.accessible} for m in device.list_mice()]

    def set_learn_mode(self, enabled):
        if not self.engine:
            raise RuntimeError(_("serviço sem acesso ao /dev/uinput"))
        self.engine.learn = enabled
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

    def test_action(self, trigger):
        if trigger not in TRIGGERS:
            return False, _("gatilho desconhecido: {}").format(trigger)
        if not self.engine:
            return False, _("serviço sem acesso ao /dev/uinput")
        if not self.engine.test(trigger):
            return False, _("este botão está no comportamento padrão ou desativado")
        return True, ""


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
            device_name = cfg.load(args.config).device
        except cfg.ConfigError:
            device_name = ""
        return diagnose.run(device_name)

    if args.check:
        try:
            config = cfg.load(args.config)
        except cfg.ConfigError as err:
            sys.exit(f"Erro em {args.config}: {err}")
        for warning in config.warnings:
            print(f"Aviso: {warning}")
        for trigger in TRIGGERS:
            print(f"{trigger:13} -> {config.buttons[trigger].describe()}")
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
