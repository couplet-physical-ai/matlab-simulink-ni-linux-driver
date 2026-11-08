"""Fail-closed, non-actuating inspector for synthetic/replay traces.

No hardware adapter exists here. In particular a ``controller_output`` channel is
an observed value from a capture, never a command to be executed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = "synthetic-capture-v1"
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ROLES = {
    "process_variable", "setpoint", "controller_output", "controller_state",
    "interlock_observation", "other",
}
TOP = {"schema_version", "capture_id", "loop_id", "provenance", "timing", "channels", "samples"}
PROVENANCE = {
    "source_kind", "evidence_classification", "producer", "capture_method",
    "source_reference", "capture_time_utc", "hardware_run_id", "operator",
    "bench_id", "labview_project_revision",
}


class InvalidCapture(ValueError):
    """The input does not satisfy this offline, non-hardware subset of the capture schema."""


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCapture(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise InvalidCapture(f"non-finite JSON constant: {value}")


def _fields(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise InvalidCapture(f"{name}: expected exactly {sorted(expected)}")
    return value


def _identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise InvalidCapture(f"{name}: invalid identifier")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise InvalidCapture(f"{name}: expected finite number")
    return float(value)


def _string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidCapture(f"{name}: expected nonempty string")


def inspect_capture(path: Path, max_gap_ms: float = 250.0) -> dict[str, Any]:
    """Validate and summarize a local synthetic/replay capture, without executing it.

    ``max_gap_ms`` is a *simulation-only* stale-input threshold, not a bed
    safety limit. An exceeded gap rejects the trace; no state is persisted.
    """
    if isinstance(max_gap_ms, bool) or not isinstance(max_gap_ms, (int, float)) or not math.isfinite(max_gap_ms) or max_gap_ms <= 0:
        raise InvalidCapture("max_gap_ms must be positive and finite")
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw, object_pairs_hook=_pairs_unique, parse_constant=_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidCapture(f"cannot load local capture: {exc}") from exc
    doc = _fields(doc, TOP, "capture")
    if doc["schema_version"] != SCHEMA:
        raise InvalidCapture("unsupported capture schema version")
    _identifier(doc["capture_id"], "capture_id")
    _identifier(doc["loop_id"], "loop_id")
    provenance = _fields(doc["provenance"], PROVENANCE, "provenance")
    kind = provenance["source_kind"]
    # A measured_hardware claim requires an independently authorized validator and a
    # human-approved acquisition procedure; this standalone tool cannot verify it.
    if kind not in ("synthetic", "replay"):
        raise InvalidCapture("only synthetic and replay captures are accepted; measured hardware is refused")
    expected_label = "synthetic_fixture" if kind == "synthetic" else "replay_only"
    if provenance["evidence_classification"] != expected_label:
        raise InvalidCapture("source kind and evidence classification disagree")
    for field in ("producer", "capture_method", "source_reference", "capture_time_utc"):
        _string(provenance[field], field)
    timestamp_text = provenance["capture_time_utc"]
    if not (timestamp_text.endswith("Z") or timestamp_text.endswith("+00:00")):
        raise InvalidCapture("capture_time_utc must use UTC")
    try:
        capture_time = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidCapture("capture_time_utc must be a valid UTC timestamp") from exc
    if capture_time.utcoffset() != timedelta(0):
        raise InvalidCapture("capture_time_utc must use UTC")
    if kind == "synthetic":
        for field in ("hardware_run_id", "operator", "bench_id", "labview_project_revision"):
            if provenance[field] is not None:
                raise InvalidCapture(f"synthetic capture cannot claim {field}")
    else:
        for field in ("hardware_run_id", "operator", "bench_id", "labview_project_revision"):
            if provenance[field] is not None:
                _string(provenance[field], field)
    timing = _fields(doc["timing"], {"clock_basis", "time_unit"}, "timing")
    clock = "synthetic_monotonic" if kind == "synthetic" else "recorded_monotonic"
    if timing != {"clock_basis": clock, "time_unit": "ms"}:
        raise InvalidCapture("invalid clock basis or time unit for source kind")
    channels = doc["channels"]
    if not isinstance(channels, list) or not channels:
        raise InvalidCapture("channels must be a nonempty list")
    names: set[str] = set()
    for channel in channels:
        channel = _fields(channel, {"name", "role", "unit"}, "channel")
        _identifier(channel["name"], "channel.name")
        if channel["name"] in names:
            raise InvalidCapture("duplicate channel name")
        names.add(channel["name"])
        if not isinstance(channel["role"], str) or channel["role"] not in ROLES:
            raise InvalidCapture("invalid channel role")
        _string(channel["unit"], "channel.unit")
    samples = doc["samples"]
    if not isinstance(samples, list) or len(samples) < 2:
        raise InvalidCapture("at least two samples required")
    periods: list[float] = []
    prior_time: float | None = None
    prior_seq: int | None = None
    ranges = {name: [math.inf, -math.inf] for name in names}
    for sample in samples:
        sample = _fields(sample, {"sequence", "monotonic_time_ms", "values"}, "sample")
        seq = sample["sequence"]
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise InvalidCapture("sequence must be a nonnegative integer")
        if prior_seq is not None and seq <= prior_seq:
            raise InvalidCapture("sequence must increase")
        timestamp = _finite(sample["monotonic_time_ms"], "monotonic_time_ms")
        if timestamp < 0:
            raise InvalidCapture("monotonic_time_ms cannot be negative")
        if prior_time is not None:
            gap = timestamp - prior_time
            if gap <= 0:
                raise InvalidCapture("timestamps must strictly increase")
            if gap > max_gap_ms:
                raise InvalidCapture(f"stale input: {gap:g} ms exceeds offline threshold {max_gap_ms:g} ms")
            periods.append(gap)
        values = sample["values"]
        if not isinstance(values, dict) or set(values) != names:
            raise InvalidCapture("sample values must match declared channels exactly")
        for name in names:
            number = _finite(values[name], f"values.{name}")
            ranges[name][0] = min(number, ranges[name][0])
            ranges[name][1] = max(number, ranges[name][1])
        prior_time, prior_seq = timestamp, seq
    return {
        "schema_version": SCHEMA,
        "capture_id": doc["capture_id"],
        "source_kind": kind,
        "evidence_classification": expected_label,
        "mode": "OFFLINE_INSPECTION_ONLY",
        "hardware_access": False,
        "actuation": False,
        "control_law_inferred": False,
        "sample_count": len(samples),
        "period_ms": {"min": min(periods), "median": statistics.median(periods), "max": max(periods)},
        "channel_ranges": {name: {"min": ranges[name][0], "max": ranges[name][1]} for name in sorted(names)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline-only capture inspector")
    parser.add_argument("capture", type=Path, help="local synthetic or replay JSON file")
    parser.add_argument("--max-gap-ms", type=float, default=250.0, help="offline rejection threshold, NOT a safety setting")
    args = parser.parse_args(argv)
    try:
        report = inspect_capture(args.capture, args.max_gap_ms)
    except InvalidCapture as exc:
        print(f"REJECTED (no hardware access): {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0
