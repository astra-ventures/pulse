#!/usr/bin/env python3
"""
BIOSENSOR BRIDGE — Phase E1
Receives HealthKit data from iPhone Shortcuts and updates Pulse SOMA/ENDOCRINE state.

Architecture: Apple Watch → HealthKit → iPhone Shortcut → POST here → Pulse state update

Endpoints:
  POST /biosensor/heartrate    { "value": 72, "unit": "bpm" }
  POST /biosensor/hrv          { "value": 45, "unit": "ms" }
  POST /biosensor/activity     { "move": 400, "exercise": 20, "stand": 8, "goal_move": 600 }
  POST /biosensor/sleep        { "stage": "deep|core|rem|awake", "minutes": 90 }
  POST /biosensor/workout      { "type": "start|end", "activity": "running|strength|..." }
  GET  /biosensor/status       Returns current biometric state

Usage:
  python3 biosensor_bridge.py --port 9721 --host 0.0.0.0

Expose via Cloudflare tunnel (existing astra-trading tunnel):
  Add route: api.astra-hq.com/biosensor/* → localhost:9721/biosensor/*

Then iPhone Shortcut POSTs to: https://api.astra-hq.com/biosensor/heartrate
"""

import json
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
import argparse

# ─── Paths ────────────────────────────────────────────────────────────────────

STATE_DIR = Path.home() / ".pulse" / "state"
BIOSENSOR_FILE = STATE_DIR / "biosensor-state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("biosensor_bridge")

# ─── Biometric → Pulse State Mapping ─────────────────────────────────────────

def _load_biosensor_state() -> dict:
    if BIOSENSOR_FILE.exists():
        return json.loads(BIOSENSOR_FILE.read_text())
    return {
        "heart_rate": {"value": None, "ts": None, "zone": None},
        "hrv": {"value": None, "ts": None, "stress_level": None},
        "activity": {"move": 0, "exercise": 0, "stand": 0, "goal_move": 600, "ts": None},
        "sleep": {"stage": None, "minutes": 0, "ts": None},
        "workout": {"active": False, "activity": None, "started": None},
        "last_update": None,
    }


def _save_biosensor_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["last_update"] = time.time()
    BIOSENSOR_FILE.write_text(json.dumps(state, indent=2))


def _hr_zone(bpm: float) -> str:
    """Map heart rate to zone for ENDOCRINE routing."""
    if bpm < 60:
        return "resting"
    elif bpm < 80:
        return "relaxed"
    elif bpm < 100:
        return "moderate"
    elif bpm < 130:
        return "elevated"
    elif bpm < 160:
        return "high"
    else:
        return "max"


def _hrv_stress(ms: float) -> str:
    """Classify HRV into stress level (higher HRV = lower stress)."""
    if ms > 60:
        return "low"
    elif ms > 40:
        return "moderate"
    elif ms > 25:
        return "elevated"
    else:
        return "high"


def update_endocrine_from_biometrics(state: dict):
    """
    Write ENDOCRINE event based on current biometric state.
    This mimics what endocrine.trigger_event() would do, but file-direct.
    """
    endocrine_path = STATE_DIR / "endocrine-state.json"
    if not endocrine_path.exists():
        log.warning("ENDOCRINE state file not found — skipping hormonal update")
        return

    try:
        endo = json.loads(endocrine_path.read_text())
        levels = endo.get("levels", {})
        changed = False

        # Heart rate → adrenaline + cortisol
        hr = state.get("heart_rate", {})
        if hr.get("zone") == "high":
            levels["adrenaline"] = min(1.0, levels.get("adrenaline", 0) + 0.3)
            levels["cortisol"] = min(1.0, levels.get("cortisol", 0.2) + 0.1)
            changed = True
            log.info(f"HR zone=high → adrenaline +0.3, cortisol +0.1")
        elif hr.get("zone") == "resting":
            levels["adrenaline"] = max(0.0, levels.get("adrenaline", 0) - 0.1)
            changed = True

        # HRV → cortisol (low HRV = high stress)
        hrv = state.get("hrv", {})
        if hrv.get("stress_level") == "high":
            levels["cortisol"] = min(1.0, levels.get("cortisol", 0.2) + 0.2)
            changed = True
            log.info(f"HRV stress=high → cortisol +0.2")
        elif hrv.get("stress_level") == "low":
            levels["cortisol"] = max(0.0, levels.get("cortisol", 0.2) - 0.15)
            levels["serotonin"] = min(1.0, levels.get("serotonin", 0.5) + 0.1)
            changed = True
            log.info(f"HRV stress=low → cortisol -0.15, serotonin +0.1")

        # Activity ring completion → dopamine
        activity = state.get("activity", {})
        move = activity.get("move", 0)
        goal = activity.get("goal_move", 600)
        if goal > 0 and move >= goal:
            levels["dopamine"] = min(1.0, levels.get("dopamine", 0.5) + 0.25)
            changed = True
            log.info(f"Move ring closed ({move}/{goal}) → dopamine +0.25")

        if changed:
            endo["levels"] = levels
            endo["last_update"] = time.time()
            endocrine_path.write_text(json.dumps(endo, indent=2))
            log.info("ENDOCRINE state updated from biometrics")

    except Exception as e:
        log.error(f"ENDOCRINE update failed: {e}")


def update_soma_from_biometrics(state: dict):
    """Update SOMA energy/posture based on biometrics."""
    soma_path = STATE_DIR / "soma-state.json"
    if not soma_path.exists():
        log.warning("SOMA state file not found — skipping")
        return

    try:
        soma = json.loads(soma_path.read_text())
        changed = False

        # Workout active → energy spend context
        workout = state.get("workout", {})
        if workout.get("active"):
            soma["posture"] = "active"
            changed = True

        # Sleep → energy replenishment signal
        sleep = state.get("sleep", {})
        if sleep.get("stage") == "deep":
            # Deep sleep = high recovery signal for SOMA
            current_energy = soma.get("energy", 0.8)
            soma["energy"] = min(1.0, current_energy + 0.02)  # gentle recovery
            changed = True
            log.info(f"Deep sleep detected → SOMA energy +0.02")

        if changed:
            soma["last_update"] = time.time()
            soma_path.write_text(json.dumps(soma, indent=2))
            log.info("SOMA state updated from biometrics")

    except Exception as e:
        log.error(f"SOMA update failed: {e}")


# ─── HTTP Handler ──────────────────────────────────────────────────────────────

class BiosensorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info(f"{self.address_string()} - {format % args}")

    def _respond(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _read_body(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        if self.path == "/biosensor/status":
            state = _load_biosensor_state()
            self._respond(200, state)
        elif self.path == "/health":
            self._respond(200, {"status": "ok", "bridge": "biosensor_bridge", "ts": time.time()})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if body is None:
            self._respond(400, {"error": "invalid JSON"})
            return

        state = _load_biosensor_state()
        path = self.path.rstrip("/")

        if path == "/biosensor/heartrate":
            bpm = float(body.get("value", 0))
            zone = _hr_zone(bpm)
            state["heart_rate"] = {"value": bpm, "ts": time.time(), "zone": zone}
            log.info(f"Heart rate: {bpm} bpm → zone={zone}")

        elif path == "/biosensor/hrv":
            ms = float(body.get("value", 0))
            stress = _hrv_stress(ms)
            state["hrv"] = {"value": ms, "ts": time.time(), "stress_level": stress}
            log.info(f"HRV: {ms} ms → stress={stress}")

        elif path == "/biosensor/activity":
            state["activity"] = {
                "move": float(body.get("move", 0)),
                "exercise": float(body.get("exercise", 0)),
                "stand": float(body.get("stand", 0)),
                "goal_move": float(body.get("goal_move", 600)),
                "ts": time.time(),
            }
            log.info(f"Activity: move={body.get('move')}, exercise={body.get('exercise')}, stand={body.get('stand')}")

        elif path == "/biosensor/sleep":
            state["sleep"] = {
                "stage": body.get("stage", "unknown"),
                "minutes": float(body.get("minutes", 0)),
                "ts": time.time(),
            }
            log.info(f"Sleep: stage={body.get('stage')}, minutes={body.get('minutes')}")

        elif path == "/biosensor/workout":
            wtype = body.get("type", "").lower()
            if wtype == "start":
                state["workout"] = {"active": True, "activity": body.get("activity"), "started": time.time()}
                log.info(f"Workout started: {body.get('activity')}")
            elif wtype == "end":
                state["workout"] = {"active": False, "activity": None, "started": None}
                log.info("Workout ended")

        else:
            self._respond(404, {"error": f"unknown endpoint: {path}"})
            return

        _save_biosensor_state(state)
        update_endocrine_from_biometrics(state)
        update_soma_from_biometrics(state)

        self._respond(200, {"status": "ok", "path": path, "ts": time.time()})


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Biosensor Bridge — Phase E1")
    parser.add_argument("--port", type=int, default=9721)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Biosensor bridge starting on {args.host}:{args.port}")
    log.info(f"State dir: {STATE_DIR}")
    log.info("Endpoints: /biosensor/{heartrate,hrv,activity,sleep,workout} | /biosensor/status | /health")

    server = HTTPServer((args.host, args.port), BiosensorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Biosensor bridge stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
