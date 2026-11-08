"""The portable inspection slice never opens a NI device or issues an output."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ni_offline.replay import InvalidCapture, inspect_capture  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "pi-synthetic-capture.json"


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(FIXTURE.read_text())

    def inspect(self, doc, threshold=250):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.json"
            path.write_text(json.dumps(doc))
            return inspect_capture(path, threshold)

    def test_only_offline_report_is_emitted(self):
        report = self.inspect(self.doc)
        self.assertEqual(report["mode"], "OFFLINE_INSPECTION_ONLY")
        self.assertEqual(report["evidence_classification"], "synthetic_fixture")
        self.assertFalse(report["hardware_access"])
        self.assertFalse(report["actuation"])
        self.assertFalse(report["control_law_inferred"])
        self.assertEqual(report["sample_count"], 3)
        self.assertEqual(report["period_ms"], {"min": 100, "median": 100, "max": 100})
        self.assertEqual(report["channel_ranges"]["heater_reference"], {"min": 0, "max": 20})

    def test_cli_on_current_architecture(self):
        result = subprocess.run(
            [sys.executable, "-m", "ni_offline", str(FIXTURE)],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["actuation"])

    def test_replay_label_is_not_hardware_evidence(self):
        doc = copy.deepcopy(self.doc)
        doc["provenance"]["source_kind"] = "replay"
        doc["provenance"]["evidence_classification"] = "replay_only"
        doc["timing"]["clock_basis"] = "recorded_monotonic"
        report = self.inspect(doc)
        self.assertEqual(report["evidence_classification"], "replay_only")
        self.assertFalse(report["hardware_access"])

    def test_refuse_measured_hardware_claim(self):
        self.doc["provenance"]["source_kind"] = "measured_hardware"
        with self.assertRaisesRegex(InvalidCapture, "measured hardware is refused"):
            self.inspect(self.doc)

    def test_refuse_mislabeled_provenance(self):
        self.doc["provenance"]["evidence_classification"] = "measured_hardware_evidence"
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)

    def test_refuse_claimed_synthetic_hardware_run(self):
        self.doc["provenance"]["hardware_run_id"] = "real"
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)

    def test_refuse_stale_input(self):
        self.doc["samples"][1]["monotonic_time_ms"] = 300
        with self.assertRaisesRegex(InvalidCapture, "stale input"):
            self.inspect(self.doc)

    def test_refuse_bad_period_and_sequence(self):
        for value in (0, -1, float("nan")):
            with self.subTest(value=value), self.assertRaises(InvalidCapture):
                self.inspect(self.doc, value)
        self.doc["samples"][1]["sequence"] = 0
        with self.assertRaisesRegex(InvalidCapture, "sequence must increase"):
            self.inspect(self.doc)

    def test_refuse_missing_extra_and_nonfinite_values(self):
        for values in ({"temperature": 20}, {"temperature": 20, "heater_reference": 0, "extra": 1},
                       {"temperature": True, "heater_reference": 0},
                       {"temperature": float("nan"), "heater_reference": 0}):
            with self.subTest(values=values), self.assertRaises(InvalidCapture):
                doc = copy.deepcopy(self.doc)
                doc["samples"][0]["values"] = values
                self.inspect(doc)

    def test_refuse_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "duplicate.json"
            p.write_text('{"schema_version": 1, "schema_version": 2}')
            with self.assertRaisesRegex(InvalidCapture, "duplicate JSON key"):
                inspect_capture(p)

    def test_refuse_bad_timestamp_and_role(self):
        self.doc["provenance"]["capture_time_utc"] = "not-a-date"
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)
        self.doc["provenance"]["capture_time_utc"] = "2026-10-06T00:00:00Z"
        self.doc["channels"][0]["role"] = {"unexpected": "mapping"}
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)

    def test_refuse_unknown_fields_and_no_samples(self):
        self.doc["hardware_device"] = "cdaq"
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)
        del self.doc["hardware_device"]
        self.doc["samples"] = []
        with self.assertRaises(InvalidCapture):
            self.inspect(self.doc)


if __name__ == "__main__":
    unittest.main()
