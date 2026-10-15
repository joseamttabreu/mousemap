"""Catálogo de ações prontas (SPEC §6)."""

from .i18n import _

# id -> (nome na GUI, atalho equivalente)
PRESETS = {
    "workspace-prev": (_("Área de trabalho anterior"), "super+PAGEUP"),
    "workspace-next": (_("Área de trabalho seguinte"), "super+PAGEDOWN"),
    "overview": (_("Visão geral das atividades"), "super"),
    "back": (_("Voltar"), "alt+LEFT"),
    "forward": (_("Avançar"), "alt+RIGHT"),
    "copy": (_("Copiar"), "ctrl+c"),
    "paste": (_("Colar"), "ctrl+v"),
    "volume-up": (_("Aumentar volume"), "VOLUMEUP"),
    "volume-down": (_("Diminuir volume"), "VOLUMEDOWN"),
    "mute": (_("Silenciar"), "MUTE"),
    "play-pause": (_("Reproduzir/pausar"), "PLAYPAUSE"),
    "next-track": (_("Próxima faixa"), "NEXTSONG"),
    "prev-track": (_("Faixa anterior"), "PREVIOUSSONG"),
    "close-tab": (_("Fechar aba"), "ctrl+w"),
    "new-tab": (_("Nova aba"), "ctrl+t"),
    "screenshot": (_("Captura de tela"), "SYSRQ"),
}
