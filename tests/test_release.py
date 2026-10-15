"""Consistência dos metadados de versão e das traduções (M3)."""

import re
import subprocess
import unittest
from pathlib import Path

import mousemap

ROOT = Path(__file__).resolve().parent.parent


class ReleaseTest(unittest.TestCase):
    def test_versions_match(self):
        sources = {
            "meson.build": re.search(r"version: '([^']+)'", (ROOT / "meson.build").read_text()),
            "pyproject.toml": re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M),
            "mousemap.spec": re.search(r"^Version:\s+(\S+)", (ROOT / "packaging/mousemap.spec").read_text(), re.M),
            "metainfo": re.search(r'<release version="([^"]+)"', (ROOT / "data/io.github.mousemap.metainfo.xml").read_text()),
        }
        for name, match in sources.items():
            self.assertIsNotNone(match, name)
            self.assertEqual(match.group(1), mousemap.__version__, name)

    def test_potfiles_cover_translated_modules(self):
        listed = set((ROOT / "po/POTFILES").read_text().split())
        using = {str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py")
                 if re.search(r"^from \.{1,2}i18n import _", p.read_text(), re.M)}
        self.assertEqual(listed, using)

    def test_translations_complete(self):
        for po in (ROOT / "po").glob("*.po"):
            out = subprocess.run(["msgfmt", "--check", "--statistics", "-o", "/dev/null", str(po)],
                                 capture_output=True, text=True, env={"LC_ALL": "C"})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("untranslated", out.stderr, po.name)
            self.assertNotIn("fuzzy", out.stderr, po.name)


if __name__ == "__main__":
    unittest.main()
