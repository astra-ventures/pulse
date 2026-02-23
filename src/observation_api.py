"""
Pulse Observation API — Real-time window into the nervous system.

File-based design: reads state JSON files written by the running daemon.
No coupling to daemon internals — completely decoupled.

Endpoints:
    GET /health                     → system health, uptime, last trigger
    GET /state                      → full current state snapshot
    GET /state/drives               → drive levels (curiosity, goals, etc.)
    GET /state/emotional            → emotional landscape
    GET /state/endocrine            → hormone levels
    GET /state/circadian            → energy, sleep phase, time profile
    GET /state/soma                 → physical/energy state
    GET /chronicle/recent?n=20      → last N CHRONICLE events
    GET /engram/search?q=text       → search memory engrams
    WS  /stream                     → WebSocket live state updates (5s intervals)

Auth: Bearer token via PULSE_OBS_TOKEN env var (falls back to PULSE_HOOK_TOKEN).

Usage:
    python -m pulse.src.observation_api
    # or
    uvicorn pulse.src.observation_api:app --port 9722
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# ── Config ────────────────────────────────────────────────────────────────────

STATE_DIR    = Path(os.environ.get("PULSE_STATE_DIR", Path.home() / ".pulse" / "state"))
OBS_TOKEN    = os.environ.get("PULSE_OBS_TOKEN") or os.environ.get("PULSE_HOOK_TOKEN", "")
OBS_PORT     = int(os.environ.get("PULSE_OBS_PORT", "9722"))
STREAM_INTERVAL = float(os.environ.get("PULSE_OBS_STREAM_INTERVAL", "5.0"))

logger = logging.getLogger("pulse.observation_api")
logging.basicConfig(level=logging.INFO)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pulse Observation API",
    description="Real-time window into the Pulse nervous system.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(authorization: str = Header(default="")):
    if not OBS_TOKEN:
        return  # No token configured — open access (dev mode)
    token = authorization.replace("Bearer ", "").strip()
    if token != OBS_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid observation token")

# ── State reader helpers ──────────────────────────────────────────────────────

def _read_json(filename: str, default: Any = None) -> Any:
    """Read a state JSON file, return default on any error."""
    path = STATE_DIR / filename
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _read_jsonl_tail(filename: str, n: int = 20) -> List[dict]:
    """Read last N lines from a JSONL file."""
    path = STATE_DIR / filename
    try:
        lines = path.read_text().strip().splitlines()
        tail  = lines[-n:]
        result = []
        for line in reversed(tail):
            try:
                result.append(json.loads(line))
            except Exception:
                pass
        return result
    except Exception:
        return []


def _file_age_seconds(filename: str) -> Optional[float]:
    """How old is a state file in seconds? None if missing."""
    path = STATE_DIR / filename
    try:
        return time.time() - path.stat().st_mtime
    except Exception:
        return None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def get_health(_: None = Depends(require_auth)):
    """Pulse daemon health — uptime indicator, module freshness, warnings."""
    # Check drive file age as a proxy for "daemon is running"
    drive_age = _file_age_seconds("drive-performance.json")
    chronicle_age = _file_age_seconds("chronicle.jsonl")

    # Read recent chronicle for warnings
    recent = _read_jsonl_tail("chronicle.jsonl", n=5)
    errors = [e for e in recent if e.get("level") in ("error", "warning")]

    daemon_alive = drive_age is not None and drive_age < 300  # seen in last 5 min

    return {
        "status":        "ok" if daemon_alive else "stale",
        "daemon_alive":  daemon_alive,
        "drive_file_age_seconds":     drive_age,
        "chronicle_file_age_seconds": chronicle_age,
        "recent_errors": errors,
        "state_dir":     str(STATE_DIR),
        "timestamp":     time.time(),
    }


# ── Full snapshot ─────────────────────────────────────────────────────────────

@app.get("/state")
def get_state(_: None = Depends(require_auth)):
    """Full current state snapshot — drives, emotional, endocrine, circadian, soma."""
    return {
        "drives":    _get_drives_data(),
        "emotional": _get_emotional_data(),
        "endocrine": _get_endocrine_data(),
        "circadian": _get_circadian_data(),
        "soma":      _get_soma_data(),
        "timestamp": time.time(),
    }


# ── Individual state subsystems ───────────────────────────────────────────────

def _get_drives_data() -> dict:
    raw = _read_json("drive-performance.json", {})
    drives = raw.get("drives", raw)  # handle both wrapped and flat formats
    return {
        "values":    drives,
        "pressure":  _compute_pressure(drives),
        "timestamp": time.time(),
    }


def _compute_pressure(drives: dict) -> float:
    """Sum of all individual drive values (mirrors daemon pressure calc)."""
    if not drives:
        return 0.0
    values = [v for v in drives.values() if isinstance(v, (int, float))]
    return round(sum(values), 3)


def _get_emotional_data() -> dict:
    raw = _read_json("limbic-state.json", {})
    return {
        "valence":           raw.get("current_valence", 0.0),
        "intensity":         raw.get("current_intensity", 0.5),
        "active_emotion":    raw.get("current_emotion"),
        "recent_pattern":    raw.get("active_pattern"),
        "emotional_memory":  raw.get("recent_memories", [])[:5],
        "timestamp":         time.time(),
    }


def _get_endocrine_data() -> dict:
    raw = _read_json("endocrine-state.json", {})
    hormones = raw.get("hormones", raw)
    return {
        "cortisol":   round(float(hormones.get("cortisol",   0.2)), 4),
        "dopamine":   round(float(hormones.get("dopamine",   0.5)), 4),
        "serotonin":  round(float(hormones.get("serotonin",  0.6)), 4),
        "oxytocin":   round(float(hormones.get("oxytocin",   0.3)), 4),
        "adrenaline": round(float(hormones.get("adrenaline", 0.1)), 4),
        "melatonin":  round(float(hormones.get("melatonin",  0.1)), 4),
        "timestamp":  time.time(),
    }


def _get_circadian_data() -> dict:
    raw = _read_json("circadian-state.json", {})
    return {
        "energy_level":     raw.get("energy_level", 0.5),
        "sleep_phase":      raw.get("sleep_phase", "unknown"),
        "peak_energy_hour": raw.get("peak_energy_hour"),
        "is_resting":       raw.get("is_resting", False),
        "sleep_quality":    raw.get("sleep_quality_avg", 0.5),
        "timestamp":        time.time(),
    }


def _get_soma_data() -> dict:
    raw = _read_json("soma-state.json", {})
    if not raw:
        # SOMA might store differently
        raw = _read_json("nephron-state.json", {})
    return {
        "energy":     raw.get("energy", 0.7),
        "strain":     raw.get("strain", 0.1),
        "readiness":  raw.get("readiness", 0.8),
        "timestamp":  time.time(),
    }


@app.get("/state/drives")
def get_drives(_: None = Depends(require_auth)):
    return _get_drives_data()


@app.get("/state/emotional")
def get_emotional(_: None = Depends(require_auth)):
    return _get_emotional_data()


@app.get("/state/endocrine")
def get_endocrine(_: None = Depends(require_auth)):
    return _get_endocrine_data()


@app.get("/state/circadian")
def get_circadian(_: None = Depends(require_auth)):
    return _get_circadian_data()


@app.get("/state/soma")
def get_soma(_: None = Depends(require_auth)):
    return _get_soma_data()


# ── Chronicle ─────────────────────────────────────────────────────────────────

@app.get("/chronicle/recent")
def get_chronicle_recent(
    n: int = Query(default=20, ge=1, le=200),
    _: None = Depends(require_auth),
):
    """Last N CHRONICLE events, newest first."""
    events = _read_jsonl_tail("chronicle.jsonl", n=n)
    return {"events": events, "count": len(events), "timestamp": time.time()}


# ── Engram (memory search) ────────────────────────────────────────────────────

@app.get("/engram/search")
def search_engrams(
    q: str = Query(default="", min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    _: None = Depends(require_auth),
):
    """Simple text search across memory engrams."""
    raw = _read_json("engram-store.json", {})
    engrams = raw.get("engrams", []) if isinstance(raw, dict) else raw
    if not isinstance(engrams, list):
        return {"results": [], "query": q, "count": 0}

    q_lower = q.lower()
    results = [
        e for e in engrams
        if q_lower in json.dumps(e).lower()
    ][:limit]

    return {"results": results, "query": q, "count": len(results), "timestamp": time.time()}


# ── WebSocket stream ──────────────────────────────────────────────────────────

@app.websocket("/stream")
async def websocket_stream(ws: WebSocket):
    """Real-time state updates every STREAM_INTERVAL seconds."""
    # Lightweight auth via query param (headers not always available in WS)
    token = ws.query_params.get("token", "")
    if OBS_TOKEN and token != OBS_TOKEN:
        await ws.close(code=4001)
        return

    await ws.accept()
    try:
        while True:
            state = {
                "drives":    _get_drives_data(),
                "emotional": _get_emotional_data(),
                "endocrine": _get_endocrine_data(),
                "circadian": _get_circadian_data(),
                "timestamp": time.time(),
            }
            await ws.send_json(state)
            await asyncio.sleep(STREAM_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket stream error: {e}")


# ── Dashboard ─────────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pulse — Nervous System Dashboard</title>
<style>
  :root { --bg: #0a0a0f; --card: #111118; --border: #1e1e2e; --text: #f0f0f5; --dim: #6666a0; --accent: #9d7cd8; --green: #3fb950; --red: #f85149; --amber: #ffcc55; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 1.5rem; }
  h1 { font-size: 1.4rem; font-weight: 500; margin-bottom: 0.25rem; }
  .subtitle { color: var(--dim); font-size: 0.85rem; margin-bottom: 2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; }
  .card-title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.12em; color: var(--dim); margin-bottom: 1rem; }
  .gauge { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; font-size: 0.85rem; }
  .gauge-label { width: 90px; color: var(--dim); }
  .gauge-bar { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .gauge-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
  .gauge-value { width: 40px; text-align: right; font-variant-numeric: tabular-nums; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-green { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot-red   { background: var(--red);   box-shadow: 0 0 6px var(--red); }
  .dot-amber { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
  .chronicle-feed { font-size: 0.78rem; color: var(--dim); line-height: 1.6; max-height: 200px; overflow-y: auto; }
  .chronicle-feed .event { padding: 0.3rem 0; border-bottom: 1px solid var(--border); }
  .chronicle-feed .event:last-child { border-bottom: none; }
  .ts { color: #444466; margin-right: 0.4rem; }
  .updated { font-size: 0.72rem; color: #444466; margin-top: 0.5rem; }
  #status-bar { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1.5rem; font-size: 0.85rem; }
</style>
</head>
<body>
<h1>🔮 Pulse</h1>
<p class="subtitle">Nervous System Dashboard — live state</p>
<div id="status-bar">
  <span class="status-dot" id="status-dot"></span>
  <span id="status-text">Connecting...</span>
</div>
<div class="grid">
  <div class="card" id="drives-card">
    <div class="card-title">Drives</div>
    <div id="drives-content"></div>
    <div class="updated" id="drives-ts"></div>
  </div>
  <div class="card" id="endocrine-card">
    <div class="card-title">Endocrine</div>
    <div id="endocrine-content"></div>
    <div class="updated" id="endocrine-ts"></div>
  </div>
  <div class="card" id="emotional-card">
    <div class="card-title">Emotional</div>
    <div id="emotional-content"></div>
    <div class="updated" id="emotional-ts"></div>
  </div>
  <div class="card" id="circadian-card">
    <div class="card-title">Circadian + Soma</div>
    <div id="circadian-content"></div>
  </div>
</div>
<div class="card" style="margin-bottom:1rem">
  <div class="card-title">Chronicle — Recent Events</div>
  <div class="chronicle-feed" id="chronicle-feed"></div>
</div>
<script>
const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
const BASE  = window.location.origin;
let ws;

function gauge(label, value, color='#9d7cd8') {
  const pct = Math.max(0, Math.min(100, value * 100));
  return `<div class="gauge">
    <span class="gauge-label">${label}</span>
    <div class="gauge-bar"><div class="gauge-fill" style="width:${pct}%;background:${color}"></div></div>
    <span class="gauge-value">${value.toFixed(2)}</span>
  </div>`;
}

function renderDrives(data) {
  const vals = data.values || {};
  const html = Object.entries(vals)
    .sort(([,a],[,b]) => b - a)
    .map(([k, v]) => gauge(k.replace(/_/g,' '), Math.min(v/5, 1), '#9d7cd8'))
    .join('');
  document.getElementById('drives-content').innerHTML = html || '<span style="color:#444466">No data</span>';
  document.getElementById('drives-ts').textContent = 'pressure: ' + (data.pressure || 0).toFixed(2);
}

function renderEndocrine(data) {
  const colors = { cortisol:'#f85149', dopamine:'#9d7cd8', serotonin:'#3fb950', oxytocin:'#7dcfcf', adrenaline:'#ffcc55', melatonin:'#6666a0' };
  const keys = ['dopamine','serotonin','oxytocin','cortisol','adrenaline','melatonin'];
  const html = keys.map(k => gauge(k, data[k] || 0, colors[k] || '#9d7cd8')).join('');
  document.getElementById('endocrine-content').innerHTML = html;
}

function renderEmotional(data) {
  const valence = data.valence || 0;
  const intensity = data.intensity || 0;
  const color = valence > 0 ? '#3fb950' : valence < 0 ? '#f85149' : '#9d7cd8';
  document.getElementById('emotional-content').innerHTML = `
    ${gauge('valence', (valence + 3) / 6, color)}
    ${gauge('intensity', intensity, '#ffcc55')}
    <div style="font-size:0.8rem;color:#6666a0;margin-top:0.5rem">
      ${data.active_emotion ? '● ' + data.active_emotion : '—'}
      ${data.recent_pattern ? ' · ' + data.recent_pattern : ''}
    </div>`;
}

function renderCircadian(data, soma) {
  document.getElementById('circadian-content').innerHTML = `
    ${gauge('energy', data.energy_level || 0.5, '#ffcc55')}
    ${gauge('readiness', soma.readiness || 0.8, '#3fb950')}
    ${gauge('strain', soma.strain || 0.1, '#f85149')}
    <div style="font-size:0.78rem;color:#6666a0;margin-top:0.5rem">Phase: ${data.sleep_phase || '—'}${data.is_resting ? ' (resting)' : ''}</div>`;
}

function renderChronicle(events) {
  const html = (events || []).slice(0, 15).map(e => {
    const ts = e.timestamp ? new Date(e.timestamp * 1000).toLocaleTimeString() : '';
    const msg = (e.message || e.event || JSON.stringify(e)).slice(0, 90);
    return `<div class="event"><span class="ts">${ts}</span>${msg}</div>`;
  }).join('');
  document.getElementById('chronicle-feed').innerHTML = html || '<span style="color:#444466">No events</span>';
}

async function fetchChronicle() {
  try {
    const r = await fetch(`${BASE}/chronicle/recent?n=15`, { headers: TOKEN ? {Authorization:'Bearer '+TOKEN} : {} });
    if (r.ok) { const d = await r.json(); renderChronicle(d.events); }
  } catch(_) {}
}

function connect() {
  const wsUrl = `${BASE.replace('http','ws')}/stream${TOKEN ? '?token='+TOKEN : ''}`;
  ws = new WebSocket(wsUrl);
  ws.onopen  = () => { document.getElementById('status-dot').className = 'status-dot dot-green'; document.getElementById('status-text').textContent = 'Connected'; };
  ws.onclose = () => { document.getElementById('status-dot').className = 'status-dot dot-amber'; document.getElementById('status-text').textContent = 'Reconnecting...'; setTimeout(connect, 3000); };
  ws.onerror = () => { document.getElementById('status-dot').className = 'status-dot dot-red'; };
  ws.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.drives)    renderDrives(d.drives);
      if (d.endocrine) renderEndocrine(d.endocrine);
      if (d.emotional) renderEmotional(d.emotional);
      if (d.circadian || d.soma) renderCircadian(d.circadian || {}, d.soma || {});
    } catch(_) {}
  };
}

connect();
fetchChronicle();
setInterval(fetchChronicle, 10000);
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Real-time Pulse dashboard — no auth (token via ?token=... query param)."""
    return DASHBOARD_HTML


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("pulse.src.observation_api:app", host="0.0.0.0", port=OBS_PORT, reload=False)
