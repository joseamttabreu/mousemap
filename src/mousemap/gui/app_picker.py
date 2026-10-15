"""Diálogo "Adicionar aplicativo": escolhe um app instalado ou recebe um id digitado (SPEC §14)."""

from gi.repository import Adw, Gio, Gtk

from ..i18n import _


def installed_apps():
    """[(id sem .desktop, nome, ícone)] dos aplicativos visíveis no menu, por nome."""
    apps = []
    for info in Gio.AppInfo.get_all():
        if info.should_show() and info.get_id():
            apps.append((info.get_id().removesuffix(".desktop"), info.get_name(), info.get_icon()))
    return sorted(apps, key=lambda a: a[1].casefold())


def app_name(app_id):
    """Nome amigável de um id de aplicativo ("" se não houver .desktop)."""
    try:
        info = Gio.DesktopAppInfo.new(f"{app_id}.desktop")
    except TypeError:
        return ""
    return info.get_name() if info else ""


class AppPickerDialog(Adw.Dialog):
    def __init__(self, exclude, on_pick):
        super().__init__(title=_("Adicionar aplicativo"), content_width=460, content_height=600)
        self.on_pick = on_pick
        exclude = {e.casefold() for e in exclude}

        self.search = Gtk.SearchEntry(placeholder_text=_("Buscar aplicativo"))
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.list.set_filter_func(self._filter)
        for app_id, name, icon in installed_apps():
            if app_id.casefold() in exclude:
                continue
            row = Adw.ActionRow(title=name, subtitle=app_id, activatable=True, use_markup=False)
            image = Gtk.Image(pixel_size=32)
            if icon:
                image.set_from_gicon(icon)
            else:
                image.set_from_icon_name("application-x-executable")
            row.add_prefix(image)
            row.connect("activated", lambda _row, i=app_id, n=name: self._pick(i, n))
            self.list.append(row)

        manual = Adw.PreferencesGroup(
            title=_("Outro"),
            description=_("Id do aplicativo ou classe da janela, para apps que não aparecem na lista."))
        self.manual_row = Adw.EntryRow(title=_("Id ou classe da janela"), show_apply_button=True)
        self.manual_row.connect("apply", self._on_manual)
        manual.add(self.manual_row)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=12, margin_bottom=24, margin_start=12, margin_end=12)
        box.append(self.search)
        box.append(self.list)
        box.append(manual)
        scroller = Gtk.ScrolledWindow(child=Adw.Clamp(child=box), vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        view = Adw.ToolbarView(content=scroller)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.set_focus(self.search)

    def _filter(self, row):
        text = self.search.get_text().casefold().strip()
        return not text or text in row.get_title().casefold() or text in row.get_subtitle().casefold()

    def _on_manual(self, row):
        text = row.get_text().strip().removesuffix(".desktop")
        if text:
            self._pick(text, app_name(text))

    def _pick(self, app_id, name):
        self.on_pick(app_id, name)
        self.close()
