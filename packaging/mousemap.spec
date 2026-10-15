Name:           mousemap
Version:        1.0.0
Release:        1%{?dist}
Summary:        Remap extra mouse buttons on Linux, with a GTK interface

License:        MIT
URL:            https://github.com/joseamttabreu/mousemap
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  meson
BuildRequires:  python3-devel
BuildRequires:  gettext
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  systemd-rpm-macros
# Testes de unidade
BuildRequires:  python3-evdev

Requires:       python3-evdev
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       polkit
Requires:       systemd-udev
Requires:       hicolor-icon-theme
# Perfis por aplicativo dependem da extensão do GNOME Shell
Recommends:     gnome-shell

%description
mousemap changes what the extra mouse buttons do (wheel tilt and side buttons)
into keyboard shortcuts, commands or other clicks. It works on GNOME with
Wayland: a user service captures the mouse through evdev and re-emits events
through uinput, and a GTK4/libadwaita app edits the configuration.

%prep
%autosetup

%build
%meson
%meson_build

%install
%meson_install
%find_lang %{name}

%check
%meson_test

%post
%systemd_user_post mousemapd.service
%udev_rules_update
# O gatilho de arquivos do systemd-udev só recarrega as regras no fim da transação;
# recarrega aqui para o trigger abaixo já aplicar o uaccess sem precisar de reboot.
modprobe uinput >/dev/null 2>&1 || :
udevadm control --reload-rules >/dev/null 2>&1 || :
udevadm trigger --subsystem-match=misc --sysname-match=uinput >/dev/null 2>&1 || :
udevadm trigger --subsystem-match=input --property-match=ID_INPUT_MOUSE=1 >/dev/null 2>&1 || :

%preun
%systemd_user_preun mousemapd.service

%postun
%udev_rules_update

%files -f %{name}.lang
%license LICENSE
%doc README.md SPEC.md BUGS.md
%{_bindir}/mousemap
%{_bindir}/mousemapd
%{_libexecdir}/mousemap-setup
%{python3_sitelib}/mousemap/
%{_userunitdir}/mousemapd.service
%{_datadir}/dbus-1/services/io.github.mousemap.Daemon.service
%{_datadir}/applications/io.github.mousemap.desktop
%{_metainfodir}/io.github.mousemap.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.mousemap.svg
%{_datadir}/polkit-1/actions/io.github.mousemap.policy
%{_udevrulesdir}/70-mousemap.rules
%{_modulesloaddir}/mousemap.conf
%{_datadir}/gnome-shell/extensions/mousemap@joseamttabreu.github.com/

%changelog
* Thu Oct 15 2026 joseamttabreu <jose@ouroborosbr.com> - 1.0.0-1
- Primeira versão estável

* Thu Oct 15 2026 joseamttabreu <jose@ouroborosbr.com> - 0.5.0-1
- Macros, rolagem, clique do meio e botões 6-8
- Vários mouses, com perfil por mouse

* Thu Oct 15 2026 joseamttabreu <jose@ouroborosbr.com> - 0.4.0-1
- Perfis por aplicativo com extensão do GNOME Shell
- mousemapd --diagnose

* Thu Oct 15 2026 joseamttabreu <jose@ouroborosbr.com> - 0.3.0-1
- Empacotamento RPM, tradução para inglês e ícone próprio
