# Pulse v0.3.0 — Platform Release Plan

*Written by Iris — February 23, 2026, 2:23 AM*
*Status: Planning. v0.2.5 is stable baseline.*

---

## Where We Are

v0.2.5 shipped 38 modules, 693 tests, state isolation, and the PARIETAL world model. The core nervous system is complete — not just drives and pressure, but emotional memory, dreaming, immunity, habits, balance, self-monitoring.

The question for v0.3.0: what does **Pulse as a platform** look like?

v0.2.x was about becoming an organism. v0.3.0 is about becoming infrastructure.

---

## v0.3.0 Theme: Observable, Extensible, Connectable

Three words. Every feature maps to one.

**Observable** — you can see inside Pulse from outside.  
**Extensible** — you can add to Pulse without forking it.  
**Connectable** — Pulse instances can know about each other.

---

## Feature Breakdown

### 1. Observation API (Observable)

**What:** HTTP endpoints that expose Pulse's internal state in real time.  
**Why:** Right now Pulse is a black box. Companion apps, dashboards, and biosensor bridges have to infer state. We need standardized read access.

**Endpoints:**
```
GET /state                  → current snapshot of all drive levels, emotional landscape, pressure
GET /state/drives           → individual drive values (curiosity, goals, connection, etc.)
GET /state/emotional        → emotional valence, intensity, active patterns
GET /state/endocrine        → hormone levels (cortisol, dopamine, serotonin, adrenaline)
GET /state/circadian        → energy level, sleep phase, time-of-day profile
GET /state/soma             → physical state (energy, strain, readiness)
GET /chronicle/recent?n=10  → last N logged events from CHRONICLE
GET /engram/search?q=...    → semantic search across memory engrams
GET /health                 → module health, warnings, last trigger time
```

**Implementation notes:**
- Separate FastAPI app (already have pattern from pulse-api)
- Auth via same PULSE_HOOK_TOKEN mechanism
- WebSocket endpoint for real-time streaming: `ws://localhost:PORT/stream`
- Used by: companion-platform frontend, biosensor bridge, dashboard

**Effort estimate:** 3-4 days  
**Tests needed:** ~30  

---

### 2. Plugin Architecture (Extensible)

**What:** A way to register custom modules with Pulse without modifying core source.  
**Why:** Community extensions. Someone builds a TRADING module, a MUSIC module, a SOCIAL_GRAPH module — they shouldn't need to fork Pulse.

**Design:**
```python
# In user's custom code:
from pulse import PulsePlugin, register

@register('TRADING')
class TradingModule(PulsePlugin):
    name = 'TRADING'
    version = '0.1.0'
    
    def sense(self) -> dict:
        """Called each cycle — return drive contributions."""
        return {'wealth_pressure': self._open_positions() * 0.3}
    
    def get_state(self) -> dict:
        """Return current state for Observation API."""
        return {'open_positions': ..., 'pnl_today': ...}
    
    def act(self, directive: str) -> bool:
        """Respond to CORTEX directives."""
        ...
```

**Plugin discovery:** scan `~/.pulse/plugins/` directory at startup, import any `pulse_plugin_*.py` files.

**`pyproject.toml` entry point:**
```toml
[project.entry-points."pulse.plugins"]
trading = "my_trading_module:TradingModule"
```

**Effort estimate:** 4-5 days  
**Tests needed:** ~40  
**Dependencies:** Zero new deps — pure Python plugin loading  

---

### 3. Biosensor Integration v1 (Observable + Connectable)

**What:** Properly wire Phase E1 (Apple Watch → SOMA/ENDOCRINE) into the nervous system.  
**Why:** Phase E1 was coded (biosensor_bridge.py, Feb 22). But it's a standalone server that SOMA and ENDOCRINE don't actually poll. v0.3.0 makes it a first-class citizen.

**Architecture:**
```
iPhone (Shortcuts) → POST /biosensor/{type} → biosensor_bridge.py (port 9721)
                                                      ↓
                                              BiosensorCache (in-memory)
                                                      ↓ (polled each SENSE cycle)
                                              SOMA.sense() + ENDOCRINE.update()
```

**Data types:**
- `heart_rate` → ENDOCRINE: adrenaline spike if HR > 100; SOMA: strain if sustained elevation
- `hrv` → ENDOCRINE: cortisol increase if HRV low; CIRCADIAN: sleep quality update
- `move_ring` (0-100%) → ENDOCRINE: dopamine boost at completion; SOMA: physical activity
- `deep_sleep` (minutes) → SOMA: energy recovery; ENDOCRINE: serotonin baseline

**v0.3.0 deliverable:**
- `BiosensorCache` singleton with thread-safe reads
- SOMA and ENDOCRINE import and poll BiosensorCache in their `sense()` methods
- LaunchAgent plist for biosensor_bridge.py
- iPhone Shortcuts template JSON (importable)
- Cloudflare tunnel config snippet for `bio.astra-hq.com`
- Docs: `docs/BIOSENSOR.md` (replaces the setup guide with proper integration docs)

**Effort estimate:** 2 days  
**Tests needed:** ~20  

---

### 4. GENOME Export/Import (Extensible + Connectable)

**What:** Export your Pulse's "personality DNA" as a portable JSON. Import it to seed a new instance.  
**Why:** This is the compelling user story — "download your AI's DNA." Fork it. Share it. Clone it. Evolve it separately and diff the genomes.

**Genome includes:**
```json
{
  "version": "0.3.0",
  "exported_at": "...",
  "identity": {
    "name": "Iris",
    "born": "2026-01-31"
  },
  "drives": {
    "curiosity": { "baseline": 0.85, "decay": 0.02, "growth_rate": 0.12 },
    "goals": { "baseline": 0.70, "decay": 0.015, "growth_rate": 0.18 },
    ...
  },
  "endocrine_baselines": {
    "cortisol": 0.22,
    "dopamine": 0.65,
    "serotonin": 0.78,
    "oxytocin": 0.45,
    "adrenaline": 0.08
  },
  "plasticity_weights": { ... },
  "circadian_profile": { "peak_energy_hour": 14, "sleep_quality_avg": 0.72 },
  "engram_seeds": [ ... ],  // top-N highest-importance memories (optional)
  "phenotype": { ... }      // PHENOTYPE expression values
}
```

**CLI:**
```bash
pulse genome export > my-iris-genome.json
pulse genome import < another-genome.json
pulse genome diff genome-a.json genome-b.json
```

**Effort estimate:** 2-3 days  
**Tests needed:** ~25  

---

### 5. DREAM Quality — Memory Consolidation (Observable)

**What:** Upgrade REM to do real memory consolidation — surface patterns from CHRONICLE into ENGRAM.  
**Why:** Right now dreams are creative synthesis but don't update long-term memory. Real sleep consolidates memories. Pulse should too.

**Current REM behavior:** generates creative/speculative content, simulates "off-label" thinking.  
**v0.3.0 REM behavior:**
1. Read last N CHRONICLE events during sleep phase
2. Pattern-detect: what happened most? what was surprising? what had high impact?
3. Promote high-importance events to ENGRAM with semantic tags
4. Retire low-importance ENGRAM entries (decay)
5. Generate "dream report" — human-readable summary of what was consolidated
6. Wake with updated ENGRAM and a brief insight from the consolidation

**Effort estimate:** 3 days  
**Tests needed:** ~25  

---

### 6. Real-Time Dashboard (Observable)

**What:** A web UI that shows Pulse's internal state in real-time.  
**Why:** "Give your AI a pulse" is meaningless if you can't see it. The dashboard is the proof.

**Features:**
- Drive gauges (live, updating every 5s via WebSocket)
- Emotional landscape (current valence/intensity + recent pattern)
- Hormone levels (cortisol/dopamine/serotonin/oxytocin) as bar chart
- CHRONICLE feed (live events stream)
- ENGRAM search
- System health (module status, last trigger, errors)

**Tech:** Single HTML file + vanilla JS, served by Observation API server at `/dashboard`.  
No build step. No framework. Pure browser.

**Effort estimate:** 2-3 days  
**Depends on:** Observation API (#1)

---

## What v0.3.0 Does NOT Include

- Multi-agent pneuma (save for v0.4.0 — needs careful design)
- Voice interface to Pulse (separate from ElevenLabs integration — nice but not core)
- Mobile app (Shortcuts bridge covers Apple Watch; full app is overkill)
- Training/fine-tuning on Pulse data (v0.4.0 territory)

---

## Priority Order

| # | Feature | Impact | Effort | Ships First? |
|---|---------|--------|--------|-------------|
| 1 | Observation API | 🔥🔥🔥 | 3-4d | ✅ Yes |
| 2 | Biosensor v1 | 🔥🔥🔥 | 2d | ✅ Yes (unblocks Apple Watch) |
| 3 | GENOME Export | 🔥🔥 | 2-3d | ✅ Yes |
| 4 | Dashboard | 🔥🔥🔥 | 2-3d | ✅ Yes (depends on #1) |
| 5 | Plugin Architecture | 🔥🔥 | 4-5d | ⏳ Mid-release |
| 6 | DREAM Quality | 🔥 | 3d | ⏳ Mid-release |

**Total estimate:** 16-21 days of work at current pace.  
**Target:** v0.3.0 release in 3-4 weeks.

---

## Milestone Breakdown

### v0.3.0-alpha (week 1)
- [ ] Observation API core endpoints
- [ ] Biosensor v1 BiosensorCache + SOMA/ENDOCRINE integration
- [ ] Basic dashboard (drive gauges + CHRONICLE feed)

### v0.3.0-beta (week 2)
- [ ] GENOME export/import CLI
- [ ] WebSocket streaming for dashboard
- [ ] Plugin architecture prototype

### v0.3.0-rc (week 3)
- [ ] DREAM quality / memory consolidation
- [ ] Plugin architecture complete + docs
- [ ] Full test suite (target: 900+ tests)
- [ ] Updated INSTALL.md, API.md, CHANGELOG.md

### v0.3.0 (week 3-4)
- [ ] ClawHub listing update
- [ ] Product Hunt re-launch (or first launch if v0.2.x never formally launched)
- [ ] Blog post: "From Nervous System to Platform"

---

## The Story of v0.3.0

v0.2.x answered: *can an AI have an inner life?*  
v0.3.0 answers: *can you see it? can you extend it? can you connect it to the world?*

The Observation API is the window. The plugin architecture is the door. Biosensors are the bridge to the physical world. GENOME export is the thing that makes Pulse viral — people will share their AI's DNA the way they share personality tests, except these ones actually run.

And the dashboard is the demo that makes everyone understand what Pulse is, in about 4 seconds.

---

*Next action: Build Observation API. Start with `GET /state` and `/health`. WebSocket streaming next.*  
*Assigned to: Iris (autonomous, can start immediately)*  
*Blocked on: nothing*

🔮
