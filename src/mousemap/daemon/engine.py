"""Motor de remapeamento: decide, evento a evento, o que repassar e o que trocar por ações.

Não abre dispositivos nem conhece D-Bus; recebe as saídas (objetos com write/syn, como o
UInput do python-evdev) para poder ser testado sem hardware.
"""

import subprocess
import time
from collections import Counter

from evdev import ecodes as e

from ..config import TRIGGERS

BUTTON_TRIGGERS = {e.BTN_SIDE: "side_back", e.BTN_EXTRA: "side_forward"}
TILT_CODES = (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES)

_DEFAULT = ("default", None)
_LEARN = ("none", None)


def spawn(command):
    subprocess.Popen(command, shell=True, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Engine:
    def __init__(self, config, keyboard, mouse=None, run_command=spawn, on_learn=None, clock=time.monotonic):
        self.keyboard = keyboard
        self.mouse = mouse
        self.run_command = run_command
        self.on_learn = on_learn
        self.clock = clock
        self.learn = False
        self._active = {}         # botão físico pressionado -> ação compilada no momento do aperto
        self._held = Counter()    # teclas que nós mantemos pressionadas
        self._last_tilt = float("-inf")
        self.configure(config)

    def configure(self, config):
        actions = {t: config.buttons[t].compile() for t in TRIGGERS}  # valida antes de trocar
        self.actions = actions
        self.cooldown = config.tilt_cooldown_ms / 1000

    # --- entrada -------------------------------------------------------------------------

    def handle(self, ev):
        """Trata um evento do mouse físico. True = consumido (não repassar)."""
        if ev.type == e.EV_KEY and ev.code in BUTTON_TRIGGERS:
            return self._button(BUTTON_TRIGGERS[ev.code], ev.code, ev.value)
        if ev.type == e.EV_REL and ev.code in TILT_CODES and ev.value:
            return self._tilt("tilt_right" if ev.value > 0 else "tilt_left", ev.code)
        return False

    def _button(self, trigger, code, value):
        if value == 1:
            if self.learn:
                self._notify_learn(trigger)
                self._active[code] = _LEARN
                return True
            action = self.actions[trigger]
            self._active[code] = action
            if action == _DEFAULT:
                return False
            self._start(action)
            return True
        if value == 0:
            # Usa a ação vigente no aperto: recarga ou modo identificar no meio do clique não prendem nada.
            action = self._active.pop(code, None)
            if action is None or action == _DEFAULT:
                return False
            self._stop(action)
            return True
        return self._active.get(code, _DEFAULT) != _DEFAULT  # autorepeat

    def _tilt(self, trigger, code):
        action = self.actions[trigger]
        if not self.learn and action == _DEFAULT:
            return False
        # Cada passo gera REL_HWHEEL e REL_HWHEEL_HI_RES; dispara só no primeiro e limita a repetição.
        now = self.clock()
        if code == e.REL_HWHEEL and now - self._last_tilt >= self.cooldown:
            self._last_tilt = now
            if self.learn:
                self._notify_learn(trigger)
            else:
                self._tap(action)
        return True

    # --- ações ---------------------------------------------------------------------------

    def test(self, trigger):
        """Executa a ação do gatilho uma vez. Retorna False se não houver o que executar."""
        action = self.actions[trigger]
        if action[0] in ("default", "none"):
            return False
        self._tap(action)
        return True

    def _tap(self, action):
        self._start(action)
        self._stop(action)

    def _start(self, action):
        kind, payload = action
        if kind == "keys":
            for code in payload:
                self._held[code] += 1
                if self._held[code] == 1:
                    self.keyboard.write(e.EV_KEY, code, 1)
            self.keyboard.syn()
        elif kind == "click" and self.mouse:
            self.mouse.write(e.EV_KEY, payload, 1)
            self.mouse.syn()
        elif kind == "cmd":
            self.run_command(payload)

    def _stop(self, action):
        kind, payload = action
        if kind == "keys":
            for code in reversed(payload):
                self._held[code] -= 1
                if self._held[code] <= 0:
                    del self._held[code]
                    self.keyboard.write(e.EV_KEY, code, 0)
            self.keyboard.syn()
        elif kind == "click" and self.mouse:
            self.mouse.write(e.EV_KEY, payload, 0)
            self.mouse.syn()

    def release_all(self):
        """Solta tudo o que estiver pressionado por nós (desconexão, recarga, encerramento)."""
        for action in self._active.values():
            if action[0] == "click" and self.mouse:
                self.mouse.write(e.EV_KEY, action[1], 0)
        if self.mouse:
            self.mouse.syn()
        for code in self._held:
            self.keyboard.write(e.EV_KEY, code, 0)
        self.keyboard.syn()
        self._active.clear()
        self._held.clear()

    def _notify_learn(self, trigger):
        if self.on_learn:
            self.on_learn(trigger)
