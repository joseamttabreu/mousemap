"""Estado da extensão do GNOME Shell que informa o aplicativo em foco (SPEC §14)."""

from gi.repository import Gio, GLib

UUID = "mousemap@joseamttabreu.github.com"
STATE_ACTIVE = 1
STATE_ERROR = 3


class ShellExtension:
    def __init__(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES | Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                None, "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", None)
        except GLib.Error:
            self.proxy = None

    def info(self):
        """Dicionário do Shell ({} = Shell indisponível ou extensão desconhecida)."""
        if not self.proxy:
            return {}
        try:
            reply = self.proxy.call_sync("GetExtensionInfo", GLib.Variant("(s)", (UUID,)),
                                         Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            return {}
        return reply.unpack()[0]

    def enable(self):
        if not self.proxy:
            return False
        try:
            reply = self.proxy.call_sync("EnableExtension", GLib.Variant("(s)", (UUID,)),
                                         Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            return False
        return reply.unpack()[0]
