import unittest
from collections import namedtuple

from evdev import ecodes as e

from mousemap import config as cfg
from mousemap.config import Action
from mousemap.daemon.engine import Engine

Ev = namedtuple("Ev", "type code value")


class FakeOut:
    def __init__(self):
        self.events = []

    def write(self, type_, code, value):
        self.events.append((code, value))

    def syn(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(**buttons):
    config = cfg.Config(tilt_cooldown_ms=350)
    for trigger, action in buttons.items():
        config.buttons[trigger] = action
    kb, mouse, clock, commands, learned = FakeOut(), FakeOut(), FakeClock(), [], []
    engine = Engine(config, kb, mouse, run_command=commands.append, on_learn=learned.append, clock=clock)
    return engine, kb, mouse, clock, commands, learned


def press(code, value):
    return Ev(e.EV_KEY, code, value)


def tilt(value, hi_res=False):
    return Ev(e.EV_REL, e.REL_HWHEEL_HI_RES if hi_res else e.REL_HWHEEL, value * (120 if hi_res else 1))


class EngineTest(unittest.TestCase):
    def test_default_passes_everything_through(self):
        engine, kb, *_ = make()
        for ev in (press(e.BTN_SIDE, 1), press(e.BTN_SIDE, 0), tilt(-1), tilt(-1, True),
                   Ev(e.EV_REL, e.REL_X, 5), press(e.BTN_LEFT, 1)):
            self.assertFalse(engine.handle(ev), ev)
        self.assertEqual(kb.events, [])

    def test_keys_held_while_button_held(self):
        engine, kb, *_ = make(side_back=Action("keys", "ctrl+c"))
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 1)))
        self.assertEqual(kb.events, [(e.KEY_LEFTCTRL, 1), (e.KEY_C, 1)])
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 0)))
        self.assertEqual(kb.events[2:], [(e.KEY_C, 0), (e.KEY_LEFTCTRL, 0)])

    def test_shared_modifier_released_only_when_last_holder_releases(self):
        engine, kb, *_ = make(side_back=Action("keys", "ctrl+c"), side_forward=Action("keys", "ctrl+v"))
        engine.handle(press(e.BTN_SIDE, 1))
        engine.handle(press(e.BTN_EXTRA, 1))
        engine.handle(press(e.BTN_SIDE, 0))
        self.assertNotIn((e.KEY_LEFTCTRL, 0), kb.events)
        engine.handle(press(e.BTN_EXTRA, 0))
        self.assertEqual(kb.events[-1], (e.KEY_LEFTCTRL, 0))

    def test_tilt_taps_once_per_cooldown_and_swallows_hi_res(self):
        engine, kb, _, clock, *_ = make(tilt_left=Action("preset", "workspace-prev"))
        self.assertTrue(engine.handle(tilt(-1, True)))
        self.assertEqual(kb.events, [])  # hi-res sozinho não dispara
        self.assertTrue(engine.handle(tilt(-1)))
        self.assertEqual(kb.events, [(e.KEY_LEFTMETA, 1), (e.KEY_PAGEUP, 1), (e.KEY_PAGEUP, 0), (e.KEY_LEFTMETA, 0)])
        clock.now += 0.1
        engine.handle(tilt(-1))
        self.assertEqual(len(kb.events), 4)  # dentro do intervalo
        clock.now += 0.3
        engine.handle(tilt(-1))
        self.assertEqual(len(kb.events), 8)

    def test_unmapped_direction_still_scrolls(self):
        engine, kb, *_ = make(tilt_left=Action("none"))
        self.assertTrue(engine.handle(tilt(-1)))
        self.assertFalse(engine.handle(tilt(1)))
        self.assertFalse(engine.handle(tilt(1, True)))

    def test_cmd_runs_on_press_only(self):
        engine, _, _, _, commands, _ = make(side_forward=Action("cmd", "gnome-calculator"))
        engine.handle(press(e.BTN_EXTRA, 1))
        engine.handle(press(e.BTN_EXTRA, 0))
        self.assertEqual(commands, ["gnome-calculator"])

    def test_click_mirrors_press_and_release(self):
        engine, kb, mouse, *_ = make(side_back=Action("click", "middle"))
        engine.handle(press(e.BTN_SIDE, 1))
        engine.handle(press(e.BTN_SIDE, 0))
        self.assertEqual(mouse.events, [(e.BTN_MIDDLE, 1), (e.BTN_MIDDLE, 0)])
        self.assertEqual(kb.events, [])

    def test_none_swallows(self):
        engine, kb, mouse, *_ = make(side_back=Action("none"))
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 1)))
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 0)))
        self.assertEqual((kb.events, mouse.events), ([], []))

    def test_release_uses_action_from_press_time(self):
        engine, kb, *_ = make(side_back=Action("keys", "ctrl+c"))
        engine.handle(press(e.BTN_SIDE, 1))
        new = cfg.Config()
        engine.configure(new)  # agora side_back = default
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 0)))
        self.assertEqual(kb.events[-1], (e.KEY_LEFTCTRL, 0))

    def test_default_press_passes_release_even_if_remapped_meanwhile(self):
        engine, *_ = make()
        self.assertFalse(engine.handle(press(e.BTN_SIDE, 1)))
        config = cfg.Config()
        config.buttons["side_back"] = Action("none")
        engine.configure(config)
        self.assertFalse(engine.handle(press(e.BTN_SIDE, 0)))

    def test_learn_mode_reports_and_swallows(self):
        engine, kb, _, _, commands, learned = make(side_back=Action("cmd", "x"))
        engine.learn = True
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 1)))
        self.assertTrue(engine.handle(press(e.BTN_SIDE, 0)))
        self.assertTrue(engine.handle(tilt(1, True)))
        self.assertTrue(engine.handle(tilt(1)))
        self.assertEqual(learned, ["side_back", "tilt_right"])
        self.assertEqual((commands, kb.events), ([], []))

    def test_release_all_unsticks_keys_and_clicks(self):
        engine, kb, mouse, *_ = make(side_back=Action("keys", "ctrl+shift"), side_forward=Action("click", "left"))
        engine.handle(press(e.BTN_SIDE, 1))
        engine.handle(press(e.BTN_EXTRA, 1))
        engine.release_all()
        self.assertIn((e.KEY_LEFTCTRL, 0), kb.events)
        self.assertIn((e.KEY_LEFTSHIFT, 0), kb.events)
        self.assertEqual(mouse.events[-1], (e.BTN_LEFT, 0))
        self.assertFalse(engine.handle(press(e.BTN_SIDE, 0)))  # nada mais preso

    def test_test_action(self):
        engine, kb, *_ = make(tilt_right=Action("preset", "volume-up"))
        self.assertTrue(engine.test("tilt_right"))
        self.assertEqual(kb.events, [(e.KEY_VOLUMEUP, 1), (e.KEY_VOLUMEUP, 0)])
        self.assertFalse(engine.test("tilt_left"))


if __name__ == "__main__":
    unittest.main()
