"""Cliente D-Bus do mousemapd para a GUI."""

from gi.repository import Gio, GLib, GObject

from .. import DBUS_IFACE, DBUS_NAME, DBUS_PATH

TIMEOUT_MS = 3000


class DaemonClient(GObject.Object):
    __gsignals__ = {
        # dict com o status, ou None quando o serviço não está no barramento
        "status-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "trigger-pressed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # (id do aplicativo em foco, perfil vigente — "" = padrão global)
        "active-app-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self):
        super().__init__()
        self.status = None
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
                DBUS_NAME, DBUS_PATH, DBUS_IFACE, None)
        except GLib.Error:
            self.proxy = None
            return
        self.proxy.connect("g-signal", self._on_signal)
        self.proxy.connect("notify::g-name-owner", lambda *_: self.refresh())

    @property
    def available(self):
        return bool(self.proxy and self.proxy.get_name_owner())

    def call(self, method, params=None):
        """Chamada síncrona; retorna a tupla de resposta. Levanta GLib.Error."""
        if not self.proxy:
            raise GLib.Error("sem conexão com o D-Bus")
        result = self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
        return result.unpack() if result else ()

    def refresh(self):
        try:
            self.status = self.call("GetStatus")[0]
        except GLib.Error:
            self.status = None
        self.emit("status-changed", self.status)

    def reload(self):
        return self.call("Reload")

    def list_devices(self):
        try:
            return self.call("ListDevices")[0]
        except GLib.Error:
            return []

    def set_learn_mode(self, enabled):
        self.call("SetLearnMode", GLib.Variant("(b)", (enabled,)))

    def test_action(self, trigger):
        return self.call("TestAction", GLib.Variant("(s)", (trigger,)))

    def test_profile_action(self, app_id, trigger):
        return self.call("TestProfileAction", GLib.Variant("(ss)", (app_id, trigger)))

    def _on_signal(self, _proxy, _sender, name, params):
        if name == "StatusChanged":
            self.status = params.unpack()[0]
            self.emit("status-changed", self.status)
        elif name == "TriggerPressed":
            self.emit("trigger-pressed", params.unpack()[0])
        elif name == "ActiveAppChanged":
            if self.status is not None:
                self.status["app"], self.status["profile"] = params.unpack()
                self.status["focus_source"] = True
            self.emit("active-app-changed", *params.unpack())
