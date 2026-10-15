"""Descoberta de mouses pelo sysfs (não exige permissão) e abertura do escolhido."""

import os
from dataclasses import dataclass
from pathlib import Path

from evdev import ecodes as e

VIRTUAL_PREFIX = "mousemap"  # nossos próprios dispositivos virtuais nunca são candidatos
SYS_INPUT = Path("/sys/class/input")
BUSES = {0x03: "usb", 0x05: "bluetooth", 0x11: "ps2", 0x18: "i2c", 0x19: "host"}


@dataclass(frozen=True)
class MouseInfo:
    name: str
    path: str
    bus: str
    triggers: tuple

    @property
    def accessible(self):
        return os.access(self.path, os.R_OK)


def _bitmap(text):
    """Bitmap de capacidades do sysfs ('ffff0000 0 0 0 0', palavra mais significativa primeiro) -> int."""
    value = 0
    for word in text.split():
        value = (value << 64) | int(word, 16)
    return value


def _has(bits, code):
    return bool(bits >> code & 1)


def read_mouse(node, sys_root=SYS_INPUT):
    """Lê /sys/class/input/<node>; retorna MouseInfo se for um mouse, senão None."""
    dev = sys_root / node / "device"
    try:
        name = (dev / "name").read_text().strip()
        key_bits = _bitmap((dev / "capabilities" / "key").read_text())
        rel_bits = _bitmap((dev / "capabilities" / "rel").read_text())
        bus = int((dev / "id" / "bustype").read_text(), 16)
    except (OSError, ValueError):
        return None
    if name.startswith(VIRTUAL_PREFIX):
        return None
    if not (_has(key_bits, e.BTN_LEFT) and _has(rel_bits, e.REL_X) and _has(rel_bits, e.REL_Y)):
        return None
    triggers = []
    if _has(rel_bits, e.REL_HWHEEL):
        triggers += ["tilt_left", "tilt_right"]
    if _has(key_bits, e.BTN_SIDE):
        triggers.append("side_back")
    if _has(key_bits, e.BTN_EXTRA):
        triggers.append("side_forward")
    return MouseInfo(name, f"/dev/input/{node}", BUSES.get(bus, f"0x{bus:02x}"), tuple(triggers))


def list_mice(sys_root=SYS_INPUT):
    try:
        nodes = sorted((p.name for p in sys_root.iterdir() if p.name.startswith("event")),
                       key=lambda n: int(n.removeprefix("event")))
    except OSError:
        return []
    return [m for m in (read_mouse(n, sys_root) for n in nodes) if m]


def pick(mice, wanted=""):
    """Escolhe o mouse: pelo nome configurado; sem nome, o primeiro com botões extras."""
    if wanted:
        return next((m for m in mice if m.name == wanted), None)
    return next((m for m in mice if m.triggers), mice[0] if mice else None)
