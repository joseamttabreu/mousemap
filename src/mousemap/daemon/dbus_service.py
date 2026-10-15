"""Interface D-Bus do daemon (SPEC §8)."""

from gi.repository import Gio, GLib

from .. import DBUS_IFACE, DBUS_NAME, DBUS_PATH, __version__

INTROSPECTION = f"""
<node>
  <interface name="{DBUS_IFACE}">
    <method name="GetStatus"><arg type="a{{sv}}" direction="out" name="status"/></method>
    <method name="Reload">
      <arg type="b" direction="out" name="ok"/><arg type="s" direction="out" name="error"/>
    </method>
    <method name="ListDevices"><arg type="aa{{sv}}" direction="out" name="devices"/></method>
    <method name="SetLearnMode"><arg type="b" direction="in" name="enabled"/></method>
    <method name="TestAction">
      <arg type="s" direction="in" name="trigger"/>
      <arg type="b" direction="out" name="ok"/><arg type="s" direction="out" name="error"/>
    </method>
    <method name="SetActiveApp">
      <arg type="s" direction="in" name="app_id"/><arg type="s" direction="in" name="wm_class"/>
    </method>
    <method name="TestProfileAction">
      <arg type="s" direction="in" name="app_id"/><arg type="s" direction="in" name="trigger"/>
      <arg type="b" direction="out" name="ok"/><arg type="s" direction="out" name="error"/>
    </method>
    <signal name="StatusChanged"><arg type="a{{sv}}" name="status"/></signal>
    <signal name="ActiveAppChanged"><arg type="s" name="app_id"/><arg type="s" name="profile"/></signal>
    <signal name="TriggerPressed"><arg type="s" name="trigger"/></signal>
    <property name="Version" type="s" access="read"/>
  </interface>
</node>
"""


def variant_dict(values):
    """dict Python -> a{sv}, escolhendo o tipo pelo valor."""
    out = {}
    for key, value in values.items():
        if isinstance(value, bool):
            out[key] = GLib.Variant("b", value)
        elif isinstance(value, int):
            out[key] = GLib.Variant("i", value)
        elif isinstance(value, (list, tuple)):
            out[key] = GLib.Variant("as", list(value))
        else:
            out[key] = GLib.Variant("s", str(value))
    return out


class DBusService:
    """Publica `daemon` (main.Daemon) no barramento de sessão."""

    def __init__(self, daemon, on_name_lost):
        self.daemon = daemon
        self.on_name_lost = on_name_lost
        self.connection = None
        self._iface = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION).interfaces[0]
        self._owner_id = Gio.bus_own_name(Gio.BusType.SESSION, DBUS_NAME, Gio.BusNameOwnerFlags.NONE,
                                          self._on_bus, None, self._on_lost)

    def _on_bus(self, connection, _name):
        self.connection = connection
        connection.register_object(DBUS_PATH, self._iface, self._on_call, self._on_get_property, None)

    def _on_lost(self, _connection, name):
        self.on_name_lost(f"não foi possível registrar {name} no D-Bus (outro mousemapd rodando?)")

    def _on_get_property(self, _conn, _sender, _path, _iface, prop):
        return GLib.Variant("s", __version__) if prop == "Version" else None

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        d = self.daemon
        try:
            if method == "GetStatus":
                invocation.return_value(GLib.Variant("(a{sv})", (variant_dict(d.status()),)))
            elif method == "Reload":
                invocation.return_value(GLib.Variant("(bs)", d.reload()))
            elif method == "ListDevices":
                devices = [variant_dict(m) for m in d.list_devices()]
                invocation.return_value(GLib.Variant("(aa{sv})", (devices,)))
            elif method == "SetLearnMode":
                d.set_learn_mode(params.unpack()[0])
                invocation.return_value(None)
            elif method == "TestAction":
                invocation.return_value(GLib.Variant("(bs)", d.test_action(params.unpack()[0])))
            elif method == "SetActiveApp":
                d.set_active_app(*params.unpack())
                invocation.return_value(None)
            elif method == "TestProfileAction":
                invocation.return_value(GLib.Variant("(bs)", d.test_profile_action(*params.unpack())))
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception as err:  # um erro numa chamada não pode derrubar o daemon
            invocation.return_dbus_error(f"{DBUS_IFACE}.Error", str(err))

    def emit(self, signal, signature, args):
        if self.connection:
            self.connection.emit_signal(None, DBUS_PATH, DBUS_IFACE, signal, GLib.Variant(signature, args))

    def status_changed(self, status):
        self.emit("StatusChanged", "(a{sv})", (variant_dict(status),))

    def active_app_changed(self, app_id, profile):
        self.emit("ActiveAppChanged", "(ss)", (app_id, profile))

    def trigger_pressed(self, trigger):
        self.emit("TriggerPressed", "(s)", (trigger,))

    def close(self):
        Gio.bus_unown_name(self._owner_id)
