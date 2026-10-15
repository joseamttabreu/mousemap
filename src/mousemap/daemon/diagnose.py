"""Diagnóstico guiado: mostra o evento que cada botão extra realmente envia (BUG-001).

Pede uma ação por vez, ignora o movimento do mouse e compara com o que o motor espera.
"""

import select
import subprocess
import sys
import termios
import time

import evdev
from evdev import ecodes as e

from ..config import TRIGGER_LABELS, TRIGGERS
from . import device

WINDOW_SECONDS = 4
SERVICE = "mousemapd.service"

PROMPTS = {
    "tilt_left": "Incline a roda para a ESQUERDA, uma vez",
    "tilt_right": "Incline a roda para a DIREITA, uma vez",
    "side_back": "Aperte o botão lateral de TRÁS, uma vez",
    "side_forward": "Aperte o botão lateral da FRENTE, uma vez",
}
# O que src/mousemap/daemon/engine.py espera para cada gatilho.
EXPECTED = {
    "tilt_left": "REL_HWHEEL −",
    "tilt_right": "REL_HWHEEL +",
    "side_back": "BTN_SIDE",
    "side_forward": "BTN_EXTRA",
}


def _name(table, code):
    name = table.get(code, str(code))
    return name if isinstance(name, str) else name[0]


def signature(ev):
    """Evento relevante -> texto ('BTN_SIDE', 'REL_HWHEEL −'); None para movimento, soltar, SYN etc."""
    if ev.type == e.EV_KEY and ev.value == 1:
        return _name(e.BTN, ev.code) if ev.code in e.BTN else _name(e.KEY, ev.code)
    if ev.type == e.EV_REL and ev.code in (e.REL_HWHEEL, e.REL_WHEEL) and ev.value:
        return f"{_name(e.REL, ev.code)} {'+' if ev.value > 0 else '−'}"
    return None


def summarize(observed):
    """{gatilho: [assinaturas]} -> linhas do relatório."""
    lines = []
    for trigger in TRIGGERS:
        got = list(dict.fromkeys(observed.get(trigger, [])))
        label = f"{TRIGGER_LABELS[trigger]:22}"
        if not got:
            lines.append(f"{label} nada recebido (esperado {EXPECTED[trigger]})")
        elif got == [EXPECTED[trigger]]:
            lines.append(f"{label} OK ({got[0]})")
        else:
            lines.append(f"{label} DIFERENTE: recebido {', '.join(got)} (esperado {EXPECTED[trigger]})")
    seen = {}
    for trigger in TRIGGERS:
        for sig in dict.fromkeys(observed.get(trigger, [])):
            seen.setdefault(sig, []).append(TRIGGER_LABELS[trigger])
    for sig, triggers in seen.items():
        if len(triggers) > 1:
            lines.append(f"CONFLITO: {sig} aparece em {' e '.join(triggers)}")
    return lines


def _collect(dev):
    """Lê por WINDOW_SECONDS e devolve as assinaturas relevantes, na ordem."""
    try:
        while dev.read_one():  # descarta o que chegou antes do Enter
            pass
    except BlockingIOError:
        pass
    found = []
    deadline = time.monotonic() + WINDOW_SECONDS
    while (left := deadline - time.monotonic()) > 0:
        if not select.select([dev.fd], [], [], left)[0]:
            continue
        try:
            for ev in dev.read():
                sig = signature(ev)
                if sig:
                    found.append(sig)
        except BlockingIOError:
            pass
    return found


def _discard_typed_input():
    try:
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (termios.error, ValueError, OSError):
        pass  # stdin não é um terminal


def _systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def run(wanted_device=""):
    target = device.pick(device.list_mice(), wanted_device)
    if target is None:
        sys.exit("Nenhum mouse encontrado.")
    was_active = _systemctl("is-active", SERVICE).stdout.strip() == "active"
    if was_active:
        print("Parando o mousemapd durante o diagnóstico (ele captura o mouse com exclusividade)...")
        _systemctl("stop", SERVICE)
    try:
        dev = evdev.InputDevice(target.path)
        print(f"\nMouse: {dev.name} ({dev.path})")
        print(f"Para cada passo: pressione Enter e faça a ação em até {WINDOW_SECONDS} s. O movimento é ignorado.\n")
        observed = {}
        for trigger in TRIGGERS:
            _discard_typed_input()  # um Enter a mais no passo anterior não pode iniciar este
            input(f"{PROMPTS[trigger]}. [Enter para começar] ")
            observed[trigger] = _collect(dev)
            print(f"   → {', '.join(observed[trigger]) or 'nada recebido'}")
        dev.close()
        print("\nResultado:")
        for line in summarize(observed):
            print(f"  {line}")
    except PermissionError:
        sys.exit(f"Sem permissão para ler {target.path}. Rode: sudo bash tools/setup-system.sh")
    except (KeyboardInterrupt, EOFError):
        print("\nDiagnóstico cancelado.")
    finally:
        if was_active:
            _systemctl("start", SERVICE)
            print("mousemapd reiniciado.")
    return 0
