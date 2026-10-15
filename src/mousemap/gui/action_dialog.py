"""Diálogo "Editar ação" (SPEC §7)."""

import shlex

from evdev import ecodes as e
from gi.repository import Adw, Gio, GLib, Gtk

from .. import keys
from ..i18n import _
from ..config import CLICKS, KIND_LABELS, KINDS, SCROLLS, TRIGGER_LABELS, Action
from ..presets import PRESETS

PRESET_IDS = list(PRESETS)
CLICK_IDS = list(CLICKS)
SCROLL_IDS = list(SCROLLS)
EMPTY_MESSAGES = {"keys": _("Grave ou digite um atalho"), "cmd": _("Digite um comando"),
                  "macro": _("Digite os passos ou grave um atalho")}
KEYS_TITLE = _("Atalho (ex.: ctrl+shift+t)")
MACRO_TITLE = _("Passos (ex.: ctrl+c, 100ms, ctrl+v)")


def sentence(text):
    return text[:1].upper() + text[1:]


class ActionDialog(Adw.Dialog):
    """Edita a ação de um gatilho. Com `inherited` (texto da ação global), é um perfil de aplicativo:
    ganha a opção "Igual ao padrão", e on_save recebe None quando ela é escolhida.
    """

    def __init__(self, trigger, action, on_save, inherited=None, subtitle=""):
        super().__init__(title=TRIGGER_LABELS[trigger], content_width=480)
        self.on_save = on_save
        self.inherited = inherited
        self.kinds = (("inherit",) if inherited is not None else ()) + KINDS
        self.capturing = False
        self._capture_row = None  # keys_row (substitui o texto) ou macro_row (acrescenta um passo)
        self._mods = []

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False,
                               title_widget=Adw.WindowTitle(title=TRIGGER_LABELS[trigger], subtitle=subtitle))
        cancel = Gtk.Button(label=_("Cancelar"))
        cancel.connect("clicked", lambda *_: self.close())
        self.save_button = Gtk.Button(label=_("Salvar"), css_classes=["suggested-action"])
        self.save_button.connect("clicked", self._on_save)
        header.pack_start(cancel)
        header.pack_end(self.save_button)

        group = Adw.PreferencesGroup()
        labels = [_("Igual ao padrão") if k == "inherit" else KIND_LABELS[k] for k in self.kinds]
        self.kind_row = Adw.ComboRow(title=_("Tipo de ação"), model=Gtk.StringList.new(labels))
        self.preset_row = Adw.ComboRow(title=_("Ação"),
                                       model=Gtk.StringList.new([PRESETS[p][0] for p in PRESET_IDS]))
        self.keys_row = Adw.EntryRow(title=KEYS_TITLE)
        self.capture_button = self._capture_toggle(self.keys_row, _("Gravar atalho pressionando as teclas"))
        self.macro_row = Adw.EntryRow(title=MACRO_TITLE)
        self.macro_capture_button = self._capture_toggle(self.macro_row, _("Gravar um passo pressionando o atalho"))
        self._capture_buttons = {self.keys_row: self.capture_button, self.macro_row: self.macro_capture_button}
        self.cmd_row = Adw.EntryRow(title=_("Comando"))
        pick = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=_("Escolher programa"), css_classes=["flat"])
        pick.connect("clicked", self._on_pick_program)
        self.cmd_row.add_suffix(pick)
        self.click_row = Adw.ComboRow(title=_("Clique"),
                                      model=Gtk.StringList.new([CLICKS[c][0] for c in CLICK_IDS]))
        self.scroll_row = Adw.ComboRow(title=_("Direção"),
                                       model=Gtk.StringList.new([SCROLLS[d][0] for d in SCROLL_IDS]))
        for row in (self.kind_row, self.preset_row, self.keys_row, self.macro_row, self.cmd_row,
                    self.click_row, self.scroll_row):
            group.add(row)

        preview_group = Adw.PreferencesGroup()
        self.preview_row = Adw.ActionRow(title=_("Resultado"), subtitle_selectable=True)
        preview_group.add(self.preview_row)

        # Caixa simples (não rolável) para o diálogo ter a altura do conteúdo.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=12, margin_bottom=24, margin_start=12, margin_end=12)
        box.append(group)
        box.append(preview_group)
        view = Adw.ToolbarView(content=Adw.Clamp(child=box))
        view.add_top_bar(header)
        self.set_child(view)

        keyctl = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keyctl.connect("key-pressed", self._on_key_pressed)
        keyctl.connect("key-released", self._on_key_released)
        self.add_controller(keyctl)

        self._fill(action)
        for row in (self.kind_row, self.preset_row, self.click_row, self.scroll_row):
            row.connect("notify::selected", lambda *_: self._update())
        for row in (self.keys_row, self.macro_row, self.cmd_row):
            row.connect("changed", lambda *_: self._update())
        self.connect("closed", lambda *_: self._stop_capture())
        self._update()

    def _fill(self, action):
        if action is None:  # perfil herdando o padrão
            self.kind_row.set_selected(0)
            return
        self.kind_row.set_selected(self.kinds.index(action.kind))
        if action.kind == "preset" and action.value in PRESETS:
            self.preset_row.set_selected(PRESET_IDS.index(action.value))
        if action.kind == "keys":
            self.keys_row.set_text(action.value)
        if action.kind == "cmd":
            self.cmd_row.set_text(action.value)
        if action.kind == "click" and action.value in CLICKS:
            self.click_row.set_selected(CLICK_IDS.index(action.value))
        if action.kind == "macro":
            self.macro_row.set_text(action.value)
        if action.kind == "scroll" and action.value in SCROLLS:
            self.scroll_row.set_selected(SCROLL_IDS.index(action.value))

    def current_kind(self):
        return self.kinds[self.kind_row.get_selected()]

    def current_action(self):
        """Action válida ou levanta ValueError com a mensagem para o usuário."""
        kind = self.current_kind()
        if kind == "inherit":
            return None
        if kind in ("default", "none"):
            return Action(kind)
        value = {
            "preset": lambda: PRESET_IDS[self.preset_row.get_selected()],
            "keys": lambda: self.keys_row.get_text(),
            "cmd": lambda: self.cmd_row.get_text(),
            "click": lambda: CLICK_IDS[self.click_row.get_selected()],
            "macro": lambda: self.macro_row.get_text(),
            "scroll": lambda: SCROLL_IDS[self.scroll_row.get_selected()],
        }[kind]()
        if not value.strip():
            raise ValueError(EMPTY_MESSAGES[kind])
        return Action.parse({kind: value})

    def _update(self):
        kind = self.current_kind()
        self.preset_row.set_visible(kind == "preset")
        self.keys_row.set_visible(kind == "keys")
        self.cmd_row.set_visible(kind == "cmd")
        self.click_row.set_visible(kind == "click")
        self.macro_row.set_visible(kind == "macro")
        self.scroll_row.set_visible(kind == "scroll")
        try:
            action = self.current_action()
        except ValueError as err:
            self.preview_row.set_subtitle(sentence(str(err)))
            self.preview_row.add_css_class("error")
            self.save_button.set_sensitive(False)
            return
        self.preview_row.remove_css_class("error")
        self.preview_row.set_subtitle(action.describe() if action else _("Igual ao padrão: {}").format(self.inherited))
        self.save_button.set_sensitive(True)

    def _on_save(self, _button):
        try:
            action = self.current_action()
        except ValueError:
            return
        self.on_save(action)
        self.close()

    # --- escolher programa -----------------------------------------------------------------

    def _on_pick_program(self, _button):
        dialog = Gtk.FileDialog(title=_("Escolher programa"), initial_folder=Gio.File.new_for_path("/usr/bin"))
        dialog.open(self.get_root(), None, self._on_program_picked)

    def _on_program_picked(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file and file.get_path():
            self.cmd_row.set_text(shlex.quote(file.get_path()))

    # --- captura de atalho -----------------------------------------------------------------

    def _capture_toggle(self, row, tooltip):
        button = Gtk.ToggleButton(icon_name="input-keyboard-symbolic", valign=Gtk.Align.CENTER,
                                  tooltip_text=tooltip, css_classes=["flat"])
        button.connect("toggled", self._on_capture_toggled, row)
        row.add_suffix(button)
        return button

    def _on_capture_toggled(self, button, row):
        if button.get_active():
            if self.capturing:  # trocou de campo no meio de uma gravação
                self._stop_capture()
            self.capturing = True
            self._capture_row = row
            self._mods = []
            row.set_title(_("Pressione as teclas… (Esc cancela)"))
            self._inhibit(True)
        elif row is self._capture_row:
            self._stop_capture()

    def _stop_capture(self):
        if not self.capturing:
            return
        self.capturing = False
        row, self._capture_row = self._capture_row, None
        row.set_title(KEYS_TITLE if row is self.keys_row else MACRO_TITLE)
        self._inhibit(False)
        self._capture_buttons[row].set_active(False)

    def _inhibit(self, enable):
        """Pede ao compositor que não trate Super+… enquanto gravamos o atalho."""
        native = self.get_native()
        surface = native.get_surface() if native else None
        try:
            if enable:
                surface.inhibit_system_shortcuts(None)
            else:
                surface.restore_system_shortcuts()
        except (AttributeError, TypeError):
            pass

    def _finish(self, codes):
        combo = keys.format_combo(codes)
        if self._capture_row is self.macro_row:
            current = self.macro_row.get_text().strip().rstrip(",")
            self.macro_row.set_text(f"{current}, {combo}" if current else combo)
        else:
            self.keys_row.set_text(combo)
        self._stop_capture()

    def _on_key_pressed(self, _ctl, _keyval, keycode, _state):
        if not self.capturing:
            return False
        code = keycode - 8  # código de hardware do GDK = código evdev + 8
        if keys.is_modifier(code):
            if code not in self._mods:
                self._mods.append(code)
            return True
        if not self._mods and code == e.KEY_ESC:
            self._stop_capture()
        elif not self._mods and code == e.KEY_BACKSPACE:
            if self._capture_row is self.keys_row:
                self.keys_row.set_text("")
            self._stop_capture()
        elif code in keys.KEYBOARD_KEYS:
            self._finish([*self._mods, code])
        return True

    def _on_key_released(self, _ctl, _keyval, keycode, _state):
        # Só modificadores, soltos sem outra tecla: atalho como "super" (visão geral).
        if self.capturing and keys.is_modifier(keycode - 8) and self._mods:
            self._finish(self._mods)
