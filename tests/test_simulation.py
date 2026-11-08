"""Fault-injection regression for a synthetic model, not NI or a real safety case."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ni_offline.replay import inspect_capture  # noqa: E402
from ni_offline.simulation import Heartbeat, SCENARIOS, ToyController, ToyInhibit, simulate  # noqa: E402


class ToySimulationTests(unittest.TestCase):
    def values(self, scenario):
        capture, summary = simulate(scenario)
        return [sample["values"] for sample in capture["samples"]], summary

    def test_all_scenarios_are_deterministic_and_valid_synthetic_capture(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                capture, summary = simulate(scenario)
                self.assertEqual((capture, summary), simulate(scenario))
                self.assertEqual(capture["provenance"]["source_kind"], "synthetic")
                self.assertFalse(summary["hardware_access"])
                self.assertFalse(summary["actuation"])
                self.assertFalse(summary["independent_physical_protection_proven"])
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "capture.json"
                    path.write_text(json.dumps(capture))
                    report = inspect_capture(path)
                    self.assertEqual(report["sample_count"], 36)
                    self.assertEqual(report["evidence_classification"], "synthetic_fixture")
                    self.assertEqual(report["period_ms"]["median"], 100)

    def test_initial_state_is_disarmed_then_explicit_simulated_reset(self):
        values, summary = self.values("baseline")
        self.assertEqual(values[0]["heater_after_inhibit_sim"], 0)
        self.assertEqual(values[0]["blower_after_inhibit_sim"], 100)
        self.assertEqual(values[0]["inhibit_latched"], 1)
        self.assertEqual(values[1]["inhibit_latched"], 0)
        self.assertGreater(values[1]["heater_after_inhibit_sim"], 0)
        self.assertFalse(summary["final_inhibit_latched"])

    def test_crash_hold_last_exposes_hazard_then_latches_until_manual_reset(self):
        values, summary = self.values("crash-restart")
        self.assertGreater(values[9]["heater_reference"], 0)
        self.assertEqual(values[10]["heater_reference"], values[9]["heater_reference"])
        self.assertEqual(values[10]["controller_alive"], 0)
        self.assertEqual(values[13]["heater_after_inhibit_sim"], 0)
        self.assertEqual(values[13]["blower_after_inhibit_sim"], 100)
        self.assertEqual(values[20]["controller_alive"], 1)
        self.assertGreater(values[22]["heater_reference"], 0)
        self.assertTrue(all(v["heater_after_inhibit_sim"] == 0 for v in values[13:]))
        self.assertTrue(summary["final_inhibit_latched"])
        self.assertEqual(summary["final_inhibit_reason"], "HEARTBEAT_STALE")

    def test_sensor_and_airflow_faults_latch_in_demo(self):
        sensor, sensor_summary = self.values("sensor-fault")
        airflow, airflow_summary = self.values("airflow-loss")
        for values in (sensor, airflow):
            self.assertEqual(values[10]["heater_after_inhibit_sim"], 0)
            self.assertTrue(all(v["heater_after_inhibit_sim"] == 0 for v in values[10:]))
            self.assertTrue(all(v["blower_after_inhibit_sim"] == 100 for v in values[10:]))
        self.assertTrue(sensor_summary["final_inhibit_latched"])
        self.assertTrue(airflow_summary["final_inhibit_latched"])

    def test_network_gap_latches_even_when_demo_controller_stays_alive(self):
        values, summary = self.values("network-loss")
        self.assertEqual(values[13]["heater_after_inhibit_sim"], 0)
        self.assertEqual(values[13]["controller_alive"], 1)
        self.assertTrue(all(v["heater_after_inhibit_sim"] == 0 for v in values[13:]))
        self.assertTrue(summary["final_inhibit_latched"])

    def test_only_explicit_modeled_rearm_clears_latch(self):
        values, summary = self.values("manual-rearm")
        self.assertTrue(all(v["heater_after_inhibit_sim"] == 0 for v in values[13:25]))
        self.assertGreater(values[25]["heater_after_inhibit_sim"], 0)
        self.assertEqual(values[25]["inhibit_latched"], 0)
        self.assertFalse(summary["final_inhibit_latched"])
        self.assertIn({"step": 25, "event": "MODELED_RESET_ACCEPTED"}, summary["events"])

    def test_cli_emits_capture_json_and_reports_synthetic_status(self):
        command = [sys.executable, "-m", "ni_offline", "simulate", "--scenario", "crash-restart"]
        output = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                text=True, capture_output=True, check=False)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(json.loads(output.stdout)["provenance"]["evidence_classification"], "synthetic_fixture")
        command.append("--summary")
        output = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                text=True, capture_output=True, check=False)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertFalse(json.loads(output.stdout)["control_law_matches_labview"])

    def test_modeled_inhibit_rejects_reset_without_fresh_running_heartbeat(self):
        inhibit = ToyInhibit()
        self.assertFalse(inhibit.manual_reset(0, sensor_ok=True, airflow_ok=True))
        inhibit.tick(0, Heartbeat(0, 1, False, False), sensor_ok=True, airflow_ok=True)
        self.assertFalse(inhibit.manual_reset(0, sensor_ok=True, airflow_ok=True))
        inhibit.tick(100, Heartbeat(0, 2, True, False), sensor_ok=True, airflow_ok=True)
        self.assertTrue(inhibit.manual_reset(100, sensor_ok=True, airflow_ok=True))
        inhibit.tick(500, None, sensor_ok=True, airflow_ok=True)
        self.assertTrue(inhibit.latched)
        self.assertEqual(inhibit.reason, "HEARTBEAT_STALE")
        self.assertFalse(inhibit.manual_reset(500, sensor_ok=True, airflow_ok=True))

    def test_modeled_inhibit_detects_duplicate_sequence_and_boot_change(self):
        inhibit = ToyInhibit()
        inhibit.tick(0, Heartbeat(0, 1, True, False), sensor_ok=True, airflow_ok=True)
        self.assertTrue(inhibit.manual_reset(0, sensor_ok=True, airflow_ok=True))
        inhibit.tick(100, Heartbeat(0, 1, True, False), sensor_ok=True, airflow_ok=True)
        self.assertEqual(inhibit.reason, "SEQUENCE_STALLED")
        self.assertTrue(inhibit.latched)
        self.assertFalse(inhibit.manual_reset(100, sensor_ok=True, airflow_ok=True))
        inhibit.tick(200, Heartbeat(0, 2, True, False), sensor_ok=True, airflow_ok=True)
        self.assertTrue(inhibit.manual_reset(200, sensor_ok=True, airflow_ok=True))
        inhibit.tick(300, Heartbeat(1, 1, True, False), sensor_ok=True, airflow_ok=True)
        self.assertEqual(inhibit.reason, "CONTROLLER_RESTART")
        self.assertTrue(inhibit.latched)
        self.assertFalse(inhibit.manual_reset(300, sensor_ok=True, airflow_ok=True))
        inhibit.tick(400, Heartbeat(1, 2, True, False), sensor_ok=True, airflow_ok=True)
        self.assertTrue(inhibit.manual_reset(400, sensor_ok=True, airflow_ok=True))

    def test_toy_controller_restarts_idle_not_armed(self):
        controller = ToyController()
        controller.arm()
        self.assertGreater(controller.step(20, True).sequence, 0)
        self.assertGreater(controller.heater_request, 0)
        controller.crash()
        self.assertIsNone(controller.step(20, True))
        controller.restart()
        hb = controller.step(20, True)
        self.assertFalse(hb.running)
        self.assertEqual(controller.heater_request, 0)
        self.assertEqual(hb.boot, 1)

    def test_unsupported_scenario_fails_without_fallback(self):
        with self.assertRaises(ValueError):
            simulate("production")


if __name__ == "__main__":
    unittest.main()
