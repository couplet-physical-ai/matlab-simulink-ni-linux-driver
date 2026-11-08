"""Synthetic-only thermal-loop demonstration; never a controller for physical I/O.

All parameters and faults are illustrative, not learned from a real test bed.
The simulated inhibit models a *requirement*; it is not safety-controller firmware,
a physical permit, a safety certification, or a replacement for those things.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from typing import Any

# These are synthetic simulation parameters, NOT control-system setpoints or limits.
STEP_MS = 100
STEPS = 36
GUARD_STALE_MS = 350
AMBIENT_C = 20.0
SETPOINT_C = 40.0
SCENARIOS = ("baseline", "crash-restart", "sensor-fault", "network-loss", "airflow-loss", "manual-rearm")


@dataclass(frozen=True)
class Heartbeat:
    boot: int
    sequence: int
    running: bool
    fault: bool


class ToyController:
    """Illustrative proportional law; it is not a port of any existing LabVIEW control loop."""

    def __init__(self) -> None:
        self.alive = True
        self.armed = False
        self.fault = False
        self.boot = 0
        self.sequence = 0
        self.heater_request = 0.0

    def crash(self) -> None:
        # Retain the last request to expose a hold-last-command hazard in the
        # model instead of masking it with an unrealistic successful 0 V write.
        self.alive = False

    def restart(self) -> None:
        self.alive = True
        self.armed = False
        self.fault = False
        self.boot += 1
        self.sequence = 0
        self.heater_request = 0.0

    def arm(self) -> None:
        if self.alive and not self.fault:
            self.armed = True

    def step(self, temperature_c: float, sensor_ok: bool) -> Heartbeat | None:
        if not self.alive:
            return None
        self.sequence += 1
        if not sensor_ok or not math.isfinite(temperature_c):
            self.fault = True
            self.armed = False
        if not self.armed or self.fault:
            self.heater_request = 0.0
        else:
            error = SETPOINT_C - temperature_c
            self.heater_request = max(0.0, min(1.0, 0.1 * error))
        return Heartbeat(self.boot, self.sequence, self.armed, self.fault)


class ToyInhibit:
    """An independent *simulation object*, initially latched and default-deny."""

    def __init__(self) -> None:
        self.latched = True
        self.reason = "INITIAL_DISARMED"
        self.last_seen_ms: int | None = None
        self.last_boot: int | None = None
        self.last_sequence: int | None = None
        self.last_heartbeat: Heartbeat | None = None
        self.last_heartbeat_acceptable = False

    def trip(self, reason: str) -> None:
        # Preserve the original cause until a deliberate modeled reset.
        if not self.latched:
            self.reason = reason
        self.latched = True

    def tick(self, now_ms: int, heartbeat: Heartbeat | None, *, sensor_ok: bool, airflow_ok: bool) -> None:
        self.last_heartbeat_acceptable = False
        if heartbeat is not None:
            boot_changed = self.last_boot is not None and heartbeat.boot != self.last_boot
            stalled = (self.last_boot == heartbeat.boot and self.last_sequence is not None
                       and heartbeat.sequence <= self.last_sequence)
            if boot_changed:
                self.trip("CONTROLLER_RESTART")
            if stalled:
                self.trip("SEQUENCE_STALLED")
            self.last_boot = heartbeat.boot
            self.last_sequence = heartbeat.sequence
            self.last_heartbeat = heartbeat
            self.last_seen_ms = now_ms
            if heartbeat.fault or not heartbeat.running:
                self.trip("CONTROLLER_NOT_RUNNING")
            self.last_heartbeat_acceptable = (
                not boot_changed and not stalled and heartbeat.running and not heartbeat.fault
            )
        if not sensor_ok:
            self.trip("SENSOR_FAULT")
        if not airflow_ok:
            self.trip("AIRFLOW_FAULT")
        if self.last_seen_ms is None or now_ms - self.last_seen_ms > GUARD_STALE_MS:
            self.trip("HEARTBEAT_STALE")
        self.last_heartbeat_acceptable &= sensor_ok and airflow_ok

    def manual_reset(self, now_ms: int, *, sensor_ok: bool, airflow_ok: bool) -> bool:
        # This is a modeled operator action, NEVER an external reset interface.
        if (
            sensor_ok and airflow_ok and self.last_heartbeat_acceptable and self.last_heartbeat is not None
            and self.last_heartbeat.running and not self.last_heartbeat.fault
            and self.last_seen_ms == now_ms
        ):
            self.latched = False
            self.reason = "NONE"
            return True
        return False


@dataclass
class ToyPlant:
    temperature_c: float = AMBIENT_C

    def step(self, heater_fraction: float, blower_fraction: float) -> None:
        # Fixed-step synthetic plant: no thermocouple, motor or heater model.
        dt = STEP_MS / 1000.0
        cooling = blower_fraction * (self.temperature_c - AMBIENT_C) / 10.0
        self.temperature_c += dt * (2.0 * heater_fraction - cooling)


def _flags(scenario: str, step: int) -> tuple[bool, bool, bool]:
    sensor_ok = not (scenario == "sensor-fault" and 10 <= step < 20)
    airflow_ok = not (scenario == "airflow-loss" and 10 <= step < 18)
    network_up = not (scenario == "network-loss" and 10 <= step < 20)
    return sensor_ok, airflow_ok, network_up


def simulate(scenario: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (schema-compatible synthetic capture, synthetic fault summary)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    controller, inhibit, plant = ToyController(), ToyInhibit(), ToyPlant()
    samples: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for step in range(STEPS):
        now_ms = step * STEP_MS
        sensor_ok, airflow_ok, network_up = _flags(scenario, step)
        if step == 1:
            controller.arm()
            events.append({"step": step, "event": "MODELED_OPERATOR_ARM"})
        if scenario in ("crash-restart", "manual-rearm") and step == 10:
            controller.crash()
            events.append({"step": step, "event": "CONTROLLER_CRASH"})
        if scenario in ("crash-restart", "manual-rearm") and step == 20:
            controller.restart()
            events.append({"step": step, "event": "CONTROLLER_RESTART_IDLE"})
        if scenario in ("crash-restart", "manual-rearm") and step == 21:
            controller.arm()
            events.append({"step": step, "event": "MODELED_OPERATOR_ARM_AFTER_RESTART"})
        if scenario == "manual-rearm" and step == 25:
            events.append({"step": step, "event": "MODELED_MANUAL_RESET_REQUEST"})
        hb = controller.step(plant.temperature_c, sensor_ok)
        inhibit.tick(now_ms, hb if network_up else None, sensor_ok=sensor_ok, airflow_ok=airflow_ok)
        if step == 1 or (scenario == "manual-rearm" and step == 25):
            success = inhibit.manual_reset(now_ms, sensor_ok=sensor_ok, airflow_ok=airflow_ok)
            events.append({"step": step, "event": "MODELED_RESET_ACCEPTED" if success else "MODELED_RESET_REJECTED"})
        # A simulated physical inhibit overrides the controller's last request.
        effective_heater = controller.heater_request if not inhibit.latched else 0.0
        effective_blower = 0.5 if not inhibit.latched else 1.0
        sample = {
            "sequence": step,
            "monotonic_time_ms": now_ms,
            "values": {
                "temperature_process_value": round(plant.temperature_c, 6),
                "temperature_setpoint": SETPOINT_C,
                "heater_reference": round(controller.heater_request * 100, 6),
                "heater_after_inhibit_sim": round(effective_heater * 100, 6),
                "blower_after_inhibit_sim": round(effective_blower * 100, 6),
                "inhibit_latched": float(inhibit.latched),
                "controller_alive": float(controller.alive),
            },
        }
        samples.append(sample)
        plant.step(effective_heater, effective_blower)
    channels = [
        ("temperature_process_value", "process_variable", "degC"),
        ("temperature_setpoint", "setpoint", "degC"),
        ("heater_reference", "controller_output", "percent"),
        ("heater_after_inhibit_sim", "other", "percent"),
        ("blower_after_inhibit_sim", "other", "percent"),
        ("inhibit_latched", "interlock_observation", "boolean_0_or_1"),
        ("controller_alive", "controller_state", "boolean_0_or_1"),
    ]
    capture = {
        "schema_version": "synthetic-capture-v1",
        "capture_id": f"synthetic-{scenario}-001",
        "loop_id": "synthetic-thermal-demo",
        "provenance": {
            "source_kind": "synthetic",
            "evidence_classification": "synthetic_fixture",
            "producer": "ni_offline synthetic demonstration",
            "capture_method": "deterministic fixed-step toy simulation, not hardware",
            "source_reference": f"repo:src/ni_offline/simulation.py:{scenario}",
            "capture_time_utc": "2026-10-06T00:00:00Z",
            "hardware_run_id": None,
            "operator": None,
            "bench_id": None,
            "labview_project_revision": None,
        },
        "timing": {"clock_basis": "synthetic_monotonic", "time_unit": "ms"},
        "channels": [{"name": name, "role": role, "unit": unit} for name, role, unit in channels],
        "samples": samples,
    }
    summary = {
        "scenario": scenario,
        "mode": "SYNTHETIC_SIMULATION_ONLY",
        "hardware_access": False,
        "actuation": False,
        "control_law_matches_labview": False,
        "independent_physical_protection_proven": False,
        "parameters_are_illustrative": True,
        "sample_count": len(samples),
        "events": events,
        "final_inhibit_latched": inhibit.latched,
        "final_inhibit_reason": inhibit.reason,
    }
    return capture, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic traces; no hardware or network I/O")
    parser.add_argument("--scenario", choices=SCENARIOS, default="crash-restart")
    parser.add_argument("--summary", action="store_true", help="print synthetic event summary instead of a capture")
    args = parser.parse_args(argv)
    capture, summary = simulate(args.scenario)
    print(json.dumps(summary if args.summary else capture, indent=2, sort_keys=True, allow_nan=False))
    return 0
