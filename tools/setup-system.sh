#!/bin/bash
# Preparação única do sistema (root): dependências + permissões.
# Uso: sudo bash tools/setup-system.sh
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

dnf install -y python3-evdev python3-gobject gtk4 libadwaita
bash "$repo/data/mousemap-setup"
echo
echo "Pronto. Agora, sem sudo: bash $repo/tools/install-dev.sh"
