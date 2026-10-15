"""Configuração: esquema v2 (SPEC §6, §14, §15), leitura do formato v1 do protótipo e gravação atômica."""

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from evdev import ecodes as e

from . import keys
from .i18n import _
from .presets import PRESETS

VERSION = 2

PRIMARY_TRIGGERS = ("tilt_left", "tilt_right", "side_back", "side_forward", "middle")
EXTRA_TRIGGERS = ("btn_forward", "btn_back", "btn_task")  # só existem em alguns mouses
TRIGGERS = PRIMARY_TRIGGERS + EXTRA_TRIGGERS
TRIGGER_LABELS = {
    "tilt_left": _("Roda para a esquerda"),
    "tilt_right": _("Roda para a direita"),
    "side_back": _("Lateral de trás"),
    "side_forward": _("Lateral da frente"),
    "middle": _("Clique do meio"),
    "btn_forward": _("Botão extra 6"),
    "btn_back": _("Botão extra 7"),
    "btn_task": _("Botão extra 8"),
}

CLICKS = {
    "left": (_("Clique esquerdo"), e.BTN_LEFT),
    "right": (_("Clique direito"), e.BTN_RIGHT),
    "middle": (_("Clique do meio"), e.BTN_MIDDLE),
    "back": (_("Botão voltar"), e.BTN_SIDE),
    "forward": (_("Botão avançar"), e.BTN_EXTRA),
}

SCROLLS = {
    "up": (_("Rolar para cima"), e.REL_WHEEL, 1),
    "down": (_("Rolar para baixo"), e.REL_WHEEL, -1),
    "left": (_("Rolar para a esquerda"), e.REL_HWHEEL, -1),
    "right": (_("Rolar para a direita"), e.REL_HWHEEL, 1),
}

KINDS = ("default", "none", "preset", "keys", "macro", "cmd", "click", "scroll")
KIND_LABELS = {
    "default": _("Padrão"),
    "none": _("Desativado"),
    "preset": _("Ação pronta"),
    "keys": _("Atalho de teclado"),
    "macro": _("Macro"),
    "cmd": _("Comando"),
    "click": _("Outro clique"),
    "scroll": _("Rolagem"),
}

COOLDOWN_RANGE = (100, 2000)
DEFAULT_COOLDOWN = 350

MACRO_MAX_STEPS = 20
MACRO_DELAY_RANGE = (10, 5000)   # ms por pausa
MACRO_MAX_TOTAL_DELAY = 10000    # ms somando as pausas
_DELAY = re.compile(r"^(\d+)\s*ms$", re.IGNORECASE)


class ConfigError(Exception):
    pass


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "mousemap" / "config.toml"


def parse_macro(text):
    """'ctrl+c, 100ms, ctrl+v' -> (('keys', códigos), ('delay', ms), ...). Levanta ValueError."""
    steps = []
    for raw in text.split(","):
        part = raw.strip()
        if not part:
            raise ValueError(_("macro com passo vazio"))
        match = _DELAY.match(part)
        if match:
            ms = int(match.group(1))
            lo, hi = MACRO_DELAY_RANGE
            if not lo <= ms <= hi:
                raise ValueError(_("pausa de macro deve ficar entre {} e {} ms").format(lo, hi))
            steps.append(("delay", ms))
        else:
            steps.append(("keys", keys.parse_combo(part)))
    if len(steps) > MACRO_MAX_STEPS:
        raise ValueError(_("macro com mais de {} passos").format(MACRO_MAX_STEPS))
    if not any(kind == "keys" for kind, _value in steps):
        raise ValueError(_("macro precisa de ao menos um atalho"))
    if sum(v for k, v in steps if k == "delay") > MACRO_MAX_TOTAL_DELAY:
        raise ValueError(_("macro com mais de {} ms de pausa no total").format(MACRO_MAX_TOTAL_DELAY))
    return tuple(steps)


def format_macro(steps):
    return ", ".join(f"{v}ms" if k == "delay" else keys.format_combo(v) for k, v in steps)


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
        if kind not in KINDS or kind in ("default", "none"):
            raise ValueError(_("tipo de ação desconhecido: {}").format(repr(kind)))
        if not isinstance(value, str) or not value.strip():
            raise ValueError(_("{} precisa de um texto não vazio").format(kind))
        action = cls(kind, value.strip())
        action.compile()  # valida
        if kind == "keys":  # normaliza a grafia
            action = cls("keys", keys.format_combo(keys.parse_combo(value)))
        elif kind == "macro":
            action = cls("macro", format_macro(parse_macro(value)))
        return action

    def compile(self):
        """Forma executável: ('default'|'none', None), ('keys', códigos), ('macro', passos),
        ('cmd', texto), ('click', código), ('scroll', (eixo, sentido))."""
        if self.kind in ("default", "none"):
            return self.kind, None
        if self.kind == "preset":
            if self.value not in PRESETS:
                raise ValueError(_("ação pronta desconhecida: {}").format(repr(self.value)))
            return "keys", keys.parse_combo(PRESETS[self.value][1])
        if self.kind == "keys":
            return "keys", keys.parse_combo(self.value)
        if self.kind == "macro":
            return "macro", parse_macro(self.value)
        if self.kind == "cmd":
            return "cmd", self.value
        if self.kind == "click":
            if self.value not in CLICKS:
                raise ValueError(_("clique deve ser um de: {}").format(", ".join(CLICKS)))
            return "click", CLICKS[self.value][1]
        if self.kind == "scroll":
            if self.value not in SCROLLS:
                raise ValueError(_("rolagem deve ser uma de: {}").format(", ".join(SCROLLS)))
            return "scroll", SCROLLS[self.value][1:]
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
        if self.kind == "macro":
            parts = [_("{} ms").format(v) if k == "delay" else keys.label(v) for k, v in parse_macro(self.value)]
            return _("Macro: {}").format(" → ".join(parts))
        if self.kind == "cmd":
            return _("Comando: {}").format(self.value)
        if self.kind == "click":
            return CLICKS.get(self.value, (self.value,))[0]
        if self.kind == "scroll":
            return SCROLLS.get(self.value, (self.value,))[0]
        return self.value


@dataclass
class Profile:
    """Sobrescritas de um aplicativo ou de um mouse: só os gatilhos que mudam; o resto herda."""
    name: str = ""
    buttons: dict = field(default_factory=dict)


AppProfile = Profile


@dataclass
class Config:
    devices: list = field(default_factory=list)  # nomes dos mouses capturados; vazio = automático
    tilt_cooldown_ms: int = DEFAULT_COOLDOWN
    buttons: dict = field(default_factory=lambda: {t: Action() for t in TRIGGERS})
    mice: dict = field(default_factory=dict)  # nome do mouse -> Profile
    apps: dict = field(default_factory=dict)  # id do aplicativo -> Profile
    warnings: list = field(default_factory=list, compare=False)

    def actions_for(self, app="", mouse=""):
        """Ações efetivas: [buttons] ⊕ [mice.<mouse>] ⊕ [apps.<app>] (SPEC §15, RF-64)."""
        merged = dict(self.buttons)
        for table, key in ((self.mice, mouse), (self.apps, app)):
            if key in table:
                merged.update(table[key].buttons)
        return merged


def find_profile(config, app_id="", wm_class=""):
    """Chave do perfil para o aplicativo em foco: pelo id e, se não houver, pela classe da janela."""
    by_lower = {key.lower(): key for key in config.apps}
    for candidate in (app_id, wm_class):
        if candidate and candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return ""


def _parse_profiles(data, table_name, warnings):
    profiles = {}
    table = data.get(table_name, {})
    if not isinstance(table, dict):
        raise ConfigError(_("[{}] deve ser uma tabela").format(table_name))
    for key, entry in table.items():
        if not key.strip():
            raise ConfigError(_("[{}] tem uma entrada com nome vazio").format(table_name))
        where = f"{table_name}.{key}"
        if not isinstance(entry, dict):
            raise ConfigError(_("{}: deve ser uma tabela").format(where))
        name = entry.get("name", "")
        if not isinstance(name, str):
            raise ConfigError(_("{}.name deve ser texto").format(where))
        profile = Profile(name=name)
        for trigger, spec in entry.items():
            if trigger == "name":
                continue
            if trigger not in TRIGGERS:
                warnings.append(_("botão desconhecido ignorado: {}").format(f"{where}.{trigger}"))
                continue
            try:
                profile.buttons[trigger] = Action.parse(spec)
            except ValueError as err:
                raise ConfigError(f"{where}.{trigger}: {err}") from None
        profiles[key] = profile
    return profiles


def _parse_devices(settings):
    if "devices" in settings:
        devices = settings["devices"]
        if not isinstance(devices, list) or not all(isinstance(d, str) and d.strip() for d in devices):
            raise ConfigError(_("settings.devices deve ser uma lista de nomes"))
        return list(dict.fromkeys(devices))
    device = settings.get("device", "")  # formato até a 0.4
    if not isinstance(device, str):
        raise ConfigError(_("settings.device deve ser texto"))
    return [device] if device else []


def parse(data):
    """dict do TOML (v1 ou v2) -> Config."""
    version = data.get("version", 1)
    if version == 1:
        source, known = data, {"settings", "tilt_left", "tilt_right", "side_back", "side_forward"}
    elif version == VERSION:
        source, known = data.get("buttons", {}), {"version", "settings", "buttons", "apps", "mice"}
        if not isinstance(source, dict):
            raise ConfigError(_("[buttons] deve ser uma tabela"))
    else:
        raise ConfigError(_("versão de configuração não suportada: {}").format(repr(version)))

    config = Config()
    config.warnings += [_("chave desconhecida ignorada: {}").format(k) for k in data if k not in known]
    if version == VERSION:
        config.warnings += [_("botão desconhecido ignorado: {}").format(k) for k in source if k not in TRIGGERS]

    for trigger in TRIGGERS:
        if version == 1 and trigger not in known:
            continue
        try:
            config.buttons[trigger] = Action.parse(source.get(trigger, "default"))
        except ValueError as err:
            raise ConfigError(f"{trigger}: {err}") from None

    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigError(_("[settings] deve ser uma tabela"))
    cooldown = settings.get("tilt_cooldown_ms", DEFAULT_COOLDOWN)
    lo, hi = COOLDOWN_RANGE
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or not lo <= cooldown <= hi:
        raise ConfigError(_("settings.tilt_cooldown_ms deve ser um inteiro entre {} e {}").format(lo, hi))
    config.devices, config.tilt_cooldown_ms = _parse_devices(settings), cooldown
    if version == VERSION:
        config.mice = _parse_profiles(data, "mice", config.warnings)
        config.apps = _parse_profiles(data, "apps", config.warnings)
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


def _dump_profiles(table_name, profiles):
    lines = []
    for key, profile in profiles.items():
        lines += ["", f"[{table_name}.{json.dumps(key, ensure_ascii=False)}]"]
        if profile.name:
            lines.append(f"name = {json.dumps(profile.name, ensure_ascii=False)}")
        lines += [f"{t} = {profile.buttons[t].to_toml()}" for t in TRIGGERS if t in profile.buttons]
    return lines


def dumps(config):
    lines = [
        "# Configuração do mousemap. Pode ser editada aqui ou pelo app \"mousemap\".",
        "# Ações: \"default\", \"none\", { preset = \"...\" }, { keys = \"ctrl+c\" },",
        "#        { macro = \"ctrl+c, 100ms, ctrl+v\" }, { cmd = \"comando\" },",
        "#        { click = \"middle\" }, { scroll = \"up\" }",
        f"version = {VERSION}",
        "",
        "[settings]",
        f"devices = {json.dumps(config.devices, ensure_ascii=False)}",
        f"tilt_cooldown_ms = {config.tilt_cooldown_ms}",
        "",
        "[buttons]",
    ]
    # Gatilhos extras só aparecem quando configurados (RF-62).
    lines += [f"{t} = {config.buttons[t].to_toml()}" for t in TRIGGERS
              if t in PRIMARY_TRIGGERS or config.buttons[t] != Action()]
    lines += _dump_profiles("mice", config.mice)
    lines += _dump_profiles("apps", config.apps)
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
