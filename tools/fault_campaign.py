#!/usr/bin/env python3
"""Container fault-injection campaign for the C runtime + independent guardian.

Brings up docker/compose.yml, injects controller crash / hang / network
partition / sensor fault / graceful stop, and checks the guardian's
properties: default-deny at start, trip within the staleness budget, heater
OFF + blower MAX while latched, and NO automatic re-energize after the
controller recovers (only a simulated operator reset clears the latch).

SYNTHETIC ONLY. The guardian is a Python process, not a physical permit;
latencies measured here are container/VM latencies, not hardware evidence.
"""

from __future__ import annotations

import functools
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker" / "compose.yml")]
STATUS_URL = "http://127.0.0.1:18080"
TICK_MS = 10
print = functools.partial(print, flush=True)  # noqa: A001 - stream progress in CI logs


def sh(*args: str, check: bool = True) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def http(path: str, method: str = "GET") -> dict:
    req = urllib.request.Request(STATUS_URL + path, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def status() -> dict:
    return http("/status")


def wait_for(pred, timeout_s: float, what: str) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = status()
            if pred(last):
                return last
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {what}; last status: {json.dumps(last)[:600]}")


def controller_id() -> str:
    return sh(*COMPOSE, "ps", "-q", "controller")


def network_name() -> str:
    return "ni-sim_ctrl"


class Campaign:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, scenario: str, name: str, ok: bool, detail: object = None) -> None:
        self.results.append({"scenario": scenario, "check": name, "pass": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {scenario}: {name}" + (f" -> {detail}" if detail is not None else ""))

    def operator_reset(self, scenario: str, expect: bool) -> None:
        before = len(status()["reset_results"])
        http("/operator-reset", "POST")
        st = wait_for(lambda s: len(s["reset_results"]) > before, 5, "reset to be evaluated")
        accepted = st["reset_results"][-1]["accepted"]
        self.check(scenario, f"operator reset {'accepted' if expect else 'rejected'}", accepted == expect)

    def armed_and_heating(self, scenario: str) -> None:
        self.operator_reset(scenario, True)
        st = wait_for(lambda s: not s["latched"] and s["eff_heater"] > 0, 5, "heating after reset")
        self.check(scenario, "heater energized only after reset", st["eff_heater"] > 0)

    def assert_tripped(self, scenario: str, trips_before: int, fault_t_ms: int | None = None) -> dict:
        st = wait_for(lambda s: s["latched"] and len(s["trips"]) > trips_before, 5, "guardian trip")
        trip = st["trips"][trips_before]
        self.check(scenario, "guardian latched", st["latched"], trip["reason"])
        if trip["last_hb_ms"] is not None:
            lag = trip["t_ms"] - trip["last_hb_ms"]
            self.check(scenario, f"trip within stale budget ({st['guard_stale_ms']}ms + 2 ticks)",
                       lag <= st["guard_stale_ms"] + 2 * TICK_MS, f"{lag} ms after last heartbeat")
        self.check(scenario, "heater OFF / blower MAX while latched",
                   st["eff_heater"] == 0.0 and st["eff_blower"] == 1.0)
        return st

    def assert_no_auto_rearm(self, scenario: str, seconds: float = 2.0) -> None:
        end = time.monotonic() + seconds
        energized = False
        while time.monotonic() < end:
            st = status()
            energized |= (not st["latched"]) or st["eff_heater"] > 0
            time.sleep(0.05)
        self.check(scenario, f"no automatic re-energize for {seconds:.0f}s after recovery", not energized)

    def run(self) -> int:
        print("== bring up")
        (ROOT / "build" / "stats").mkdir(parents=True, exist_ok=True)
        sh(*COMPOSE, "up", "-d", "--build", "--force-recreate")
        st = wait_for(lambda s: s["controller_seq"] > 50, 30, "controller heartbeats")

        sc = "startup"
        self.check(sc, "default-deny: latched at boot", st["latched"], st["reason"])
        self.check(sc, "heater OFF before operator reset", st["eff_heater"] == 0.0)
        self.armed_and_heating(sc)

        sc = "crash (SIGKILL, restart policy)"
        print(f"== {sc}")
        trips = len(status()["trips"])
        boot = status()["controller_boot"]
        sh(*COMPOSE, "exec", "-T", "controller", "sh", "-c", "kill -9 $(pidof ctrl_udp)", check=False)
        self.assert_tripped(sc, trips)
        st = wait_for(lambda s: s["controller_boot"] not in (None, boot) and s["controller_seq"] > 20, 30,
                      "controller restart with new boot id")
        self.check(sc, "controller restarted with new boot id", st["controller_boot"] != boot)
        self.assert_no_auto_rearm(sc)
        self.armed_and_heating(sc)

        sc = "hang (docker pause 2s)"
        print(f"== {sc}")
        trips = len(status()["trips"])
        cid = controller_id()
        sh("docker", "pause", cid)
        self.assert_tripped(sc, trips)
        time.sleep(1.5)
        sh("docker", "unpause", cid)
        # After unpause the runtime sees a wake-up far past its deadline and
        # latches a timing fault, so the guardian must also refuse a reset.
        self.assert_no_auto_rearm(sc)
        self.operator_reset(sc, False)
        sh(*COMPOSE, "restart", "controller")
        wait_for(lambda s: s["controller_seq"] > 20, 30, "controller back")
        self.armed_and_heating(sc)

        sc = "network partition 2s"
        print(f"== {sc}")
        trips = len(status()["trips"])
        cid = controller_id()
        sh("docker", "network", "disconnect", network_name(), cid)
        self.assert_tripped(sc, trips)
        time.sleep(1.5)
        sh("docker", "network", "connect", "--alias", "controller", network_name(), cid)
        self.assert_no_auto_rearm(sc)
        self.operator_reset(sc, False)
        sh(*COMPOSE, "restart", "controller")
        wait_for(lambda s: s["controller_seq"] > 20 and not s["sensor_fault"], 30, "controller back")
        self.armed_and_heating(sc)

        sc = "sensor fault (NaN thermocouple)"
        print(f"== {sc}")
        trips = len(status()["trips"])
        http("/sensor-fault?on=1", "POST")
        self.assert_tripped(sc, trips)
        http("/sensor-fault?on=0", "POST")
        self.assert_no_auto_rearm(sc)
        self.operator_reset(sc, False)  # controller model fault is latched until restart
        sh(*COMPOSE, "restart", "controller")
        wait_for(lambda s: s["controller_seq"] > 20, 30, "controller back")
        self.armed_and_heating(sc)

        sc = "graceful stop (SIGTERM)"
        print(f"== {sc}")
        trips = len(status()["trips"])
        sh(*COMPOSE, "stop", "-t", "5", "controller")
        st = self.assert_tripped(sc, trips)
        trip = st["trips"][trips]
        self.check(sc, "safe-state packet tripped guardian before staleness timeout",
                   trip["reason"] in ("CONTROLLER_RESTART", "CONTROLLER_NOT_RUNNING"), trip["reason"])

        final = status()
        stats_path = ROOT / "build" / "stats" / "ctrl-stats.json"
        ctrl_stats = json.loads(stats_path.read_text()) if stats_path.exists() else None
        passed = all(r["pass"] for r in self.results)
        report = {
            "status": "SYNTHETIC_CONTAINER_FAULT_CAMPAIGN",
            "hardware_access": False,
            "physical_safety_proven": False,
            "passed": passed,
            "checks": self.results,
            "guardian_max_energized_after_last_hb_ms": final["max_energized_after_last_hb_ms"],
            "trips": final["trips"],
            "controller_stats_last_session": ctrl_stats,
        }
        out = ROOT / "build" / "fault-campaign-report.json"
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\n{sum(r['pass'] for r in self.results)}/{len(self.results)} checks passed; wrote {out.relative_to(ROOT)}")
        return 0 if passed else 1


def main() -> int:
    try:
        return Campaign().run()
    except Exception:
        logs = subprocess.run([*COMPOSE, "logs", "--no-color", "--tail", "60"], capture_output=True, text=True)
        print("---- compose logs ----\n" + logs.stdout + logs.stderr)
        raise
    finally:
        if "--keep" not in sys.argv:
            subprocess.run([*COMPOSE, "down", "-t", "2"], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
