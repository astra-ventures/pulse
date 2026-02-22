# Pulse HTTP API Reference

Pulse exposes a simple HTTP API for monitoring and control. All endpoints return JSON.

**Base URL:** `http://localhost:9720` (configurable via `api.port` in config)

---

## Endpoints

### GET /health

**Purpose:** Health check for monitoring systems (Prometheus, uptime bots, etc.)

**Response:**
```json
{
  "status": "healthy",
  "uptime": 3642
}
```

**Fields:**
- `status` (string): Always "healthy" if daemon is running
- `uptime` (int): Seconds since daemon started

**Status codes:**
- `200 OK`: Daemon is healthy
- (No response): Daemon is down

**Example:**
```bash
curl http://localhost:9720/health
```

---

### GET /state

**Purpose:** Inspect current drive pressures, sensors, config

**Response:**
```json
{
  "drives": {
    "goals": {
      "pressure": 3.24,
      "last_addressed": 1708524180,
      "sources": ["goals.json"]
    },
    "curiosity": {
      "pressure": 1.87,
      "last_addressed": 1708522400,
      "sources": ["curiosity.json"]
    }
  },
  "sensors": {
    "filesystem": {
      "last_change": 1708524000,
      "changed_files": ["memory/2026-02-21.md"]
    },
    "conversation": {
      "active": false,
      "last_activity": 1708520000
    },
    "system": {
      "memory_mb": 42,
      "disk_free_gb": 127
    }
  },
  "config": {
    "drives": {
      "trigger_threshold": 5.0
    },
    "openclaw": {
      "min_trigger_interval": 1800,
      "max_turns_per_hour": 10
    }
  },
  "uptime": 3642,
  "version": "0.2.3"
}
```

**Use cases:**
- Dashboard display (show current drive pressures)
- Debugging (why did Pulse trigger? Check drive values)
- Tuning (too sensitive? Raise threshold)

**Example:**
```bash
curl http://localhost:9720/state | jq '.drives'
```

---

### POST /feedback

**Purpose:** Decay drive pressure after agent addresses a drive

**Request body:**
```json
{
  "drives_addressed": ["goals", "curiosity"],
  "outcome": "success",
  "summary": "Completed goal #7, explored new research topic"
}
```

**Fields:**
- `drives_addressed` (array[string], required): Which drives were addressed
- `outcome` (string, required): "success", "partial", or "failure"
- `summary` (string, optional): Human-readable description (for logs)

**Response:**
```json
{
  "decayed": {
    "goals": {
      "before": 6.23,
      "after": 3.12,
      "decay_amount": 3.11
    },
    "curiosity": {
      "before": 4.87,
      "after": 2.44,
      "decay_amount": 2.43
    }
  }
}
```

**Decay rules:**
- `success`: 50% decay (pressure × 0.5)
- `partial`: 25% decay (pressure × 0.75)
- `failure`: 0% decay (pressure unchanged)

**Status codes:**
- `200 OK`: Feedback processed
- `400 Bad Request`: Missing required fields or invalid outcome

**Example:**
```bash
curl -X POST http://localhost:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "drives_addressed": ["goals"],
    "outcome": "success",
    "summary": "Shipped InvoiceFlow landing page"
  }'
```

---

### POST /trigger

**Purpose:** Manually trigger Pulse (force an agent turn, bypassing threshold)

**Request body:**
```json
{
  "reason": "manual override",
  "drives": ["goals"]
}
```

**Fields:**
- `reason` (string, required): Why you're forcing a trigger (for audit logs)
- `drives` (array[string], optional): Which drives to emphasize in trigger message

**Response:**
```json
{
  "triggered": true,
  "webhook_response": {
    "status": 200,
    "sessionKey": "sess_abc123"
  }
}
```

**Status codes:**
- `200 OK`: Trigger sent to OpenClaw
- `429 Too Many Requests`: Rate limit exceeded (respect `min_trigger_interval`)
- `503 Service Unavailable`: OpenClaw webhook unreachable

**Example:**
```bash
curl -X POST http://localhost:9720/trigger \
  -H "Content-Type: application/json" \
  -d '{"reason": "testing new config", "drives": ["system"]}'
```

---

### GET /config

**Purpose:** Retrieve current configuration (useful for debugging, backups)

**Response:**
```json
{
  "drives": {
    "trigger_threshold": 5.0,
    "categories": {
      "goals": {
        "weight": 1.0,
        "sources": ["goals.json"]
      }
    }
  },
  "sensors": { ... },
  "openclaw": { ... },
  "evaluator": { ... }
}
```

**Status codes:**
- `200 OK`: Config returned

**Example:**
```bash
curl http://localhost:9720/config > pulse-config-backup.json
```

---

### POST /config

**Purpose:** Update configuration at runtime (for self-modification or external tuning)

**Request body:**
```json
{
  "drives.trigger_threshold": 6.5,
  "sensors.filesystem.poll_interval": 120
}
```

**Response:**
```json
{
  "updated": true,
  "changes": {
    "drives.trigger_threshold": {
      "old": 5.0,
      "new": 6.5
    },
    "sensors.filesystem.poll_interval": {
      "old": 60,
      "new": 120
    }
  },
  "restart_required": false
}
```

**Guardrails:**
- Only fields in `mutator.allowed_fields` can be changed
- Changes respect `mutator.guardrails` (min/max values)
- All changes logged to `mutator.audit_log`

**Status codes:**
- `200 OK`: Config updated
- `400 Bad Request`: Invalid field or value outside guardrails
- `403 Forbidden`: Mutation disabled (`mutator.enabled: false`)

**Example:**
```bash
curl -X POST http://localhost:9720/config \
  -H "Content-Type: application/json" \
  -d '{"drives.trigger_threshold": 7.0}'
```

---

### GET /metrics

**Purpose:** Prometheus-compatible metrics (for monitoring dashboards)

**Response (text/plain):**
```
# HELP pulse_uptime_seconds Daemon uptime
# TYPE pulse_uptime_seconds counter
pulse_uptime_seconds 3642

# HELP pulse_drive_pressure Current drive pressure by category
# TYPE pulse_drive_pressure gauge
pulse_drive_pressure{drive="goals"} 3.24
pulse_drive_pressure{drive="curiosity"} 1.87

# HELP pulse_triggers_total Total triggers sent
# TYPE pulse_triggers_total counter
pulse_triggers_total 42

# HELP pulse_feedback_total Total feedback received by outcome
# TYPE pulse_feedback_total counter
pulse_feedback_total{outcome="success"} 28
pulse_feedback_total{outcome="partial"} 10
pulse_feedback_total{outcome="failure"} 4
```

**Use with Prometheus:**
```yaml
scrape_configs:
  - job_name: 'pulse'
    static_configs:
      - targets: ['localhost:9720']
    metrics_path: '/metrics'
```

**Example:**
```bash
curl http://localhost:9720/metrics
```

---

## Rate Limiting

Pulse enforces rate limits to prevent runaway triggers:

1. **Cooldown:** `min_trigger_interval` (default: 1800s / 30 min)
   - No trigger within X seconds of last trigger
   - Applies to both automatic and manual (`/trigger`) triggers

2. **Hourly cap:** `max_turns_per_hour` (default: 10)
   - Sliding 1-hour window
   - Resets continuously (not on the hour)

**Bypass:** None. Rate limits are hard-coded for safety. To increase, edit `config/pulse.yaml` and restart.

---

## Error Responses

All errors return JSON:

```json
{
  "error": "descriptive error message",
  "code": "ERROR_CODE"
}
```

**Common errors:**

- `400 Bad Request`: Invalid request body or missing fields
- `403 Forbidden`: Action not allowed (e.g., mutation disabled)
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Daemon bug (check logs)
- `503 Service Unavailable`: OpenClaw webhook unreachable

---

## Authentication

**Current:** None (Pulse is localhost-only)

**Future (v0.3+):** Optional API key authentication for remote access:

```yaml
api:
  auth_enabled: true
  api_key: "your-secret-key"
```

Then:
```bash
curl -H "Authorization: Bearer your-secret-key" http://localhost:9720/state
```

---

## WebSocket Support

**Status:** Not yet implemented (planned for v0.4)

**Use case:** Real-time drive pressure updates for dashboards

**Proposed:**
```javascript
const ws = new WebSocket('ws://localhost:9720/stream');
ws.onmessage = (event) => {
  const state = JSON.parse(event.data);
  console.log('Drive pressure:', state.drives);
};
```

---

## Client Libraries

**Official:** None yet (contributions welcome!)

**Example Python client:**
```python
import requests

class PulseClient:
    def __init__(self, base_url="http://localhost:9720"):
        self.base_url = base_url
    
    def health(self):
        return requests.get(f"{self.base_url}/health").json()
    
    def state(self):
        return requests.get(f"{self.base_url}/state").json()
    
    def feedback(self, drives, outcome, summary=""):
        return requests.post(f"{self.base_url}/feedback", json={
            "drives_addressed": drives,
            "outcome": outcome,
            "summary": summary
        }).json()
    
    def trigger(self, reason, drives=None):
        return requests.post(f"{self.base_url}/trigger", json={
            "reason": reason,
            "drives": drives or []
        }).json()

# Usage
pulse = PulseClient()
print(pulse.health())
pulse.feedback(["goals"], "success", "Completed task #7")
```

---

## Integration Examples

### Dashboard (Live Drive Pressure)

```javascript
// Poll /state every 5 seconds, update UI
setInterval(async () => {
  const res = await fetch('http://localhost:9720/state');
  const data = await res.json();
  
  document.getElementById('goals-pressure').textContent = 
    data.drives.goals.pressure.toFixed(2);
  document.getElementById('curiosity-pressure').textContent = 
    data.drives.curiosity.pressure.toFixed(2);
}, 5000);
```

### Uptime Monitor (Healthcheck)

```bash
#!/bin/bash
# cron: */5 * * * * /path/to/pulse-healthcheck.sh

if ! curl -sf http://localhost:9720/health > /dev/null; then
  echo "Pulse is down!" | mail -s "Pulse Health Alert" you@example.com
fi
```

### Custom Sensor (External Trigger)

```python
# Example: GitHub webhook → Pulse trigger
from flask import Flask, request
import requests

app = Flask(__name__)

@app.route('/github-webhook', methods=['POST'])
def github_webhook():
    event = request.json
    if event['action'] == 'opened' and 'pull_request' in event:
        # New PR opened → trigger Pulse
        requests.post('http://localhost:9720/trigger', json={
            'reason': f'New PR: {event["pull_request"]["title"]}',
            'drives': ['goals']
        })
    return '', 200

app.run(port=8080)
```

---

## Changelog

- **v0.2.3:** Added `/config` POST endpoint for runtime updates
- **v0.2.0:** Added `/feedback` endpoint for drive decay
- **v0.1.0:** Initial API (`/health`, `/state`, `/trigger`)

---

## Support

Questions? Open an issue: [github.com/jcap93/pulse/issues](https://github.com/jcap93/pulse/issues)
