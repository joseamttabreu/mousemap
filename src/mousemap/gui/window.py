"""Janela principal (SPEC §7)."""

import shutil
import subprocess
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import APP_ID, __version__
from .. import config as cfg
from ..i18n import _
from ..config import COOLDOWN_RANGE, TRIGGER_LABELS, TRIGGERS, Action
from .action_dialog import ActionDialog
from .daemon_client import DaemonClient

SERVICE = "mousemapd.service"
RETRY_MS = 2500  # o daemon tenta reconectar a cada 2 s
BUS_LABELS = {"bluetooth": "Bluetooth", "usb": "USB", "ps2": "PS/2", "i2c": _("Integrado"), "host": _("Integrado")}
CSS = ".mm-highlight { background-color: alpha(@accent_bg_color, 0.3); }"


def setup_script():
    """Script de permissões: instalado (/usr/libexec) ou no repositório (desenvolvimento)."""
    for candidate in (Path("/usr/libexec/mousemap-setup"), Path(__file__).resolve().parents[3] / "data" / "mousemap-setup"):
        if candidate.exists():
            return str(candidate)
    return shutil.which("mousemap-setup")


def systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="mousemap", default_width=560, default_height=680)
        self.client = DaemonClient()
        self.config = cfg.Config()
        self.config_error = ""
        self.rows = {}
        self._updating = False
        self._save_timeout = None
        self._device_names = [""]

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._build()
        self._load_config()
        self.client.connect("status-changed", self._on_status)
        self.client.connect("trigger-pressed", self._on_trigger)
        self.client.refresh()

    # --- construção ------------------------------------------------------------------------

    def _build(self):
        for name, callback in (("reset", self._on_reset), ("open-config", self._on_open_config),
                               ("about", self._on_about)):
            action = Gio.SimpleAction(name=name)
            action.connect("activate", callback)
            self.add_action(action)
        menu = Gio.Menu()
        menu.append(_("Restaurar padrões"), "win.reset")
        menu.append(_("Abrir arquivo de configuração"), "win.open-config")
        menu.append(_("Sobre o mousemap"), "win.about")
        header = Adw.HeaderBar()
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Menu")))

        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", self._on_banner_button)

        page = Adw.PreferencesPage()

        mouse_group = Adw.PreferencesGroup(title=_("Mouse"))
        self.device_model = Gtk.StringList.new([_("Automático")])
        self.device_row = Adw.ComboRow(title=_("Dispositivo"), model=self.device_model)
        self.device_row.connect("notify::selected", self._on_device_selected)
        mouse_group.add(self.device_row)
        page.add(mouse_group)

        buttons_group = Adw.PreferencesGroup(title=_("Botões"),
                                             description=_("Clique em um botão para escolher o que ele faz."))
        self.identify_button = Gtk.ToggleButton(label=_("Identificar botão"), valign=Gtk.Align.CENTER,
                                                tooltip_text=_("Aperte um botão do mouse para encontrá-lo na lista"))
        self.identify_button.connect("toggled", self._on_identify_toggled)
        buttons_group.set_header_suffix(self.identify_button)
        for trigger in TRIGGERS:
            row = Adw.ActionRow(title=TRIGGER_LABELS[trigger], activatable=True)
            test = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text=_("Testar"), css_classes=["flat"])
            test.connect("clicked", self._on_test, trigger)
            row.add_suffix(test)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self._on_row_activated, trigger)
            buttons_group.add(row)
            self.rows[trigger] = row
        page.add(buttons_group)

        settings_group = Adw.PreferencesGroup(title=_("Ajustes"))
        lo, hi = COOLDOWN_RANGE
        self.cooldown_row = Adw.SpinRow.new_with_range(lo, hi, 50)
        self.cooldown_row.set_title(_("Repetição da inclinação"))
        self.cooldown_row.set_subtitle(_("Intervalo, em milissegundos, com a roda mantida inclinada"))
        self.cooldown_row.connect("notify::value", self._on_cooldown_changed)
        settings_group.add(self.cooldown_row)
        self.autostart_row = Adw.SwitchRow(title=_("Iniciar com a sessão"),
                                           subtitle=_("Liga o remapeamento automaticamente ao entrar"))
        result = systemctl("is-enabled", SERVICE)
        self.autostart_row.set_active(bool(result and result.stdout.strip() == "enabled"))
        self.autostart_row.connect("notify::active", self._on_autostart_changed)
        settings_group.add(self.autostart_row)
        page.add(settings_group)

        self.toasts = Adw.ToastOverlay(child=page)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        self.set_content(view)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    # --- configuração ----------------------------------------------------------------------

    def _load_config(self):
        try:
            self.config = cfg.load()
            self.config_error = ""
        except cfg.ConfigError as err:
            self.config = cfg.Config()
            self.config_error = str(err)
        self._show_config()
        self._update_banner()

    def _show_config(self):
        self._updating = True
        for trigger, row in self.rows.items():
            row.set_subtitle(GLib.markup_escape_text(self.config.buttons[trigger].describe()))
        self.cooldown_row.set_value(self.config.tilt_cooldown_ms)
        self._fill_devices()
        self._updating = False

    def _save(self, message=_("Aplicado")):
        try:
            cfg.save(self.config)
        except OSError as err:
            self.toast(_("Não foi possível salvar: {}").format(err))
            return
        self.config_error = ""
        if not self.client.available:
            self.toast(_("Salvo. Será aplicado quando o serviço iniciar."))
        else:
            try:
                ok, error = self.client.reload()
            except GLib.Error as err:
                ok, error = False, err.message
            self.toast(message if ok else _("Erro ao aplicar: {}").format(error))
        self._update_banner()

    def _set_action(self, trigger, action):
        self.config.buttons[trigger] = action
        self._show_config()
        self._save()

    # --- eventos da interface ----------------------------------------------------------------

    def _on_row_activated(self, _row, trigger):
        if self.identify_button.get_active():
            self.identify_button.set_active(False)
        ActionDialog(trigger, self.config.buttons[trigger],
                     lambda action: self._set_action(trigger, action)).present(self)

    def _on_test(self, _button, trigger):
        if not self.client.available:
            self.toast(_("O serviço não está rodando."))
            return
        try:
            ok, error = self.client.test_action(trigger)
        except GLib.Error as err:
            ok, error = False, err.message
        if not ok:
            self.toast(error[:1].upper() + error[1:])

    def _on_cooldown_changed(self, row, _pspec):
        if self._updating:
            return
        self.config.tilt_cooldown_ms = int(row.get_value())
        if self._save_timeout:
            GLib.source_remove(self._save_timeout)
        self._save_timeout = GLib.timeout_add(600, self._save_cooldown)

    def _save_cooldown(self):
        self._save_timeout = None
        self._save()
        return GLib.SOURCE_REMOVE

    def _on_autostart_changed(self, row, _pspec):
        result = systemctl("enable" if row.get_active() else "disable", SERVICE)
        if not result or result.returncode != 0:
            self.toast(_("Não foi possível alterar a inicialização do serviço."))

    def _on_identify_toggled(self, button):
        if self._updating:
            return
        try:
            self.client.set_learn_mode(button.get_active())
        except GLib.Error as err:
            self.toast(_("Não foi possível identificar: {}").format(err.message))
            self._updating = True
            button.set_active(False)
            self._updating = False
            return
        if button.get_active():
            self.toast(_("Aperte um botão extra do mouse…"))

    def _on_trigger(self, _client, trigger):
        row = self.rows.get(trigger)
        if not row:
            return
        row.grab_focus()
        row.add_css_class("mm-highlight")
        GLib.timeout_add(1200, lambda: row.remove_css_class("mm-highlight") or GLib.SOURCE_REMOVE)
        self.toast(_("Detectado: {}").format(TRIGGER_LABELS[trigger]))

    # --- dispositivos ------------------------------------------------------------------------

    def _fill_devices(self):
        devices = self.client.list_devices()
        names = [""] + [d["name"] for d in devices]
        labels = [_("Automático")] + [f"{d['name']} ({BUS_LABELS.get(d['bus'], d['bus'])})" for d in devices]
        if self.config.device and self.config.device not in names:
            names.append(self.config.device)
            labels.append(_("{} (desconectado)").format(self.config.device))
        was_updating, self._updating = self._updating, True
        if names != self._device_names:
            self._device_names = names
            self.device_model.splice(0, self.device_model.get_n_items(), labels)
        self.device_row.set_selected(names.index(self.config.device) if self.config.device in names else 0)
        self._updating = was_updating

    def _on_device_selected(self, row, _pspec):
        if self._updating:
            return
        name = self._device_names[row.get_selected()]
        if name != self.config.device:
            self.config.device = name
            self._save(_("Dispositivo alterado"))

    # --- estado do serviço -------------------------------------------------------------------

    def _on_status(self, _client, status):
        self._updating = True
        self.identify_button.set_active(bool(status and status.get("learning")))
        self.identify_button.set_sensitive(bool(status and status.get("state") == "running"))
        self._updating = False
        self._fill_devices()
        if status:
            state = {"running": _("Ativo"), "waiting_device": _("Desconectado"),
                     "no_permission": _("Sem permissão")}.get(status.get("state"), status.get("state"))
            self.device_row.set_subtitle(f"{state} — {status.get('device') or _('nenhum mouse')}")
        else:
            self.device_row.set_subtitle(_("Serviço parado"))
        self._update_banner()

    def _update_banner(self):
        status = self.client.status
        error = self.config_error or (status or {}).get("error", "")
        if status is None:
            title, button, self._banner_action = _("O serviço do mousemap não está rodando."), _("Iniciar"), "start"
        elif status.get("state") == "no_permission":
            title, button, self._banner_action = _("Sem permissão para acessar o mouse."), _("Configurar"), "setup"
        elif error:
            title, button, self._banner_action = _("Erro na configuração: {}").format(error), _("Restaurar padrões"), "reset"
        elif status.get("state") == "waiting_device":
            title, button, self._banner_action = _("Mouse desconectado. Ligue-o ou escolha outro."), "", None
        else:
            self.banner.set_revealed(False)
            return
        self.banner.set_title(GLib.markup_escape_text(title))
        self.banner.set_button_label(button or None)
        self.banner.set_revealed(True)

    def _on_banner_button(self, _banner):
        if self._banner_action == "start":
            result = systemctl("start", SERVICE)
            if not result or result.returncode != 0:
                self.toast(_("Não foi possível iniciar o serviço. Ele está instalado?"))
            GLib.timeout_add(800, lambda: self.client.refresh() or GLib.SOURCE_REMOVE)
        elif self._banner_action == "setup":
            self._run_setup()
        elif self._banner_action == "reset":
            self._on_reset()

    def _run_setup(self):
        script = setup_script()
        if not script:
            self.toast(_("Script de configuração não encontrado."))
            return
        try:
            proc = Gio.Subprocess.new(["pkexec", script], Gio.SubprocessFlags.NONE)
        except GLib.Error as err:
            self.toast(_("Não foi possível executar: {}").format(err.message))
            return
        proc.wait_check_async(None, self._on_setup_done)

    def _on_setup_done(self, proc, result):
        try:
            proc.wait_check_finish(result)
            self.toast(_("Permissões configuradas."))
        except GLib.Error:
            self.toast(_("A configuração de permissões foi cancelada ou falhou."))
        GLib.timeout_add(RETRY_MS, lambda: self.client.refresh() or GLib.SOURCE_REMOVE)

    # --- menu --------------------------------------------------------------------------------

    def _on_reset(self, *_args):
        dialog = Adw.AlertDialog(heading=_("Restaurar padrões?"),
                                 body=_("Todos os botões voltam ao comportamento original do mouse."))
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("reset", _("Restaurar"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_reset_response)
        dialog.present(self)

    def _on_reset_response(self, _dialog, response):
        if response != "reset":
            return
        self.config.buttons = {t: Action() for t in TRIGGERS}
        self._show_config()
        self._save(_("Padrões restaurados"))

    def _on_open_config(self, *_args):
        path = cfg.config_path()
        if not path.exists():
            self._save(_("Arquivo criado"))
        Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)

    def _on_about(self, *_args):
        Adw.AboutDialog(application_name="mousemap", application_icon=APP_ID, version=__version__,
                        comments=_("Escolha o que cada botão extra do mouse faz.")).present(self)

