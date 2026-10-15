import tempfile
import unittest
from pathlib import Path

from evdev import ecodes as e

from mousemap import config as cfg, keys
from mousemap.config import Action, ConfigError


class KeysTest(unittest.TestCase):
    def test_parse_names_case_and_underscores(self):
        self.assertEqual(keys.parse_combo("Super+Page_Up"), (e.KEY_LEFTMETA, e.KEY_PAGEUP))
        self.assertEqual(keys.parse_combo("CTRL + shift + T"), (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_T))
        self.assertEqual(keys.parse_combo("win+print"), (e.KEY_LEFTMETA, e.KEY_SYSRQ))

    def test_invalid(self):
        for text in ("", "+", "ctrl+Foo", "a+b+c+d+e+f", "btn_left"):
            with self.assertRaises(ValueError, msg=text):
                keys.parse_combo(text)

    def test_format_puts_modifiers_first_and_normalizes_right_side(self):
        self.assertEqual(keys.format_combo((e.KEY_T, e.KEY_RIGHTCTRL)), "ctrl+t")
        self.assertEqual(keys.format_combo((e.KEY_RIGHTALT, e.KEY_E)), "altgr+e")

    def test_roundtrip_and_label(self):
        codes = keys.parse_combo("super+pageup")
        self.assertEqual(keys.parse_combo(keys.format_combo(codes)), codes)
        self.assertEqual(keys.label(codes), "Super + Page Up")
        self.assertEqual(keys.label(keys.parse_combo("ctrl+shift+t")), "Ctrl + Shift + T")

    def test_keyboard_keys_exclude_mouse_buttons(self):
        self.assertIn(e.KEY_VOLUMEUP, keys.KEYBOARD_KEYS)
        self.assertNotIn(e.BTN_LEFT, keys.KEYBOARD_KEYS)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "config.toml"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text):
        self.path.write_text(text)

    def test_missing_file_gives_defaults(self):
        config = cfg.load(self.path)
        self.assertEqual(config, cfg.Config())
        self.assertTrue(all(a.kind == "default" for a in config.buttons.values()))

    def test_v2(self):
        self.write('version = 2\n[settings]\ntilt_cooldown_ms = 500\ndevice = "X"\n'
                   '[buttons]\ntilt_left = { preset = "workspace-prev" }\nside_back = { cmd = "echo oi" }\n'
                   'side_forward = "none"\ntilt_right = { click = "middle" }\n')
        c = cfg.load(self.path)
        self.assertEqual((c.devices, c.tilt_cooldown_ms), (["X"], 500))  # "device" do formato antigo
        self.assertEqual(c.buttons["tilt_left"], Action("preset", "workspace-prev"))
        self.assertEqual(c.buttons["side_back"].compile(), ("cmd", "echo oi"))
        self.assertEqual(c.buttons["side_forward"].compile(), ("none", None))
        self.assertEqual(c.buttons["tilt_right"].compile(), ("click", e.BTN_MIDDLE))

    def test_v1_prototype_format(self):
        self.write('tilt_left = { keys = "super+Page_Up" }\nside_back = "default"\n'
                   '[settings]\ndevice = "MX Anywhere 2S Mouse"\ntilt_cooldown_ms = 350\n')
        c = cfg.load(self.path)
        self.assertEqual(c.buttons["tilt_left"], Action("keys", "super+PAGEUP"))
        self.assertEqual(c.devices, ["MX Anywhere 2S Mouse"])

    def test_errors(self):
        cases = {
            "tilt_left = { keys = \"ctrl+Nada\" }": "tilt_left",
            "side_back = { click = \"meio\" }": "side_back",
            "side_back = { preset = \"nao-existe\" }": "side_back",
            "side_back = { keys = \"\" }": "side_back",
            "side_back = 3": "side_back",
            "[settings]\ntilt_cooldown_ms = 5": "tilt_cooldown_ms",
            "[settings]\ntilt_cooldown_ms = true": "tilt_cooldown_ms",
            "version = 9": "versão",
            "isto não é toml": "TOML",
        }
        for text, expected in cases.items():
            self.write(text)
            with self.assertRaises(ConfigError, msg=text) as ctx:
                cfg.load(self.path)
            self.assertIn(expected, str(ctx.exception))

    def test_unknown_keys_are_warnings(self):
        self.write('version = 2\nfoo = 1\n[buttons]\nwheel_up = "none"\n')
        self.assertEqual(len(cfg.load(self.path).warnings), 2)

    def test_save_roundtrip(self):
        c = cfg.Config(devices=['Mouse "aspas" \\ á', "Outro"], tilt_cooldown_ms=800)
        c.buttons["side_back"] = Action("cmd", 'notify-send "olá"')
        c.buttons["tilt_left"] = Action("keys", "ctrl+alt+LEFT")
        c.buttons["tilt_right"] = Action("none")
        cfg.save(c, self.path)
        self.assertEqual(cfg.load(self.path), c)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["config.toml"])  # sem temporários

    def test_describe(self):
        self.assertEqual(Action("preset", "volume-up").describe(), "Aumentar volume")
        self.assertEqual(Action("keys", "super+PAGEUP").describe(), "Super + Page Up")
        self.assertEqual(Action("cmd", "x").describe(), "Comando: x")


if __name__ == "__main__":
    unittest.main()
