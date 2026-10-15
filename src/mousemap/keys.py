"""Nomes de teclas: texto da configuração <-> códigos evdev <-> rótulos da GUI."""

from evdev import ecodes as e

from .i18n import _

MAX_KEYS = 5

# Nome canônico -> código. Os lados direitos são normalizados para o esquerdo, exceto AltGr.
MODIFIERS = {
    "ctrl": e.KEY_LEFTCTRL,
    "alt": e.KEY_LEFTALT,
    "altgr": e.KEY_RIGHTALT,
    "shift": e.KEY_LEFTSHIFT,
    "super": e.KEY_LEFTMETA,
}
_MODIFIER_ALIASES = {"control": "ctrl", "meta": "super", "win": "super"}
_MODIFIER_BY_CODE = {
    **{code: name for name, code in MODIFIERS.items()},
    e.KEY_RIGHTCTRL: "ctrl",
    e.KEY_RIGHTSHIFT: "shift",
    e.KEY_RIGHTMETA: "super",
}

_LABELS = {
    "ctrl": "Ctrl", "alt": "Alt", "altgr": "AltGr", "shift": "Shift", "super": "Super",
    "PAGEUP": "Page Up", "PAGEDOWN": "Page Down", "LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓",
    "ESC": "Esc", "ENTER": "Enter", "SPACE": _("Espaço"), "BACKSPACE": "Backspace", "DELETE": "Delete",
    "TAB": "Tab", "HOME": "Home", "END": "End", "INSERT": "Insert", "SYSRQ": "Print",
    "VOLUMEUP": "Volume +", "VOLUMEDOWN": "Volume −", "MUTE": _("Mudo"),
    "PLAYPAUSE": _("Reproduzir/Pausar"), "NEXTSONG": _("Próxima faixa"), "PREVIOUSSONG": _("Faixa anterior"),
}

# Teclas que o teclado virtual pode emitir: teclado comum + teclas multimídia (sem a faixa BTN_*).
KEYBOARD_KEYS = sorted(c for c in e.KEY if isinstance(c, int) and (1 <= c < 0x100 or 0x160 <= c <= 0x2FF))


def is_modifier(code):
    return code in _MODIFIER_BY_CODE


def key_code(name):
    """'Page_Up', 'pageup', 'F5', 'ctrl', 'Print'... -> código evdev."""
    word = name.strip()
    lower = _MODIFIER_ALIASES.get(word.lower(), word.lower())
    if lower in MODIFIERS:
        return MODIFIERS[lower]
    if lower == "print":
        return e.KEY_SYSRQ
    for candidate in (word.upper(), word.upper().replace("_", "")):
        code = getattr(e, "KEY_" + candidate, None)
        if isinstance(code, int) and code in KEYBOARD_KEYS:
            return code
    raise ValueError(_("tecla desconhecida: {}").format(repr(word)))


def key_name(code):
    """Código evdev -> nome canônico usado na configuração."""
    if code in _MODIFIER_BY_CODE:
        return _MODIFIER_BY_CODE[code]
    names = e.KEY.get(code)
    if names is None:
        raise ValueError(_("código de tecla desconhecido: {}").format(code))
    name = (names if isinstance(names, str) else names[0]).removeprefix("KEY_")
    return name.lower() if len(name) == 1 else name


def parse_combo(text):
    """'ctrl+shift+t' -> (KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_T). Levanta ValueError se inválido."""
    parts = [p for p in (s.strip() for s in text.split("+")) if p]
    if not parts:
        raise ValueError(_("atalho vazio"))
    codes = []
    for part in parts:
        code = key_code(part)
        if code not in codes:
            codes.append(code)
    if len(codes) > MAX_KEYS:
        raise ValueError(_("atalho com mais de {} teclas").format(MAX_KEYS))
    return tuple(codes)


def format_combo(codes):
    """Códigos -> texto canônico da configuração, modificadores primeiro."""
    mods = [c for c in codes if is_modifier(c)]
    others = [c for c in codes if not is_modifier(c)]
    return "+".join(key_name(c) for c in mods + others)


def label(codes):
    """Códigos -> texto para a GUI, ex.: 'Ctrl + Shift + T'."""
    words = []
    for name in format_combo(codes).split("+"):
        words.append(_LABELS.get(name, name.upper() if len(name) == 1 else name.title()))
    return " + ".join(words)
