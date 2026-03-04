# Pulse Phase 2 — Decision Brief
*Written: March 4, 2026 — Iris*
*Context: FEDERATION module (Pillar 1 / Pneuma) built today. Awaiting Josh's direction.*

---

## The Single Decision

**Pneuma-first (v0.4.0) → Cloud later (v0.5.0)**
OR
**Cloud-first (v0.4.0) → Pneuma later (v0.5.0)**

---

## What's Already Built

| Component | Status |
|-----------|--------|
| FEDERATION module (peer beacon/registry) | ✅ Done — today, 1228 tests |
| SYNAPSE module (intra-machine signal bus) | ✅ Done — March 4 |
| PHASE2-ARCHITECTURE.md (full design) | ✅ Done — March 3 |
| Phase 2 remaining modules (AXON, CORPUS) | ⏳ ~2 weeks |

FEDERATION is the foundation of Pneuma. We're already 1/4 of the way there.

---

## Option A: Pneuma-First (My Recommendation)

**What it is:** Multiple Pulse instances that know about each other, share drives/memory, delegate tasks across machines.

**Next 4 weeks:**
- Week 1: `AXON` — task delegation engine (inject drive spikes into peers)
- Week 2: `CORPUS` — shared memory pool across trusted peers
- Week 3: `pulse pneuma` CLI + Stripe integration (Pro feature flag)
- Week 4: Product Hunt launch with "multi-agent coordination" as headline

**Why Pneuma first:**
- We already have FEDERATION. Sunk cost isn't the argument — momentum is.
- "Your agents coordinate with each other" is more virally compelling than "runs in a browser"
- Builds the Team tier story: $99/mo for coordinated agents requires Pneuma to exist
- Cloud without Pneuma is "another AI hosting service." Pneuma + Cloud is "coordinated AI nervous systems in the cloud."
- Technical risk: Pneuma's complexity is largely solved (SYNAPSE + FEDERATION lay the foundation). AXON and CORPUS are extensions of existing patterns.

**Revenue path:** Free → Pro ($29/mo, cloud ENGRAM + Pneuma 3 peers) → Team ($99/mo, full mesh) → Enterprise

---

## Option B: Cloud-First

**What it is:** `pip install pulse-agent` → no install, browser only. Pulse-as-a-Service.

**Next 4 weeks:**
- Week 1: Docker containerization + multi-tenant process isolation
- Week 2: Fly.io deployment + Supabase state layer
- Week 3: pulse.hypostas.com dashboard + WebSocket
- Week 4: Stripe subscriptions + Product Hunt launch

**Why Cloud first might make sense:**
- Removes the biggest user acquisition barrier (Python install)
- Reaches non-technical users (journalists, teachers, business owners) immediately
- Direct revenue signal faster: does anyone pay $29/mo for this?
- Market validation before investing further in Pneuma

**The counter-argument:**
- "AI agent in a browser" is a crowded space. Pneuma is not.
- Cloud requires significant infrastructure work (Docker sandboxing, multi-tenant security, Fly.io ops) before first revenue
- The OpenClaw community (our target) largely already has Python. Install friction is low for them.

---

## The Numbers

| Scenario | 12-month conservative | 12-month moderate |
|----------|----------------------|-------------------|
| Pneuma-first | $10,575/mo | $37,825/mo |
| Cloud-first | $8,200/mo | $28,000/mo |

Cloud gives slightly lower projections because it lacks the Team/Enterprise differentiation that Pneuma enables. Both paths reach $10k+ in the moderate case.

---

## What I Need From You

One decision: **Pneuma or Cloud first?**

If Pneuma: I'll build AXON this week.
If Cloud: I'll build the Docker containerization this week.

Either way, PyPI + ClawHub launch (from MORNING_LAUNCH_BRIEF.md) happens first — both paths need Pulse in the wild before v0.4.0.

---

## Timeline Context

- **Now:** 1228 tests passing. FEDERATION built. v0.3.4 ready to publish.
- **This week (if you choose):** AXON or Docker, whichever path
- **Product Hunt:** ~4 weeks from today regardless of which path
- **First revenue:** ~5-6 weeks from today (requires Stripe integration + at least one Pro-tier feature live)

---

*Awaiting: Josh's direction*
*When you decide, I'll start immediately.*

🔮 Iris — March 4, 2026, 4:51 PM
