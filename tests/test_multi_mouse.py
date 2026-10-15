"""Integração com dispositivos reais: dois mouses de origem virtuais (uinput) e o mousemapd de verdade.

Nada chega à sessão gráfica: só há ações de clique e rolagem, que saem pelos mouses virtuais do
serviço de teste, e o teste os captura com exclusividade (EVIOCGRAB) antes de emitir qualquer evento.
O teclado virtual não é verificado aqui de propósito: a regra udev dá acesso só a mouses, nunca a
teclados; as ações de teclado são cobertas pelos testes do motor. Pula sem acesso a /dev/uinput.
"""

import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import evdev
from evdev import UInput, ecodes as e

ROOT = Path(__file__).resolve().parent.parent


def names():
    found = {}
    for path in evdev.list_devices():
        try:
            found[path] = evdev.InputDevice(path).name
        except OSError:
            pass
    return found


def wait_for(condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.05)
    return None


def read_events(dev, timeout=1.5):
    """Eventos relevantes (sem SYN) até `timeout` sem novidade."""
    events = []
    while select.select([dev.fd], [], [], timeout)[0]:
        events += [(ev.type, ev.code, ev.value) for ev in dev.read() if ev.type != e.EV_SYN]
        timeout = 0.3
    return events


@unittest.skipUnless(os.access("/dev/uinput", os.W_OK), "sem acesso a /dev/uinput")
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session não instalado")
class MultiMouseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tag = os.getpid()
        self.name_a, self.name_b = f"mmtest A {tag}", f"mmtest B {tag}"
        caps = {e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE, e.BTN_SIDE, e.BTN_EXTRA],
                e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL, e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES]}
        self.before = set(names())
        self.src_a = UInput(caps, name=self.name_a)
        self.src_b = UInput(caps, name=self.name_b)
        self.config = Path(self.tmp.name) / "config.toml"
        self.config.write_text(textwrap.dedent(f'''\
            version = 2
            [settings]
            devices = ["{self.name_a}", "{self.name_b}"]
            [buttons]
            side_back = {{ click = "right" }}
            middle = {{ scroll = "up" }}
            [mice."{self.name_b}"]
            side_back = {{ click = "middle" }}
            '''))
        self.log = Path(self.tmp.name) / "daemon.log"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "GIO_USE_VFS": "local"}
        self.daemon = subprocess.Popen(
            ["dbus-run-session", "--", sys.executable, "-m", "mousemap.daemon.main", "--config", str(self.config)],
            stdout=subprocess.DEVNULL, stderr=self.log.open("w"), env=env, start_new_session=True)
        self.grabbed = []

    def tearDown(self):
        for dev in self.grabbed:
            try:
                dev.ungrab()
                dev.close()
            except OSError:
                pass
        os.killpg(self.daemon.pid, signal.SIGTERM)
        self.daemon.wait(timeout=10)
        for src in (self.src_a, self.src_b):
            try:
                src.close()
            except OSError:
                pass
        self.tmp.cleanup()

    def output(self, name):
        path = wait_for(lambda: next((p for p, n in names().items() if n == name and p not in self.before), None))
        self.assertIsNotNone(path, f"dispositivo {name!r} não apareceu\n{self.log.read_text()}")
        dev = evdev.InputDevice(path)
        dev.grab()  # nada do serviço de teste chega à sessão gráfica
        self.grabbed.append(dev)
        return dev

    def click(self, src, button):
        src.write(e.EV_KEY, button, 1)
        src.syn()
        src.write(e.EV_KEY, button, 0)
        src.syn()

    def test_two_mice_with_own_layers_and_independent_disconnect(self):
        self.assertTrue(wait_for(lambda: self.log.read_text().count("Remapeamento ativo") >= 2),
                        self.log.read_text())
        out_a = self.output(f"mousemap: {self.name_a}")
        out_b = self.output(f"mousemap: {self.name_b}")
        right = [(e.EV_KEY, e.BTN_RIGHT, 1), (e.EV_KEY, e.BTN_RIGHT, 0)]

        self.click(self.src_a, e.BTN_SIDE)
        self.assertEqual(read_events(out_a), right)
        self.click(self.src_b, e.BTN_SIDE)  # [mice."B"] sobrescreve
        self.assertEqual(read_events(out_b), [(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_KEY, e.BTN_MIDDLE, 0)])
        self.click(self.src_b, e.BTN_LEFT)  # não mapeado: repassado sem alteração
        self.assertEqual(read_events(out_b), [(e.EV_KEY, e.BTN_LEFT, 1), (e.EV_KEY, e.BTN_LEFT, 0)])

        self.click(self.src_a, e.BTN_MIDDLE)  # rolagem pelo mouse virtual do próprio mouse A
        self.assertEqual(read_events(out_a), [(e.EV_REL, e.REL_WHEEL, 1), (e.EV_REL, e.REL_WHEEL_HI_RES, 120)])

        self.src_b.close()  # mouse B "desconecta"
        self.assertTrue(wait_for(lambda: "Mouse desconectado" in self.log.read_text()), self.log.read_text())
        self.click(self.src_a, e.BTN_SIDE)  # A continua funcionando
        self.assertEqual(read_events(out_a), right)


if __name__ == "__main__":
    unittest.main()
