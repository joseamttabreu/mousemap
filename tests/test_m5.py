"""M5: macros, rolagem, gatilhos novos e vários mouses (SPEC §15)."""

import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

from evdev import ecodes as e

from mousemap import config as cfg
from mousemap.config import Action, ConfigError, Profile, parse_macro
from mousemap.daemon import device
from mousemap.daemon.engine import MACRO_GAP_MS, Engine, SharedKeyboard

Ev = namedtuple("Ev", "type code value")


class FakeOut:
    def __init__(self):
        self.events = []

    def write(self, type_, code, value):
        self.events.append((type_, code, value))

    def syn(self):
        pass

    def keys(self):
        return [(c, v) for t, c, v in self.events if t == e.EV_KEY]


class FakeScheduler:
    """Guarda (atraso, função) em vez de agendar; run() executa na ordem, somando o tempo."""

    def __init__(self):
        self.pending = []
        self.elapsed = []

    def __call__(self, ms, function):
        self.pending.append((ms, function))

    def run(self):
        total = 0
        while self.pending:
            ms, function = self.pending.pop(0)
            total += ms
            self.elapsed.append(total)
            function()


def engine_with(buttons=None, config=None, **kwargs):
    config = config or cfg.Config()
    for trigger, action in (buttons or {}).items():
        config.buttons[trigger] = action
    kb, mouse, scheduler = FakeOut(), FakeOut(), FakeScheduler()
    engine = Engine(config, kwargs.pop("keyboard", kb), mouse, schedule=scheduler, **kwargs)
    return engine, kb, mouse, scheduler


class MacroConfigTest(unittest.TestCase):
    def test_parse_and_normalize(self):
        steps = parse_macro("Ctrl+C, 100ms ,alt+Tab, 150MS, ctrl+v")
        self.assertEqual(steps, (("keys", (e.KEY_LEFTCTRL, e.KEY_C)), ("delay", 100),
                                 ("keys", (e.KEY_LEFTALT, e.KEY_TAB)), ("delay", 150),
                                 ("keys", (e.KEY_LEFTCTRL, e.KEY_V))))
        action = Action.parse({"macro": "Ctrl+C, 100ms ,alt+Tab"})
        self.assertEqual(action.value, "ctrl+c, 100ms, alt+TAB")
        self.assertEqual(action.describe(), "Macro: Ctrl + C → 100 ms → Alt + Tab")

    def test_invalid_macros(self):
        cases = {
            "": "texto não vazio", "ctrl+c,,ctrl+v": "passo vazio", "100ms": "ao menos um atalho",
            "ctrl+c, 5ms": "entre 10 e 5000", "ctrl+c, 6000ms": "entre 10 e 5000",
            ", ".join(["a"] * 21): "mais de 20 passos", "a, 5000ms, 5000ms, 1000ms": "10000 ms",
            "ctrl+Nada": "tecla desconhecida",
        }
        for text, message in cases.items():
            with self.assertRaises(ValueError, msg=text) as ctx:
                Action.parse({"macro": text})
            self.assertIn(message, str(ctx.exception), text)

    def test_scroll(self):
        self.assertEqual(Action.parse({"scroll": "up"}).compile(), ("scroll", (e.REL_WHEEL, 1)))
        self.assertEqual(Action("scroll", "left").describe(), "Rolar para a esquerda")
        with self.assertRaises(ValueError):
            Action.parse({"scroll": "diagonal"})


class MacroEngineTest(unittest.TestCase):
    def test_runs_steps_at_the_right_time(self):
        engine, kb, _, scheduler = engine_with({"side_back": Action("macro", "ctrl+c, 100ms, alt+TAB, ctrl+v")})
        self.assertTrue(engine.handle(Ev(e.EV_KEY, e.BTN_SIDE, 1)))
        engine.handle(Ev(e.EV_KEY, e.BTN_SIDE, 0))
        scheduler.run()
        self.assertEqual(scheduler.elapsed, [0, 100, 100 + MACRO_GAP_MS])
        self.assertEqual(kb.keys(), [
            (e.KEY_LEFTCTRL, 1), (e.KEY_C, 1), (e.KEY_C, 0), (e.KEY_LEFTCTRL, 0),
            (e.KEY_LEFTALT, 1), (e.KEY_TAB, 1), (e.KEY_TAB, 0), (e.KEY_LEFTALT, 0),
            (e.KEY_LEFTCTRL, 1), (e.KEY_V, 1), (e.KEY_V, 0), (e.KEY_LEFTCTRL, 0)])

    def test_no_reentry_while_running(self):
        engine, kb, _, scheduler = engine_with({"tilt_left": Action("macro", "a, 500ms, b")})
        engine.test("tilt_left")
        engine.test("tilt_left")  # ainda rodando: ignorado
        scheduler.run()
        self.assertEqual([c for c, v in kb.keys() if v == 1], [e.KEY_A, e.KEY_B])
        engine.test("tilt_left")  # terminou: roda de novo
        scheduler.run()
        self.assertEqual(len(kb.keys()), 8)

    def test_release_all_cancels_pending_steps(self):
        engine, kb, _, scheduler = engine_with({"side_back": Action("macro", "a, 500ms, b")})
        engine.test("side_back")
        scheduler.pending[0][1]()   # primeiro passo
        scheduler.pending.pop(0)
        engine.release_all()        # mouse desconectou
        scheduler.run()
        self.assertEqual([c for c, v in kb.keys() if v == 1], [e.KEY_A])


class ActionsAndTriggersTest(unittest.TestCase):
    def test_scroll_emits_low_and_high_resolution(self):
        engine, _, mouse, _ = engine_with({"tilt_right": Action("scroll", "down")})
        engine.handle(Ev(e.EV_REL, e.REL_HWHEEL, 1))
        self.assertEqual(mouse.events, [(e.EV_REL, e.REL_WHEEL, -1), (e.EV_REL, e.REL_WHEEL_HI_RES, -120)])

    def test_new_button_triggers(self):
        engine, kb, _, _ = engine_with({"middle": Action("keys", "ctrl+w"), "btn_task": Action("keys", "F5")})
        for code in (e.BTN_MIDDLE, e.BTN_TASK):
            self.assertTrue(engine.handle(Ev(e.EV_KEY, code, 1)))
            self.assertTrue(engine.handle(Ev(e.EV_KEY, code, 0)))
        self.assertEqual([c for c, v in kb.keys() if v == 1], [e.KEY_LEFTCTRL, e.KEY_W, e.KEY_F5])
        self.assertFalse(engine.handle(Ev(e.EV_KEY, e.BTN_FORWARD, 1)))  # padrão: repassa

    def test_shared_keyboard_between_two_mice(self):
        shared = SharedKeyboard(FakeOut())
        buttons = {"side_back": Action("keys", "ctrl+c")}
        first, *_ = engine_with(buttons, keyboard=shared)
        second, *_ = engine_with(buttons, keyboard=shared)
        first.handle(Ev(e.EV_KEY, e.BTN_SIDE, 1))
        second.handle(Ev(e.EV_KEY, e.BTN_SIDE, 1))
        first.release_all()  # o primeiro mouse desconectou com ctrl seguro
        self.assertNotIn((e.KEY_LEFTCTRL, 0), shared.device.keys())  # o segundo ainda segura
        second.handle(Ev(e.EV_KEY, e.BTN_SIDE, 0))
        self.assertEqual(shared.device.keys()[-1], (e.KEY_LEFTCTRL, 0))


class MiceConfigTest(unittest.TestCase):
    TOML = '''version = 2
[settings]
devices = ["Mouse A", "Mouse B", "Mouse A"]
[buttons]
side_back = { keys = "alt+LEFT" }
tilt_left = { scroll = "up" }
[mice."Mouse B"]
side_back = { preset = "copy" }
middle = "none"
[apps."org.mozilla.firefox"]
side_back = { keys = "ctrl+w" }
'''

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "config.toml"

    def tearDown(self):
        self.dir.cleanup()

    def load(self, text):
        self.path.write_text(text)
        return cfg.load(self.path)

    def test_layers_global_mouse_app(self):
        c = self.load(self.TOML)
        self.assertEqual(c.devices, ["Mouse A", "Mouse B"])  # duplicado removido
        self.assertEqual(c.actions_for("", "Mouse A")["side_back"], Action("keys", "alt+LEFT"))
        self.assertEqual(c.actions_for("", "Mouse B")["side_back"], Action("preset", "copy"))
        self.assertEqual(c.actions_for("", "Mouse B")["middle"], Action("none"))
        self.assertEqual(c.actions_for("org.mozilla.firefox", "Mouse B")["side_back"], Action("keys", "ctrl+w"))
        self.assertEqual(c.actions_for("org.mozilla.firefox", "Mouse B")["middle"], Action("none"))

    def test_engine_uses_its_mouse_layer(self):
        c = self.load(self.TOML)
        a, kb_a, *_ = engine_with(config=c, mouse_name="Mouse A")
        b, kb_b, *_ = engine_with(config=c, mouse_name="Mouse B")
        a.handle(Ev(e.EV_KEY, e.BTN_SIDE, 1))
        b.handle(Ev(e.EV_KEY, e.BTN_SIDE, 1))
        self.assertEqual(kb_a.keys(), [(e.KEY_LEFTALT, 1), (e.KEY_LEFT, 1)])
        self.assertEqual(kb_b.keys(), [(e.KEY_LEFTCTRL, 1), (e.KEY_C, 1)])

    def test_roundtrip_and_extras_only_when_set(self):
        c = self.load(self.TOML)
        c.buttons["btn_task"] = Action("macro", "ctrl+c, 50ms, ctrl+v")
        c.mice["Mouse C"] = Profile(buttons={"btn_back": Action("none")})
        cfg.save(c, self.path)
        text = self.path.read_text()
        self.assertIn("btn_task", text)
        self.assertNotIn("btn_forward =", text)  # extra em "default" não é gravado
        self.assertIn('devices = ["Mouse A", "Mouse B"]', text)
        self.assertEqual(cfg.load(self.path), c)

    def test_old_device_key_and_errors(self):
        self.assertEqual(self.load('version = 2\n[settings]\ndevice = "X"\n').devices, ["X"])
        self.assertEqual(self.load('version = 2\n[settings]\ndevice = ""\n').devices, [])
        for body, message in {'[settings]\ndevices = "X"': "settings.devices",
                              '[settings]\ndevices = ["", "X"]': "settings.devices",
                              '[mice."M"]\nside_back = { scroll = "x" }': "mice.M.side_back"}.items():
            with self.assertRaises(ConfigError, msg=body) as ctx:
                self.load("version = 2\n" + body + "\n")
            self.assertIn(message, str(ctx.exception))


class PickManyTest(unittest.TestCase):
    def test_pick_many(self):
        mice = [device.MouseInfo("Touchpad", "/dev/input/event1", "i2c", ("middle",)),
                device.MouseInfo("MX", "/dev/input/event2", "bluetooth", ("tilt_left", "tilt_right", "side_back")),
                device.MouseInfo("M720", "/dev/input/event3", "usb", ("side_back", "side_forward"))]
        self.assertEqual([m.name for m in device.pick_many(mice, [])], ["MX"])  # automático: um só
        self.assertEqual([m.name for m in device.pick_many(mice, ["M720", "MX", "Sumido"])], ["MX", "M720"])
        self.assertEqual(device.pick_many([], []), [])


if __name__ == "__main__":
    unittest.main()
