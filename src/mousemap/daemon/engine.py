"""Motor de remapeamento: decide, evento a evento, o que repassar e o que trocar por ações.

Não abre dispositivos nem conhece D-Bus; recebe as saídas (objetos com write/syn, como o
UInput do python-evdev) para poder ser testado sem hardware. Há um motor por mouse capturado;
o teclado virtual é compartilhado (SharedKeyboard).
"""

import subprocess
import time
from collections import Counter

from evdev import ecodes as e

from ..config import TRIGGERS, find_profile

BUTTON_TRIGGERS = {
    e.BTN_SIDE: "side_back",
    e.BTN_EXTRA: "side_forward",
    e.BTN_MIDDLE: "middle",
    e.BTN_FORWARD: "btn_forward",
    e.BTN_BACK: "btn_back",
    e.BTN_TASK: "btn_task",
}
TILT_CODES = (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES)
HI_RES = {e.REL_WHEEL: e.REL_WHEEL_HI_RES, e.REL_HWHEEL: e.REL_HWHEEL_HI_RES}
MACRO_GAP_MS = 15  # entre dois atalhos seguidos de uma macro, sem pausa explícita

_DEFAULT = ("default", None)
_LEARN = ("none", None)


def spawn(command):
    subprocess.Popen(command, shell=True, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class SharedKeyboard:
    """Teclado virtual usado por todos os motores: uma tecla só é solta quando ninguém mais a segura."""

    def __init__(self, device):
        self.device = device
        self._held = Counter()

    def press(self, code):
        self._held[code] += 1
        if self._held[code] == 1:
            self.device.write(e.EV_KEY, code, 1)

    def release(self, code):
        if self._held[code] <= 0:
            return
        self._held[code] -= 1
        if not self._held[code]:
            del self._held[code]
            self.device.write(e.EV_KEY, code, 0)

    def syn(self):
        self.device.syn()


class Engine:
    def __init__(self, config, keyboard, mouse=None, run_command=spawn, on_learn=None,
                 clock=time.monotonic, schedule=None, mouse_name=""):
        """schedule(ms, função): agenda uma função (macros). Sem schedule, a macro roda de uma vez."""
        self.keyboard = keyboard if isinstance(keyboard, SharedKeyboard) else SharedKeyboard(keyboard)
        self.mouse = mouse
        self.mouse_name = mouse_name
        self.run_command = run_command
        self.on_learn = on_learn
        self.clock = clock
        self.schedule = schedule or (lambda _ms, function: function())
        self.learn = False
        self._active = {}         # botão físico pressionado -> ação compilada no momento do aperto
        self._held = Counter()    # teclas que ESTE motor segura (no teclado compartilhado)
        self._last_tilt = float("-inf")
        self._macro_generation = 0
        self._macro_running = False
        self._app = ("", "")      # (id do aplicativo em foco, classe da janela)
        self.profile = ""         # perfil de aplicativo vigente ("" = nenhum)
        self.configure(config)

    def configure(self, config):
        # Compila tudo antes de trocar: um erro não deixa o motor pela metade.
        compile_all = lambda app: {t: a.compile() for t, a in config.actions_for(app, self.mouse_name).items()}  # noqa: E731
        profiles = {key: compile_all(key) for key in config.apps}
        base = compile_all("")
        self._config, self._base, self._profiles = config, base, profiles
        self.cooldown = config.tilt_cooldown_ms / 1000
        self._select()

    def set_app(self, app_id, wm_class):
        """Aplicativo em foco mudou. Retorna o perfil vigente."""
        self._app = (app_id, wm_class)
        return self._select()

    def _select(self):
        # Botões já pressionados guardam a ação do aperto (_active): trocar aqui não prende nada.
        self.profile = find_profile(self._config, *self._app)
        self.actions = self._profiles.get(self.profile, self._base)
        return self.profile

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

    def test(self, trigger, profile=None):
        """Executa a ação do gatilho uma vez (no perfil indicado ou no vigente).

        Retorna False se não houver o que executar; KeyError se o perfil não existir.
        """
        actions = self.actions if profile is None else (self._profiles[profile] if profile else self._base)
        action = actions[trigger]
        if action[0] in ("default", "none"):
            return False
        self._tap(action)
        return True

    def _tap(self, action):
        self._start(action)
        self._stop(action)

    def _press(self, codes):
        for code in codes:
            self._held[code] += 1
            self.keyboard.press(code)
        self.keyboard.syn()

    def _release(self, codes):
        for code in reversed(codes):
            if self._held[code] > 0:
                self._held[code] -= 1
                self.keyboard.release(code)
        self.keyboard.syn()

    def _start(self, action):
        kind, payload = action
        if kind == "keys":
            self._press(payload)
        elif kind == "macro":
            self._run_macro(payload)
        elif kind == "click" and self.mouse:
            self.mouse.write(e.EV_KEY, payload, 1)
            self.mouse.syn()
        elif kind == "scroll" and self.mouse:
            axis, direction = payload
            self.mouse.write(e.EV_REL, axis, direction)
            self.mouse.write(e.EV_REL, HI_RES[axis], 120 * direction)
            self.mouse.syn()
        elif kind == "cmd":
            self.run_command(payload)

    def _stop(self, action):
        kind, payload = action
        if kind == "keys":
            self._release(payload)
        elif kind == "click" and self.mouse:
            self.mouse.write(e.EV_KEY, payload, 0)
            self.mouse.syn()

    def _run_macro(self, steps):
        """Agenda os atalhos da macro nos instantes certos; um novo aperto durante a macro é ignorado."""
        if self._macro_running:
            return
        plan, at, after_keys = [], 0, False
        for kind, value in steps:
            if kind == "delay":
                at, after_keys = at + value, False
            else:
                at += MACRO_GAP_MS if after_keys else 0
                plan.append((at, value))
                after_keys = True
        generation = self._macro_generation
        self._macro_running = True

        def step(index):
            if generation != self._macro_generation:  # cancelada (desconexão, recarga, encerramento)
                return
            combo = plan[index][1]
            self._press(combo)
            self._release(combo)
            if index + 1 < len(plan):
                self.schedule(plan[index + 1][0] - plan[index][0], lambda: step(index + 1))
            else:
                self._macro_running = False

        self.schedule(plan[0][0], lambda: step(0))

    def cancel_macro(self):
        self._macro_generation += 1
        self._macro_running = False

    def release_all(self):
        """Solta tudo o que este motor segura e cancela macros (desconexão, recarga, encerramento)."""
        self.cancel_macro()
        for action in self._active.values():
            if action[0] == "click" and self.mouse:
                self.mouse.write(e.EV_KEY, action[1], 0)
        if self.mouse:
            self.mouse.syn()
        for code, count in self._held.items():
            for _ in range(count):
                self.keyboard.release(code)
        self.keyboard.syn()
        self._active.clear()
        self._held.clear()

    def _notify_learn(self, trigger):
        if self.on_learn:
            self.on_learn(trigger)
