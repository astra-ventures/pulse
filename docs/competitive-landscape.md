# Pulse — Competitive Landscape

*Last updated: February 20, 2026*

## Direct Competitors

### proactive-agent (halthelobster / Hal Stack)
- **Type:** Pure text skill (SKILL.md + .md assets, no code)
- **Version:** 3.1.0 (actively maintained, last update Feb 20 2026)
- **Installs:** ~14 (LobeHub marketplace)
- **Approach:** Prompt engineering — WAL protocol, working buffer, compaction recovery, reverse prompting
- **Strengths:** Zero setup, works immediately, good memory patterns (WAL), battle-tested patterns
- **Weaknesses:** Consumes context window, no real-time sensing, no quantifiable drive mechanics, relies entirely on heartbeat schedule for proactivity
- **Category:** Developer (LobeHub)

### OpenClaw Built-in Heartbeat + Crons
- **Type:** Native OpenClaw feature
- **Approach:** Fixed-interval heartbeat (default 30 min) + scheduled crons
- **Strengths:** Zero additional setup, well-documented, integrated
- **Weaknesses:** Blind to urgency (fixed schedule), no context-awareness in timing, no drive/pressure mechanics, no self-modification

## Pulse Differentiators

| Feature | Pulse | proactive-agent | Built-in Heartbeat |
|---------|-------|-----------------|-------------------|
| Urgency-aware timing | ✅ Drive pressure | ❌ Fixed schedule | ❌ Fixed schedule |
| Real-time sensing | ✅ Filesystem, system, conversation | ❌ None | ❌ None |
| Context window cost | ✅ Zero (external daemon) | ❌ Consumes context | ✅ Minimal |
| Self-modification | ✅ Runtime config evolution | ❌ Static | ❌ Static |
| Quantifiable state | ✅ Pressure numbers, history | ❌ Qualitative | ❌ None |
| Conversation suppression | ✅ Active detection | ❌ None | ❌ None |
| Setup complexity | Medium (daemon + config) | Low (copy files) | None |
| Docker/container ready | ✅ Yes | N/A | N/A |

## Positioning

**Pulse is NOT a replacement for proactive-agent or heartbeats.** It's a different layer:

- **proactive-agent** = "How should my agent think?" (prompt patterns)
- **OpenClaw heartbeat** = "When should my agent wake up?" (fixed schedule)  
- **Pulse** = "What does my agent want to do, and how urgently?" (motivation engine)

Pulse can coexist with proactive-agent patterns. The ideal stack:
1. Pulse (external daemon) decides WHEN to trigger based on urgency
2. proactive-agent patterns (or custom CORTEX) decide HOW to think once triggered
3. OpenClaw crons handle fixed-schedule tasks separately

## Launch Positioning (ClawHub)

**Don't compete with proactive-agent. Complement it.**

Tagline options:
- "Your agent's nervous system — knows when to think, not just how"
- "Urgency-driven triggers for OpenClaw — beyond crons and heartbeats"

**Key differentiator to emphasize:** Pulse is infrastructure (a daemon), not a prompt skill. It adds a capability that doesn't exist in the ecosystem: context-aware, urgency-based triggering.
