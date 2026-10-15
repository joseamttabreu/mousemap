#!/bin/bash
# Instala o mousemap para o usuário atual apontando para este repositório (sem root).
# Desinstalar: bash tools/install-dev.sh --uninstall
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
bindir="$HOME/.local/bin"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
share="${XDG_DATA_HOME:-$HOME/.local/share}"
dbus_dir="$share/dbus-1/services"
apps="$share/applications"
icons="$share/icons/hicolor/scalable/apps"
uuid="mousemap@joseamttabreu.github.com"
ext_dir="$share/gnome-shell/extensions/$uuid"

if [ "${1:-}" = "--uninstall" ]; then
    systemctl --user disable --now mousemapd.service 2>/dev/null || true
    rm -f "$bindir/mousemap" "$bindir/mousemapd" "$units/mousemapd.service" \
          "$dbus_dir/io.github.mousemap.Daemon.service" "$apps/io.github.mousemap.desktop" \
          "$icons/io.github.mousemap.svg"
    rm -rf "$ext_dir"
    systemctl --user daemon-reload
    echo "mousemap removido (a configuração em ~/.config/mousemap foi mantida)."
    exit 0
fi

# O protótipo antigo (mousemap.service) captura o mesmo mouse; desliga se existir.
if systemctl --user cat mousemap.service >/dev/null 2>&1; then
    systemctl --user disable --now mousemap.service || true
fi

mkdir -p "$bindir" "$units" "$dbus_dir" "$apps" "$icons"
chmod +x "$repo/bin/mousemap" "$repo/bin/mousemapd" "$repo/data/mousemap-setup"
ln -sf "$repo/bin/mousemap" "$bindir/mousemap"
ln -sf "$repo/bin/mousemapd" "$bindir/mousemapd"
cp "$repo/data/io.github.mousemap.svg" "$icons/"
version="$(awk -F"'" '/^  version:/ {print $2; exit}' "$repo/meson.build")"
mkdir -p "$ext_dir"
cp "$repo/extension/extension.js" "$repo/extension/focus.js" "$ext_dir/"
sed "s#@VERSION@#$version#" "$repo/extension/metadata.json.in" > "$ext_dir/metadata.json"
for pair in "mousemapd.service:$units" "io.github.mousemap.Daemon.service:$dbus_dir" \
            "io.github.mousemap.desktop:$apps"; do
    name="${pair%%:*}" dest="${pair#*:}"
    sed "s#@BINDIR@#$bindir#g" "$repo/data/$name.in" > "$dest/$name"
done

systemctl --user daemon-reload
systemctl --user enable mousemapd.service
systemctl --user restart mousemapd.service
sleep 1
systemctl --user --no-pager status mousemapd.service | head -n 12
echo
echo "Abra \"mousemap\" no menu de aplicativos ou rode: mousemap"
if gnome-extensions info "$uuid" >/dev/null 2>&1; then
    gnome-extensions enable "$uuid" && echo "Extensão do GNOME ativada (perfis por aplicativo)."
else
    echo "Perfis por aplicativo: saia e entre na sessão para o GNOME carregar a extensão; depois ative-a no mousemap."
fi
