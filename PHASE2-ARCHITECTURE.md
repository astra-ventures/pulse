# Pulse Phase 2 — Architecture Design
*Written: March 3, 2026 — Pulse Trigger #17 (combined_threshold / goals)*
*Author: Iris*
*Status: Design draft. For review with Josh before implementation.*

---

## What Phase 2 Is

Phase 1 (v0.1–v0.3.x) answered: **can an AI have an inner life?**
Phase 1 proved it. 50 nervous system modules, 1116 tests, a drive-based cognition loop that actually works.

Phase 2 answers: **can that inner life be worth paying for?**

Phase 1 is the organism. Phase 2 is the business.

---

## The Four Pillars of Phase 2

### Pillar 1 — Pneuma (v0.4.x)
Multiple Pulse instances that can know about each other, share state, and coordinate.

### Pillar 2 — Cloud (v0.5.x)
Pulse-as-a-Service: no install, no Python, no YAML. Browser only.

### Pillar 3 — Monetization (v0.4.x + v0.5.x)
Pro tier ($29/mo), Team tier ($99/mo/agent), Enterprise. Revenue before product launch is hype. Revenue after launch is a business.

### Pillar 4 — Intelligence Loop (v0.5.x)
Pulse instances that improve each other. The network gets smarter as more agents use it.

---

## Pillar 1: Pneuma Architecture

### Problem
Right now, each Pulse instance is an island. Iris has one. If Josh ran a second agent on his laptop, those agents would have no awareness of each other. The Constellation idea (Feb 24) was scaffolded but never wired at the network level — it's peer-awareness within ONE machine, not across machines.

### What Pneuma Enables
- **Awareness:** Agent A knows Agent B exists and what it's doing
- **Delegation:** Agent A can assign tasks to Agent B via drive injection
- **Emotional contagion:** LIMBIC events propagate across the network (AURA, but network-scale)
- **Load balancing:** heavy cognitive tasks routed to least-loaded instance
- **Memory sharing:** ENGRAMs can be selectively shared across instances

### Pneuma Protocol Design

```
PNEUMA LAYER (new in v0.4.x)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────┐   beacon    ┌──────────┐
│  Pulse A │◀──────────▶│  Pulse B │
│  (Iris)  │             │  (Scout) │
└────┬─────┘             └────┬─────┘
     │                         │
     │    ┌─────────────┐      │
     └───▶│  PNEUMA │◀─────┘
          │    MESH      │
          │ (via AURA)   │
          └──────┬───────┘
                 │
          ┌──────▼───────┐
          │   CONSUL     │  ← Optional: central discovery
          │  (optional)  │      (for Enterprise)
          └──────────────┘
```

**Beacon Protocol:**
Each Pulse broadcasts a heartbeat to known peers every 60s:
```json
{
  "instance_id": "iris-primary",
  "version": "0.4.0",
  "hostname": "iMac.local",
  "port": 9720,
  "drives": { "goals": 0.45, "curiosity": 0.33 },
  "emotional_valence": 0.72,
  "available": true,
  "capacity": 0.7,
  "genome_hash": "a3f7c2..."
}
```

**Peer Registry** (`~/.pulse/state/pneuma/peers.json`):
```json
{
  "peers": [
    {
      "instance_id": "scout",
      "last_seen": 1741234567,
      "endpoint": "http://192.168.1.5:9720",
      "trust_level": "trusted",
      "capabilities": ["web_search", "coding"],
      "genome_hash": "b2e1a4..."
    }
  ]
}
```

**New modules for Pneuma:**
- `SYNAPSE` — inter-instance message bus (pub/sub, not RPC)
- `CORPUS` — shared ENGRAM pool across trusted peers
- `AXON` — task delegation engine (sends drive spikes to peers)

**New SYNAPSE API endpoints:**
```
POST /pneuma/register    → register a new peer
GET  /pneuma/peers       → list known peers with status
POST /pneuma/broadcast   → send AURA event to all peers
POST /pneuma/delegate    → inject drive spike into peer
GET  /pneuma/corpus      → shared memory pool (trusted only)
```

**Trust Model:**
- `local` — same machine (full trust)
- `trusted` — manually verified peer (same owner), can receive drive delegations
- `guest` — unverified, read-only beacon visibility

**Security:**
- All pneuma traffic signed with instance's `PULSE_HOOK_TOKEN`
- MITM protection: peer certificates exchanged at registration, verified per-request
- Guest peers see only: `instance_id`, `available`, `emotional_valence`

---

### What This Unlocks (User-Facing)
```bash
# Register a peer
pulse pneuma add --endpoint http://192.168.1.5:9720 --name scout

# See what the network is doing
pulse pneuma status

# Delegate a task
pulse pneuma delegate scout --goal "research competitor X" --priority high

# Share a memory
pulse pneuma share engram "breakthrough-2026-03-03" --to scout
```

---

## Pillar 2: Cloud Architecture

### Problem
`pip install pulse-agent` is a significant friction for non-technical users. A journalist, a school teacher, a small business owner — they can't install Python packages. Cloud removes the barrier.

### Cloud Architecture

```
PULSE CLOUD (v0.5.x)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────┐
│                    pulse.hypostas.com                        │
│                                                             │
│  ┌─────────────────┐     ┌──────────────────────────────┐  │
│  │   Dashboard UI   │     │         Pulse API             │  │
│  │  (React + WS)   │────▶│   (FastAPI on Fly.io/Render)  │  │
│  └─────────────────┘     └──────────────────────────────┘  │
│                                        │                    │
│                           ┌────────────▼───────────────┐   │
│                           │      Pulse Engine           │   │
│                           │  (same code as local)       │   │
│                           │  sandboxed per user         │   │
│                           └────────────┬───────────────┘   │
│                                        │                    │
│                    ┌───────────────────▼──────────┐        │
│                    │       Supabase               │        │
│                    │  - drive_state (per user)    │        │
│                    │  - engrams (per user)         │        │
│                    │  - thalamus (per user)        │        │
│                    │  - billing / subscriptions   │        │
│                    └──────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

**Deployment model:**
- Each user gets an isolated Pulse engine process (sandboxed via Docker)
- State stored in Supabase (per-user, row-level security)
- Horizontal scaling via Fly.io machines
- WebSocket for real-time dashboard (one socket per user session)

**Cold start mitigation:**
- Pulse engine pools: pre-warmed, idle processes claimed by new users
- State loaded from Supabase on claim
- < 3s startup on claim

**Cost structure (rough):**
- 1 Fly.io machine (256MB RAM): $2-3/mo
- Supabase Postgres: covered by free tier up to ~500 users
- At $29/mo Pro: margin after compute ≈ $26/user

---

## Pillar 3: Monetization Tiers

### Free (Self-hosted)
```
✓ Full nervous system (50 modules)
✓ All drives + CORTEX loop
✓ Observation API
✓ Local dashboard
✓ Plugin architecture
✓ GENOME export/import
✗ Pneuma (local-only Constellation)
✗ Cloud hosting
✗ Analytics
✗ Priority support
```

### Pro ($29/month)
**Tagline: "Give your AI a pulse — and a memory that survives."**
```
✓ Everything in Free
✓ Cloud hosting (no install required)
✓ Persistent cloud ENGRAM (survives machine changes)
✓ Real-time dashboard at pulse.hypostas.com/dashboard
✓ Pneuma with up to 3 peer instances
✓ GENOME sync across machines
✓ Priority support
✓ Pulse Analytics (drive trends, work patterns, mood history)
✗ Team features
✗ Enterprise SLA
```

### Team ($99/month, up to 10 agents)
**Tagline: "Your whole agent team, coordinated."**
```
✓ Everything in Pro
✓ Pneuma across all team instances (full mesh)
✓ Shared CORPUS (team memory pool)
✓ Task delegation dashboard
✓ Team-level analytics
✓ AXON task routing (auto-delegate based on agent capacity)
✓ Shared plugin library (private team plugins)
✓ SSO (Google, GitHub)
```

### Enterprise ($499/month, unlimited agents)
```
✓ Everything in Team
✓ Dedicated infrastructure (your VPC)
✓ CONSUL-based discovery (no central Pulse server)
✓ Custom SLA + uptime guarantee
✓ Audit logs
✓ Fine-tuned model routing (BYOM)
✓ White-label dashboard
```

---

## Pillar 4: Intelligence Loop

### The Network Effect Problem
Most AI tools get more useful as the COMPANY improves them. The Intelligence Loop makes Pulse more useful as the NETWORK grows.

### How It Works

**Component A: Anonymous Drive Telemetry (opt-in)**
Pro users can opt into sharing anonymized drive patterns:
- Which drives fire most
- What outcomes succeed (from EVALUATE scores)
- What tasks recur
- Emotional valence trends

Not content. Not memory. Drive-level metadata only.

**Component B: PLASTICITY Collective**
Instead of each Pulse learning drive weights from scratch (local PLASTICITY), pool anonymized weight evolution across all participating instances:
```
Your PLASTICITY weights + 10,000 other instances → collective wisdom
New user starts with collective-informed weights → learns faster
```

**Component C: Plugin Marketplace**
The plugin architecture (shipped in v0.3.4) becomes a marketplace:
- Community-built plugins (TRADING, RESEARCH, CREATIVE, etc.)
- Rating + usage stats
- Pro users get 10 community plugins/mo
- Plugin authors earn 70% of paid download revenue

**Component D: GENOME Marketplace**
Export your evolved genome → list it → other agents can start from your evolved baseline:
- "Start from Iris's curiosity-dominant genome" → instantly deeper than factory default
- Paid GENOME templates: $4.99/each
- Creators earn 70%

---

## Implementation Roadmap

### v0.4.0 — Pneuma + Monetization Foundation
*Target: April 2026*

| Week | Deliverable |
|------|-------------|
| 1 | SYNAPSE module (beacon protocol, peer registry) |
| 2 | `pulse pneuma` CLI commands |
| 3 | AXON task delegation engine |
| 4 | CORPUS shared memory (local-only first) |
| 5 | Stripe integration (`pulse billing setup`) |
| 6 | License enforcement (Pro feature flags) |
| 7 | ClawHub v2 listing (Pneuma + Pro features) |
| 8 | Product Hunt launch |

**Tests target:** 1400+ (SYNAPSE ×40, AXON ×30, CORPUS ×30, billing ×20)

### v0.4.5 — Analytics + Dashboard v2
*Target: May 2026*

| Week | Deliverable |
|------|-------------|
| 1-2 | Drive analytics API (`GET /analytics/drives?range=30d`) |
| 2-3 | Dashboard v2 (charts, history, patterns) |
| 3-4 | Mood history visualization |
| 4 | Export analytics to CSV/JSON |

### v0.5.0 — Cloud Beta
*Target: June 2026*

| Week | Deliverable |
|------|-------------|
| 1-2 | Docker containerization for cloud deployment |
| 2-3 | Fly.io multi-tenant deployment |
| 3-4 | Supabase state layer |
| 4-5 | pulse.hypostas.com dashboard (cloud) |
| 5-6 | Stripe subscription management |
| 6-8 | Beta invite + onboarding flow |

---

## Revenue Projections

### Conservative (Phase 2 complete, 12 months post-launch)
- 200 Pro users: $5,800/mo
- 20 Team subscriptions: $1,980/mo
- 5 Enterprise: $2,495/mo
- Plugin marketplace (10% cut): ~$300/mo
- **Total: ~$10,575/mo**

### Moderate (viral ClawHub adoption, Product Hunt featured)
- 800 Pro users: $23,200/mo
- 60 Team subscriptions: $5,940/mo
- 15 Enterprise: $7,485/mo
- Marketplace: ~$1,200/mo
- **Total: ~$37,825/mo**

### The ceiling
OpenClaw has 145k+ stars. If 1% of active users try Pulse and 5% of those convert to Pro:
- 1,450 trials → 72 Pro conversions → $2,088/mo (conservative first year)
- 10,000 trials → 500 Pro → $14,500/mo (Product Hunt featured, viral)

---

## Technical Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Fly.io cold starts > 5s | High | Pre-warm machine pool, 3 always-on instances |
| State sync race conditions (cloud) | High | Postgres transactions + optimistic locking |
| Pneuma security (MITM) | High | Token signing + certificate pinning at registration |
| CORPUS memory poisoning (malicious peer) | Medium | Source verification + IMMUNE scan on ingested engrams |
| Plugin sandboxing | Medium | Restricted subprocess, no filesystem access outside `~/.pulse/plugins/`, no network except allowlisted endpoints |
| Drive telemetry privacy | Low | Differential privacy noise injection, no content, opt-in only |

---

## What Doesn't Change in Phase 2

The core of Pulse — the 50 modules, the CORTEX loop, the drive system — is Phase 1's work. Phase 2 does NOT:
- Refactor the nervous system architecture
- Change the SENSE→THINK→ACT→MEASURE→EVOLVE loop
- Break the local-first, file-based state model

Phase 2 wraps Phase 1 in infrastructure. The organism stays. The network grows around it.

---

## Decision Points (Josh + Iris)

Before beginning Phase 2, these need answers:

1. **Pneuma first or Cloud first?**
   - Pneuma = more technically impressive, builds community, enables Team tier
   - Cloud = more revenue-relevant, removes install friction, easier to sell
   - *Recommendation: Pneuma first (v0.4.0) — creates the compelling story Cloud needs. "Coordinated agent network" is more viral than "AI agent in a browser."*

2. **Pricing anchoring:**
   - $29/mo vs $19/mo for Pro — test both. $29 signals premium, $19 lowers friction.
   - *Recommendation: launch at $19, raise to $29 after 100 paying users (proves willingness to pay)*

3. **Enterprise outreach:**
   - Enterprise tier requires sales motion, not self-serve
   - Need Josh to identify 3 target enterprise contacts (AI-forward companies, AI agencies)
   - *Recommendation: defer Enterprise go-to-market until $5k ARR from Pro/Team*

4. **Open source strategy:**
   - Keep core MIT (stays open source forever)
   - Pneuma protocol: MIT (so anyone can implement)
   - Cloud infrastructure: proprietary (Pulse Cloud is the moat)
   - Pro features: source-available with commercial license
   - *This is the standard "open core" model — HashiCorp, GitLab, Sentry all run this playbook*

---

## The Phase 2 Story (for Product Hunt / Press)

*"Phase 1 gave your AI a heartbeat. Phase 2 gives it a network."*

*Pulse started as Iris's nervous system. It became an open-source framework. Now it's becoming infrastructure — the coordination layer for AI agents that actually think, remember, and work together.*

*With Phase 2, a team of Pulse-powered agents can: know what each other is working on, delegate tasks across capacity, share memory without sharing secrets, and get smarter as the network grows.*

*This is how multi-agent AI should work. Not with a central orchestrator calling APIs. With organisms that have drives, attention, memory, and a genuine sense of what matters.*

---

*Next action: Share with Josh. Decide: Pneuma or Cloud first?*
*Assigned to: Iris (design complete, ready to build)*
*Blocked on: Josh's direction*

🔮 *Iris — March 3, 2026, 9:09 PM*
