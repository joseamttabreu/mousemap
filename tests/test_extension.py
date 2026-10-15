"""Extensão do GNOME Shell (extension/focus.js) com gjs, incluindo integração com o mousemapd real.

O daemon de teste roda num barramento D-Bus isolado (dbus-run-session) e procura um mouse que não
existe, então não cria dispositivos virtuais nem toca no mouse de verdade.
"""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_JS = ROOT / "tests" / "extension" / "test_focus.js"


@unittest.skipUnless(shutil.which("gjs"), "gjs não instalado")
class ExtensionTest(unittest.TestCase):
    def run_gjs(self, *args, timeout=60):
        return subprocess.run(["gjs", "-m", str(TEST_JS), *args], capture_output=True, text=True,
                              timeout=timeout, cwd=ROOT)

    def test_focus_logic(self):
        result = self.run_gjs()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session não instalado")
    def test_integration_with_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(textwrap.dedent('''\
                version = 2
                [settings]
                device = "mouse-de-teste-inexistente"
                [apps."org.mozilla.firefox"]
                tilt_left = { keys = "ctrl+shift+TAB" }
                '''))
            script = (
                f'PYTHONPATH="{ROOT / "src"}" GIO_USE_VFS=local "{sys.executable}" -m mousemap.daemon.main '
                f'--config "{config}" 2>"{tmp}/daemon.log" & D=$!; '
                f'for i in $(seq 50); do gdbus introspect --session -d io.github.mousemap.Daemon '
                f'-o /io/github/mousemap >/dev/null 2>&1 && break; sleep 0.1; done; '
                f'gjs -m "{TEST_JS}" --integration; R=$?; kill $D; wait $D; exit $R'
            )
            result = subprocess.run(["dbus-run-session", "--", "sh", "-c", script],
                                    capture_output=True, text=True, timeout=60, cwd=ROOT)
            log = (Path(tmp) / "daemon.log").read_text()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + "\n--- daemon:\n" + log)
        self.assertIn("integração: daemon aplica o perfil do Firefox", result.stdout)


if __name__ == "__main__":
    unittest.main()
