#!/usr/bin/env python3
"""Synthetic plant + independent guardian process for container fault tests.

Runs in its OWN container so it survives controller crashes, hangs and
network partitions — the role a physical safety permit plays. Reuses the
latched, default-deny ToyInhibit from ni_offline.simulation. Everything here
is illustrative: no real thermal model, wiring, relay or safety certification.

UDP :47000  controller protocol: text (runtime/src/hal_udp.c) or 48-byte
            binary frames of 6 float64 for Simulink UDP blocks. MEAS replies
            stream every 10 ms; their first field acknowledges the seq of the
            latest command accepted (round-trip time / loss detection).
HTTP :8080  GET / (dashboard), GET /status, GET /history,
            POST /operator-reset (simulated button),
            POST /sensor-fault?on=1|0 (fault injection). Simulation only.
"""

from __future__ import annotations

import json
import math
import os
import socket
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ni_offline.simulation import AMBIENT_C, GUARD_STALE_MS, SETPOINT_C, Heartbeat, ToyInhibit

TICK_MS = 10
BIN_FMT = "<6d"                 # binary frame: 6 little-endian float64
BIN_SIZE = struct.calcsize(BIN_FMT)
HISTORY_EVERY_TICKS = 100       # 1 sample per second
HISTORY_LEN = 600               # 10 minutes
WEB = Path(__file__).with_name("web")
# Fixed allow-list: URL name -> (file, content type). Paths never come from the request.
STATIC = {
    "brand.css": (WEB / "brand.css", "text/css"),
}
INDEX = WEB / "index.html"


class Plant:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.guard = ToyInhibit()
        self.temperature_c = AMBIENT_C
        self.cmd_heater = 0.0
        self.cmd_blower = 1.0
        self.eff_heater = 0.0
        self.eff_blower = 1.0
        self.sensor_fault = False
        self.reset_requested = False
        self.reset_results: list[dict] = []
        self.trips: list[dict] = []
        self.peer: tuple[str, int] | None = None
        self.peer_binary = False
        self.last_boot: int | None = None
        self.last_seq = 0
        self.controller_running = False
        self.controller_fault = False
        self.packets = 0
        self.start = time.monotonic()
        self.max_energized_after_last_hb_ms = 0
        # Longest time the heater stayed energized after the last valid heartbeat.
        self.history: deque = deque(maxlen=HISTORY_LEN)
        self.ticks = 0

    def now_ms(self) -> int:
        return int((time.monotonic() - self.start) * 1000)

    def status(self) -> dict:
        with self.lock:
            g = self.guard
            return {
                "mode": "SYNTHETIC_CONTAINER_SIMULATION",
                "now_ms": self.now_ms(),
                "latched": g.latched,
                "reason": g.reason,
                "last_hb_ms": g.last_seen_ms,
                "controller_boot": self.last_boot,
                "controller_seq": self.last_seq,
                "controller_running": self.controller_running,
                "controller_fault": self.controller_fault,
                "packets": self.packets,
                "temperature_c": round(self.temperature_c, 3),
                "cmd_heater": self.cmd_heater,
                "eff_heater": self.eff_heater,
                "eff_blower": self.eff_blower,
                "sensor_fault": self.sensor_fault,
                "trips": list(self.trips),
                "reset_results": list(self.reset_results),
                "guard_stale_ms": GUARD_STALE_MS,
                "max_energized_after_last_hb_ms": self.max_energized_after_last_hb_ms,
                "setpoint_c": SETPOINT_C,
            }

    def _parse_cmd(self, data: bytes) -> tuple | None:
        """Text "CMD boot seq running fault heater blower" or a 48-byte binary
        frame of 6 little-endian float64 (for Simulink UDP blocks). Replies use
        the format of the last packet received. HELLO only registers the peer."""
        if len(data) == BIN_SIZE and not data.startswith((b"CMD", b"HELLO")):
            self.peer_binary = True
            boot, seq, running, fault, heater, blower = struct.unpack(BIN_FMT, data)
            if not all(math.isfinite(v) for v in (boot, seq, heater, blower)):
                return None
            return int(boot), int(seq), running >= 0.5, fault >= 0.5, heater, blower
        self.peer_binary = False
        parts = data.decode(errors="replace").split()
        if len(parts) != 7 or parts[0] != "CMD":
            return None
        try:
            boot, seq = int(parts[1]), int(parts[2])
            heater, blower = float(parts[5]), float(parts[6])
        except ValueError:
            return None
        if not (math.isfinite(heater) and math.isfinite(blower)):
            return None
        return boot, seq, parts[3] == "1", parts[4] == "1", heater, blower

    def run(self, sock: socket.socket) -> None:
        next_t = time.monotonic()
        while True:
            next_t += TICK_MS / 1000
            heartbeat = None
            while True:
                try:
                    data, addr = sock.recvfrom(512)
                except BlockingIOError:
                    break
                self.peer = addr
                cmd = self._parse_cmd(data)
                if cmd is None:
                    continue
                boot, seq, running, fault, heater, blower = cmd
                heartbeat = Heartbeat(boot, seq, running, fault)
                with self.lock:
                    self.cmd_heater = min(1.0, max(0.0, heater))
                    self.cmd_blower = min(1.0, max(0.0, blower))
                    self.last_boot, self.last_seq = boot, seq
                    self.controller_running, self.controller_fault = running, fault
                    self.packets += 1
            with self.lock:
                self._tick(heartbeat)
            if self.peer is not None:
                t = float("nan") if self.sensor_fault else self.temperature_c
                ok = 0 if self.sensor_fault else 1
                if self.peer_binary:
                    msg = struct.pack(BIN_FMT, self.last_seq, t, t, t, t, ok)
                else:
                    msg = f"MEAS {self.last_seq} {t:.4f} {t:.4f} {t:.4f} {t:.4f} {ok}\n".encode()
                try:
                    sock.sendto(msg, self.peer)
                except OSError:
                    pass
            time.sleep(max(0.0, next_t - time.monotonic()))

    def _tick(self, heartbeat: Heartbeat | None) -> None:
        now = self.now_ms()
        g = self.guard
        was_latched = g.latched
        g.tick(now, heartbeat, sensor_ok=not self.sensor_fault, airflow_ok=True)
        if self.reset_requested and heartbeat is not None:
            self.reset_requested = False
            ok = g.manual_reset(now, sensor_ok=not self.sensor_fault, airflow_ok=True)
            self.reset_results.append({"t_ms": now, "accepted": ok})
        if g.latched and not was_latched:
            self.trips.append({"t_ms": now, "reason": g.reason, "last_hb_ms": g.last_seen_ms})
        # Simulated physical override: latched => heater OFF, blower MAX.
        self.eff_heater = 0.0 if g.latched else self.cmd_heater
        self.eff_blower = 1.0 if g.latched else self.cmd_blower
        if self.eff_heater > 0 and g.last_seen_ms is not None:
            self.max_energized_after_last_hb_ms = max(
                self.max_energized_after_last_hb_ms, now - g.last_seen_ms)
        self.ticks += 1
        if self.ticks % HISTORY_EVERY_TICKS == 0:
            self.history.append({"t_ms": now, "temperature_c": round(self.temperature_c, 3),
                                 "eff_heater": self.eff_heater, "latched": g.latched})
        dt = TICK_MS / 1000
        cooling = self.eff_blower * (self.temperature_c - AMBIENT_C) / 10.0
        self.temperature_c += dt * (2.0 * self.eff_heater - cooling)


PLANT = Plant()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, ctype: str) -> None:
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache" if ctype.startswith("text/html") else "max-age=3600")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/status":
            self._send(200, PLANT.status())
        elif path == "/history":
            with PLANT.lock:
                self._send(200, {"setpoint_c": SETPOINT_C, "samples": list(PLANT.history)})
        elif path in ("/", "/index.html"):
            self._file(INDEX, "text/html; charset=utf-8")
        elif path.startswith("/static/") and (entry := STATIC.get(path[len("/static/"):])):
            self._file(*entry)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/operator-reset":
            with PLANT.lock:
                PLANT.reset_requested = True
            self._send(202, {"requested": True})
        elif url.path == "/sensor-fault":
            on = parse_qs(url.query).get("on", ["1"])[0] == "1"
            with PLANT.lock:
                PLANT.sensor_fault = on
            self._send(200, {"sensor_fault": on})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_: object) -> None:
        pass


def main() -> None:
    # Loopback by default; the container sets PLANT_BIND=0.0.0.0 so peers on the
    # compose network can reach it (host exposure is decided by compose ports).
    bind = os.environ.get("PLANT_BIND", "127.0.0.1")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind, 47000))
    sock.setblocking(False)
    threading.Thread(target=PLANT.run, args=(sock,), daemon=True).start()
    ThreadingHTTPServer((bind, 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
