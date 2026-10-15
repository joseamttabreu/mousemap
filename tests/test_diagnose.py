import unittest
from collections import namedtuple

from evdev import ecodes as e

from mousemap.daemon.diagnose import signature, summarize

Ev = namedtuple("Ev", "type code value")


class DiagnoseTest(unittest.TestCase):
    def test_signature_ignores_motion_releases_and_hi_res(self):
        ignored = [Ev(e.EV_REL, e.REL_X, 3), Ev(e.EV_REL, e.REL_Y, -1), Ev(e.EV_KEY, e.BTN_SIDE, 0),
                   Ev(e.EV_REL, e.REL_HWHEEL_HI_RES, 120), Ev(e.EV_MSC, e.MSC_SCAN, 589828), Ev(e.EV_SYN, 0, 0)]
        self.assertEqual([signature(ev) for ev in ignored], [None] * len(ignored))
        self.assertEqual(signature(Ev(e.EV_KEY, e.BTN_SIDE, 1)), "BTN_SIDE")
        self.assertEqual(signature(Ev(e.EV_KEY, e.BTN_LEFT, 1)), "BTN_LEFT")
        self.assertEqual(signature(Ev(e.EV_REL, e.REL_HWHEEL, -1)), "REL_HWHEEL −")
        self.assertEqual(signature(Ev(e.EV_REL, e.REL_HWHEEL, 1)), "REL_HWHEEL +")

    def test_summary_all_ok(self):
        lines = summarize({"tilt_left": ["REL_HWHEEL −"], "tilt_right": ["REL_HWHEEL +", "REL_HWHEEL +"],
                           "side_back": ["BTN_SIDE"], "side_forward": ["BTN_EXTRA"]})
        self.assertTrue(all("OK" in line for line in lines), lines)
        self.assertEqual(len(lines), 4)

    def test_summary_reports_bug_001_shape(self):
        # Forma observada no BUG-001: inclinar à esquerda chega como botão.
        lines = summarize({"tilt_left": ["BTN_EXTRA"], "tilt_right": ["REL_HWHEEL +"],
                           "side_back": ["BTN_SIDE"], "side_forward": ["BTN_EXTRA"], })
        self.assertIn("DIFERENTE: recebido BTN_EXTRA (esperado REL_HWHEEL −)", lines[0])
        self.assertTrue(any(line.startswith("CONFLITO: BTN_EXTRA") for line in lines))

    def test_summary_nothing_received(self):
        self.assertIn("nada recebido", summarize({})[0])


if __name__ == "__main__":
    unittest.main()
