"""Structural regression checks: public runtime has no NI output or install path."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExportBoundaryTests(unittest.TestCase):
    def test_only_synthetic_udp_hal_is_present(self):
        self.assertEqual(
            {p.name for p in (ROOT / "runtime" / "src").glob("hal_*.c")},
            {"hal_udp.c"},
        )
        makefile = (ROOT / "runtime" / "Makefile").read_text()
        self.assertIn("ctrl_udp", makefile)
        self.assertNotIn("ctrl_daqmx", makefile)
        self.assertNotIn("-lnidaqmx", makefile)

    def test_no_live_output_or_installer_path(self):
        self.assertFalse((ROOT / "stand-kit").exists())
        self.assertFalse((ROOT / "docker" / "ni-daqmx").exists())
        self.assertFalse((ROOT / "docs" / "reference" / "target-inventory.md").exists())
        for path in (ROOT / "runtime" / "src").glob("*.c"):
            text = path.read_text()
            for forbidden in ("DAQmxWrite", "DAQmxCreateAO", "DAQmxCreateDO", "NIDAQmx.h"):
                with self.subTest(path=path.name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_export_text_has_no_private_project_terms_or_doubled_words(self):
        # Split the literals so this regression check does not flag itself.
        project_terms = re.compile(
            r"\b(?:ga" + r"p\s*0|ul" + r"tron|at" + r"om test)\b", re.IGNORECASE
        )
        doubled_words = re.compile(
            r"\b(?:cap" + r"ture\s+capture|synthetic\s+synt" + r"hetic)\b",
            re.IGNORECASE,
        )
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):  # Non-text assets are not prose.
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(project_terms.search(text), "private project term")
                self.assertIsNone(doubled_words.search(text), "doubled descriptor")

    def test_offline_schema_and_warning_are_not_hardware_authority(self):
        inspector = (ROOT / "src" / "ni_offline" / "replay.py").read_text()
        self.assertIn('SCHEMA = "synthetic-capture-v1"', inspector)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("SIMULATION ONLY", readme)
        self.assertIn("NOT APPROVED FOR REAL HARDWARE", readme)


if __name__ == "__main__":
    unittest.main()
