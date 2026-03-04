# Pulse — Competitive Landscape

*Last updated: March 4, 2026 (refreshed — ClawHub now at 3,286 skills after ClawHavoc cleanup)*

## ClawHub Ecosystem Context

As of early March 2026:
- **3,286 active skills** on ClawHub (down from 5,705 after ClawHavoc cleanup removed suspicious skills)
- **1.5M+ total downloads** across the platform
- **220k+ GitHub stars** on OpenClaw core

Key ecosystem insight: ClawHub's top skills by downloads skew heavily toward **self-improvement/learning** (not urgency-aware triggering). Pulse occupies genuinely uncrowded territory.

---

## Tier 1: Direct Competitors (Autonomy-adjacent)

### 1. proactive-agent (halthelobster / Hal Stack)
- **Type:** Pure text skill (SKILL.md + .md assets, no code)
- **Version:** 3.1.0 (actively maintained)
- **Approach:** Prompt engineering — WAL protocol, working buffer, compaction recovery, reverse prompting
- **Strengths:** Zero setup, battle-tested patterns, good memory (WAL), works immediately
- **Weaknesses:** Consumes context window, no real-time sensing, no quantifiable drives, fixed heartbeat schedule
- **Category:** Developer (ClawHub + LobeHub)

### 2. Capability Evolver (capability-evolver)
- **Downloads:** 35,581+ — **#1 skill on all of ClawHub**
- **Stars:** 33 (ClawHub) + broader LobeHub presence
- **Type:** Prompt skill — "self-evolution engine"
- **Approach:** Analyzes runtime history to identify improvements, applies protocol-constrained evolution to agent config
- **What it actually does:** Learns from past interactions and proposes improvements to the agent's AGENTS.md / system prompt over time
- **Strengths:** Massive mindshare, simple install, "self-improvement" narrative resonates strongly
- **Weaknesses:** Prompt-based only (context window cost), no real-time environmental sensing, no urgency/pressure mechanics, improvements are suggestions not autonomous actions
- **Positioning overlap with Pulse:** "Evolution" framing is similar but mechanism is different — Capability Evolver improves WHAT the agent knows; Pulse governs WHEN it acts

### 3. self-improving-agent (pskoett / openclaw/skills)
- **Downloads:** 15,962+ — **#4 skill on ClawHub**, **132 stars** (highest-rated skill on platform)
- **Type:** Prompt skill — learning/correction tracker
- **Approach:** Captures learnings, errors, corrections. Enables continuous improvement via structured memory
- **What it actually does:** When something goes wrong or is corrected, records it in a structured way so future sessions benefit
- **Strengths:** High star rating = community trust, simple mechanism, clear value proposition
- **Weaknesses:** Reactive (records after failure), not proactive (doesn't trigger sessions), no urgency mechanics
- **Positioning:** Complementary to Pulse. Pulse decides when to act; self-improving-agent learns from past actions.

### 4. OpenClaw Built-in Heartbeat + Crons
- **Type:** Native OpenClaw feature
- **Approach:** Fixed-interval heartbeat (default 30 min) + scheduled crons
- **Strengths:** Zero additional setup, well-documented, integrated
- **Weaknesses:** Blind to urgency, no context-awareness in timing, no drive/pressure mechanics, no self-modification

---

## Tier 2: Adjacent / Complementary

### auto-skill-hunter
- "Proactively discovers, ranks, and installs high-value ClawHub skills by mining unresolved user needs"
- Adjacent to autonomy but focuses on skill management, not session initiation

### Wacli, ByteRover, ATXP (Top downloads #2, #3, #5)
- CLI/utility tools, no autonomy overlap with Pulse

---

## The Critical Differentiator

**Every competitor lives in the context window. Pulse lives outside it.**

| Feature | Pulse | Capability Evolver | self-improving-agent | proactive-agent | Built-in Heartbeat |
|---------|-------|-------------------|---------------------|-----------------|-------------------|
| Session timing control | ✅ Drive pressure | ❌ Fixed schedule | ❌ None (reactive) | ❌ Fixed schedule | ❌ Fixed schedule |
| Context window cost | ✅ **Zero** | ❌ Consumes context | ❌ Consumes context | ❌ Consumes context | ✅ Minimal |
| Real-time sensing | ✅ Filesystem, system, convo | ❌ None | ❌ None | ❌ None | ❌ None |
| Quantifiable urgency | ✅ Pressure numbers | ❌ Qualitative | ❌ None | ❌ None | ❌ None |
| External daemon | ✅ Python process | ❌ Prompt only | ❌ Prompt only | ❌ Prompt only | ❌ Built-in |
| Self-modification | ✅ Runtime config evolution | ✅ Proposes improvements | ✅ Records learnings | ❌ Static | ❌ Static |
| Conversation suppression | ✅ Active detection | ❌ None | ❌ None | ❌ None | ❌ None |
| Docker/container ready | ✅ Yes | N/A | N/A | N/A | N/A |
| Setup complexity | Medium (daemon + config) | Low (install skill) | Low (install skill) | Low (copy files) | None |

---

## Positioning Strategy

**Don't compete on "self-improvement." Compete on "urgency."**

The top skills (Capability Evolver, self-improving-agent) own the "my agent gets smarter over time" narrative. That's fine — Pulse doesn't do that. Pulse does something orthogonal: **my agent knows WHEN to act without being told**.

The gap in the ecosystem isn't intelligence. It's initiative.

### The Complementarity Story

Pulse + top skills = complete autonomous agent stack:
1. **Pulse** (external daemon) → decides WHEN to trigger based on urgency
2. **Capability Evolver** or **self-improving-agent** → improves HOW the agent thinks over time  
3. **proactive-agent** patterns → structures the CORTEX loop once triggered
4. **Built-in heartbeats** → handles fixed-schedule tasks separately

Pulse doesn't replace these. It's the missing layer — the one that replaces "wait for a cron" with "wake up when something actually matters."

### ClawHub Listing Positioning

**Tagline:** "Your agent's nervous system — knows when to think, not just how"

**Differentiator to emphasize in listing:**
> "Every skill on ClawHub lives in your agent's context window. Pulse lives outside it — a persistent daemon that senses your environment in real-time, accumulates urgency, and wakes your agent when something actually matters. Not on a schedule. On pressure."

**Target first review sentence:**
> "I installed three 'proactive' skills before Pulse. This is the only one that actually solved the problem — my agent no longer waits for crons. It decides."

---

## Market Size Estimate

- **OpenClaw:** 145k+ GitHub stars at time of Pulse design; now 220k+
- **ClawHub:** 3,286 active skills, 1.5M+ downloads
- **Top skills:** 35k downloads for #1 — Pulse's realistic ceiling at launch ~1-5k downloads first 30 days given daemon complexity vs one-click install

**Key insight:** Being a daemon is a moat AND a barrier. Moat because it's genuinely harder to replicate. Barrier because install friction filters for serious users — which is exactly the Pro/Enterprise funnel.

---

## Security Note (March 4, 2026)

OpenClaw's skill injection vulnerability is now documented publicly (DigitalOcean). Pulse's daemon architecture is actually a security advantage: we live outside the trust boundary that prompt-injected skills exploit. Today's GERMINAL injection attempts (7 in one day, all blocked) validate that Pulse's external architecture has meaningful attack resistance that context-window skills inherently cannot.

Worth mentioning in launch docs.
