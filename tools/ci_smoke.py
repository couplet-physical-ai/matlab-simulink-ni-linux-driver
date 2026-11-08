#!/usr/bin/env python3
"""Emit only synthetic CI evidence; never discovers or commands NI hardware."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ni_offline.replay import inspect_capture  # noqa: E402
from ni_offline.simulation import SCENARIOS, simulate  # noqa: E402


def main() -> int:
    results = []
    for scenario in SCENARIOS:
        capture, summary = simulate(scenario)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.json"
            path.write_text(json.dumps(capture, allow_nan=False), encoding="utf-8")
            inspected = inspect_capture(path)
        if (
            inspected["evidence_classification"] != "synthetic_fixture"
            or inspected["hardware_access"] or inspected["actuation"]
            or summary["hardware_access"] or summary["actuation"]
            or summary["independent_physical_protection_proven"]
        ):
            raise AssertionError("simulation provenance or authority boundary changed")
        results.append({
            "scenario": scenario,
            "sample_count": inspected["sample_count"],
            "final_inhibit_latched": summary["final_inhibit_latched"],
            "final_inhibit_reason": summary["final_inhibit_reason"],
            "evidence_classification": inspected["evidence_classification"],
        })
    report = {
        "status": "SYNTHETIC_SOFTWARE_ONLY",
        "hardware_access": False,
        "actuation": False,
        "physical_safety_proven": False,
        "windows_labview_parity_proven": False,
        "scenarios": results,
    }
    destination = ROOT / "build" / "synthetic-ci-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Validated {len(results)} synthetic scenarios; wrote {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
