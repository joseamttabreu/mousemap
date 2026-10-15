"""Perfis por aplicativo (M4, SPEC §14)."""

import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

from evdev import ecodes as e

from mousemap import config as cfg
from mousemap.config import Action, AppProfile, ConfigError, find_profile
from mousemap.daemon.engine import Engine

Ev = namedtuple("Ev", "type code value")

TOML = '''version = 2
[buttons]
tilt_left = { preset = "workspace-prev" }
side_back = { keys = "alt+LEFT" }

[apps."org.mozilla.firefox"]
name = "Firefox"
tilt_left = { keys = "ctrl+shift+TAB" }
side_forward = "none"

[apps."Code"]
side_back = { cmd = "echo code" }
'''


class FakeOut:
    def __init__(self):
        self.events = []

    def write(self, _type, code, value):
        self.events.append((code, value))

    def syn(self):
        pass


class ProfileConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "config.toml"

    def tearDown(self):
        self.dir.cleanup()

    def load(self, text):
        self.path.write_text(text)
        return cfg.load(self.path)

    def test_parse_and_inherit(self):
        c = self.load(TOML)
        firefox = c.apps["org.mozilla.firefox"]
        self.assertEqual(firefox.name, "Firefox")
        self.assertEqual(set(firefox.buttons), {"tilt_left", "side_forward"})
        merged = c.actions_for("org.mozilla.firefox")
        self.assertEqual(merged["tilt_left"], Action("keys", "ctrl+shift+TAB"))
        self.assertEqual(merged["side_back"], Action("keys", "alt+LEFT"))       # herdado
        self.assertEqual(merged["side_forward"], Action("none"))
        self.assertEqual(c.actions_for(""), c.buttons)
        self.assertEqual(c.actions_for("não existe"), c.buttons)

    def test_find_profile_by_id_then_wm_class_case_insensitive(self):
        c = self.load(TOML)
        self.assertEqual(find_profile(c, "org.mozilla.firefox", "firefox"), "org.mozilla.firefox")
        self.assertEqual(find_profile(c, "ORG.MOZILLA.FIREFOX", ""), "org.mozilla.firefox")
        self.assertEqual(find_profile(c, "", "code"), "Code")                    # só classe da janela
        self.assertEqual(find_profile(c, "com.visualstudio.code", "Code"), "Code")
        self.assertEqual(find_profile(c, "org.gnome.Nautilus", "nautilus"), "")
        self.assertEqual(find_profile(c), "")

    def test_roundtrip_with_profiles(self):
        c = self.load(TOML)
        c.apps['app "estranho"'] = AppProfile(name="Ç", buttons={"tilt_right": Action("click", "middle")})
        cfg.save(c, self.path)
        self.assertEqual(cfg.load(self.path), c)

    def test_errors_name_the_profile(self):
        cases = {
            '[apps."x"]\ntilt_left = { keys = "ctrl+Nada" }': "apps.x.tilt_left",
            '[apps."x"]\nname = 3': "apps.x.name",
            'apps = 1': "[apps]",
            '[apps]\nx = 1': "apps.x",
        }
        for body, expected in cases.items():
            with self.assertRaises(ConfigError, msg=body) as ctx:
                self.load("version = 2\n" + body + "\n")
            self.assertIn(expected, str(ctx.exception))

    def test_unknown_button_in_profile_is_warning(self):
        c = self.load('version = 2\n[apps."x"]\nwheel_up = "none"\n')
        self.assertTrue(any("apps.x.wheel_up" in w for w in c.warnings))

    def test_v1_ignores_apps(self):
        c = self.load('tilt_left = "none"\n')
        self.assertEqual(c.apps, {})


class ProfileEngineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / "config.toml"
        path.write_text(TOML)
        self.config = cfg.load(path)
        self.kb, self.mouse, self.commands = FakeOut(), FakeOut(), []
        self.engine = Engine(self.config, self.kb, self.mouse, run_command=self.commands.append)

    def tearDown(self):
        self.dir.cleanup()

    def press(self, code, value):
        return self.engine.handle(Ev(e.EV_KEY, code, value))

    def test_switches_with_focus(self):
        self.assertEqual(self.engine.profile, "")
        self.assertEqual(self.engine.set_app("org.mozilla.firefox", "firefox"), "org.mozilla.firefox")
        self.assertTrue(self.press(e.BTN_EXTRA, 1))          # side_forward = none no Firefox
        self.assertTrue(self.press(e.BTN_EXTRA, 0))
        self.assertEqual(self.engine.set_app("org.gnome.Nautilus", "nautilus"), "")
        self.assertFalse(self.press(e.BTN_EXTRA, 1))         # padrão global: repassa
        self.assertFalse(self.press(e.BTN_EXTRA, 0))

    def test_inherited_trigger_uses_global(self):
        self.engine.set_app("org.mozilla.firefox", "")
        self.press(e.BTN_SIDE, 1)
        self.press(e.BTN_SIDE, 0)
        self.assertEqual(self.kb.events, [(e.KEY_LEFTALT, 1), (e.KEY_LEFT, 1), (e.KEY_LEFT, 0), (e.KEY_LEFTALT, 0)])

    def test_focus_change_mid_press_releases_what_was_pressed(self):
        self.engine.set_app("", "")
        self.press(e.BTN_SIDE, 1)                            # alt+LEFT pressionado (global)
        self.engine.set_app("", "Code")                      # no Code, side_back é um comando
        self.press(e.BTN_SIDE, 0)
        self.assertEqual(self.kb.events[-1], (e.KEY_LEFTALT, 0))
        self.assertEqual(self.commands, [])

    def test_reconfigure_keeps_focus(self):
        self.engine.set_app("", "Code")
        self.engine.configure(self.config)
        self.assertEqual(self.engine.profile, "Code")
        del self.config.apps["Code"]
        self.engine.configure(self.config)
        self.assertEqual(self.engine.profile, "")

    def test_test_action_per_profile(self):
        self.assertTrue(self.engine.test("side_back", profile="Code"))
        self.assertEqual(self.commands, ["echo code"])
        self.assertFalse(self.engine.test("side_forward", profile="org.mozilla.firefox"))  # none
        self.assertTrue(self.engine.test("tilt_left", profile=""))                         # global
        with self.assertRaises(KeyError):
            self.engine.test("tilt_left", profile="inexistente")


if __name__ == "__main__":
    unittest.main()
