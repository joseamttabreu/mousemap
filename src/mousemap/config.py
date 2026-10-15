"""Configuração: esquema v2 (SPEC §6), leitura do formato v1 do protótipo e gravação atômica."""

import json
import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from evdev import ecodes as e

from . import keys
from .i18n import _
from .presets import PRESETS

VERSION = 2

TRIGGERS = ("tilt_left", "tilt_right", "side_back", "side_forward")
TRIGGER_LABELS = {
    "tilt_left": _("Roda para a esquerda"),
    "tilt_right": _("Roda para a direita"),
    "side_back": _("Lateral de trás"),
    "side_forward": _("Lateral da frente"),
}

CLICKS = {
    "left": (_("Clique esquerdo"), e.BTN_LEFT),
    "right": (_("Clique direito"), e.BTN_RIGHT),
    "middle": (_("Clique do meio"), e.BTN_MIDDLE),
    "back": (_("Botão voltar"), e.BTN_SIDE),
    "forward": (_("Botão avançar"), e.BTN_EXTRA),
}

KINDS = ("default", "none", "preset", "keys", "cmd", "click")
KIND_LABELS = {
    "default": _("Padrão"),
    "none": _("Desativado"),
    "preset": _("Ação pronta"),
    "keys": _("Atalho de teclado"),
    "cmd": _("Comando"),
    "click": _("Outro clique"),
}

COOLDOWN_RANGE = (100, 2000)
DEFAULT_COOLDOWN = 350


class ConfigError(Exception):
    pass


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "mousemap" / "config.toml"


@dataclass(frozen=True)
class Action:
    kind: str = "default"
    value: str = ""

    @classmethod
    def parse(cls, spec):
        """Valor do TOML -> Action. Levanta ValueError com mensagem legível."""
        if spec in ("default", "none"):
            return cls(spec)
        if not (isinstance(spec, dict) and len(spec) == 1):
            raise ValueError(_('use "default", "none" ou uma tabela como { keys = "ctrl+c" }'))
        kind, value = next(iter(spec.items()))
        if kind not in ("preset", "keys", "cmd", "click"):
            raise ValueError(_("tipo de ação desconhecido: {}").format(repr(kind)))
        if not isinstance(value, str) or not value.strip():
            raise ValueError(_("{} precisa de um texto não vazio").format(kind))
        action = cls(kind, value.strip())
        action.compile()  # valida
        if kind == "keys":  # normaliza a grafia
            action = cls("keys", keys.format_combo(keys.parse_combo(value)))
        return action

    def compile(self):
        """Forma executável: ('default'|'none', None), ('keys', códigos), ('cmd', texto), ('click', código)."""
        if self.kind in ("default", "none"):
            return self.kind, None
        if self.kind == "preset":
            if self.value not in PRESETS:
                raise ValueError(_("ação pronta desconhecida: {}").format(repr(self.value)))
            return "keys", keys.parse_combo(PRESETS[self.value][1])
        if self.kind == "keys":
            return "keys", keys.parse_combo(self.value)
        if self.kind == "cmd":
            return "cmd", self.value
        if self.kind == "click":
            if self.value not in CLICKS:
                raise ValueError(_("clique deve ser um de: {}").format(", ".join(CLICKS)))
            return "click", CLICKS[self.value][1]
        raise ValueError(_("tipo de ação desconhecido: {}").format(repr(self.kind)))

    def to_toml(self):
        if self.kind in ("default", "none"):
            return json.dumps(self.kind)
        return f"{{ {self.kind} = {json.dumps(self.value, ensure_ascii=False)} }}"

    def describe(self):
        if self.kind == "default":
            return _("Padrão")
        if self.kind == "none":
            return _("Desativado")
        if self.kind == "preset":
            return PRESETS.get(self.value, (self.value,))[0]
        if self.kind == "keys":
            return keys.label(keys.parse_combo(self.value))
        if self.kind == "cmd":
            return _("Comando: {}").format(self.value)
        if self.kind == "click":
            return CLICKS.get(self.value, (self.value,))[0]
        return self.value


@dataclass
class Config:
    device: str = ""
    tilt_cooldown_ms: int = DEFAULT_COOLDOWN
    buttons: dict = field(default_factory=lambda: {t: Action() for t in TRIGGERS})
    warnings: list = field(default_factory=list, compare=False)


def parse(data):
    """dict do TOML (v1 ou v2) -> Config."""
    version = data.get("version", 1)
    if version == 1:
        source, known = data, {"settings", *TRIGGERS}
    elif version == VERSION:
        source, known = data.get("buttons", {}), {"version", "settings", "buttons"}
        if not isinstance(source, dict):
            raise ConfigError(_("[buttons] deve ser uma tabela"))
    else:
        raise ConfigError(_("versão de configuração não suportada: {}").format(repr(version)))

    config = Config()
    config.warnings += [_("chave desconhecida ignorada: {}").format(k) for k in data if k not in known]
    if version == VERSION:
        config.warnings += [_("botão desconhecido ignorado: {}").format(k) for k in source if k not in TRIGGERS]

    for trigger in TRIGGERS:
        try:
            config.buttons[trigger] = Action.parse(source.get(trigger, "default"))
        except ValueError as err:
            raise ConfigError(f"{trigger}: {err}") from None

    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigError(_("[settings] deve ser uma tabela"))
    device = settings.get("device", "")
    if not isinstance(device, str):
        raise ConfigError(_("settings.device deve ser texto"))
    cooldown = settings.get("tilt_cooldown_ms", DEFAULT_COOLDOWN)
    lo, hi = COOLDOWN_RANGE
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or not lo <= cooldown <= hi:
        raise ConfigError(_("settings.tilt_cooldown_ms deve ser um inteiro entre {} e {}").format(lo, hi))
    config.device, config.tilt_cooldown_ms = device, cooldown
    return config


def load(path=None):
    """Lê a configuração; arquivo ausente = padrões. Levanta ConfigError."""
    path = Path(path or config_path())
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(_("TOML inválido: {}").format(err)) from None
    except OSError as err:
        raise ConfigError(str(err)) from None
    return parse(data)


def dumps(config):
    lines = [
        "# Configuração do mousemap. Pode ser editada aqui ou pelo app \"mousemap\".",
        "# Ações: \"default\", \"none\", { preset = \"...\" }, { keys = \"ctrl+c\" },",
        "#        { cmd = \"comando\" }, { click = \"middle\" }",
        f"version = {VERSION}",
        "",
        "[settings]",
        f"device = {json.dumps(config.device, ensure_ascii=False)}",
        f"tilt_cooldown_ms = {config.tilt_cooldown_ms}",
        "",
        "[buttons]",
    ]
    lines += [f"{t} = {config.buttons[t].to_toml()}" for t in TRIGGERS]
    return "\n".join(lines) + "\n"


def save(config, path=None):
    """Grava de forma atômica (temporário + rename)."""
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dumps(config))
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
