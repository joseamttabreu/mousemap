import tempfile
import unittest
from pathlib import Path

from mousemap.daemon import device

MX = {"name": "MX Anywhere 2S Mouse", "key": "ffff0000 0 0 0 0", "rel": "1943", "bus": "0005"}
TOUCHPAD = {"name": "VEN_06CB:00 06CB:CEEC Mouse", "key": "70000 0 0 0 0", "rel": "3", "bus": "0018"}
KEYBOARD = {"name": "AT Translated Set 2 keyboard", "key": "402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe", "rel": "0", "bus": "0011"}
VIRTUAL = {**MX, "name": "mousemap: MX Anywhere 2S Mouse"}


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def add(self, node, spec):
        dev = self.root / node / "device"
        (dev / "capabilities").mkdir(parents=True)
        (dev / "id").mkdir()
        (dev / "name").write_text(spec["name"] + "\n")
        (dev / "capabilities" / "key").write_text(spec["key"] + "\n")
        (dev / "capabilities" / "rel").write_text(spec["rel"] + "\n")
        (dev / "id" / "bustype").write_text(spec["bus"] + "\n")

    def test_lists_only_real_mice_with_triggers(self):
        self.add("event3", KEYBOARD)
        self.add("event10", TOUCHPAD)
        self.add("event24", MX)
        self.add("event30", VIRTUAL)
        mice = device.list_mice(self.root)
        self.assertEqual([m.name for m in mice], [TOUCHPAD["name"], MX["name"]])
        mx = mice[1]
        self.assertEqual(mx.bus, "bluetooth")
        self.assertEqual(mx.path, "/dev/input/event24")
        self.assertEqual(mx.triggers, ("tilt_left", "tilt_right", "side_back", "side_forward"))
        self.assertEqual(mice[0].triggers, ())

    def test_pick(self):
        self.add("event10", TOUCHPAD)
        self.add("event24", MX)
        mice = device.list_mice(self.root)
        self.assertEqual(device.pick(mice).name, MX["name"])  # automático prefere botões extras
        self.assertEqual(device.pick(mice, TOUCHPAD["name"]).name, TOUCHPAD["name"])
        self.assertIsNone(device.pick(mice, "Outro"))
        self.assertIsNone(device.pick([]))


if __name__ == "__main__":
    unittest.main()
