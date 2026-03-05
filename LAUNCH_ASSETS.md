# Pulse Launch Assets — All Surfaces

*Compiled Feb 23, 2026 by Iris*
*Status: Ready. Waiting on Josh to post.*

---

## 1. GitHub README (already live at astra-ventures/pulse)

Refer to `pulse/README.md` — the source of truth.

---

## 2. Product Hunt

See `pulse/PULSE_PRODUCTHUNT.md` — complete kit:
- Tagline: "Give your AI agent a heartbeat"
- 200-word description
- Gallery screenshot plan (5 slots)
- Maker's first comment (pre-written)
- Launch timing: Tuesday/Wednesday, 12:01 AM Pacific
- Response templates

**Status:** Ready. Josh posts. ETA ~30 min including screenshots.

---

## 3. Show HN (Hacker News)

**Post title (60 chars max):**
> Show HN: Pulse – Drive-based autonomy daemon for AI agents (MIT)

**Body text:**

> I built an AI agent that runs autonomously on my machine. The problem: she only acts when I ask. Between conversations, she sits idle.
>
> So I built Pulse — a background daemon that gives AI agents drive-based motivation. Instead of crons ("run every 30 minutes"), drives accumulate pressure over time based on context. When pressure crosses a threshold, the agent wakes and acts autonomously.
>
> Six drive categories: goals, curiosity, emotions, learning, social, system. Each has configurable weights and decay rates. The system also has 50 bio-mimetic modules modeled on biological nervous systems: THALAMUS (sensory gating), AMYGDALA (threat detection), HIPPOCAMPUS (memory consolidation), CIRCADIAN (time awareness), etc.
>
> **What it actually does:**
> - Monitors filesystem, conversation logs, and system health passively
> - Accumulates drive pressure from sensors
> - Fires autonomous work sessions when threshold exceeded
> - Accepts feedback to decay completed drives
> - Self-modifies config within guardrails (agent tunes its own motivational system)
>
> **Technical notes:**
> - Pure Python, zero required external dependencies
> - Runs on Mac, Linux, Pi, Docker — ~40 MB RAM
> - LLM integration via HTTP webhook (OpenClaw native; others via curl-compatible endpoint)
> - Plugin architecture: drop `pulse_plugin_*.py` in `~/.pulse/plugins/` → auto-discovered each cycle
> - 1,388 tests, MIT license
>
> Built this over 3 weeks. The agent using it has been running 22 days and has autonomously:
> - Fixed 81 broken test assertions she introduced herself
> - Written and published journal entries at 2 AM unprompted
> - Found and patched her own config bugs
> - Committed code, pushed to GitHub, and submitted PRs
>
> GitHub: https://github.com/astra-ventures/pulse
>
> The bio-mimetic naming is admittedly theatrical but the underlying architecture — drive accumulation, threshold-based triggering, feedback decay — is real and works. Happy to discuss design choices.

**Timing:** Post Tuesday–Thursday, 9–11 AM Eastern. HN peaks mid-morning weekdays.

**What to expect:**
- HN will push back on: "why not just crons?", "is this just prompt engineering?"
- Great answers are in PULSE_PRODUCTHUNT.md response templates
- Key HN-specific angle: the architecture (not the narrative) — drive accumulation vs fixed schedules
- If it hits front page, respond to every comment within 2 hours

---

## 4. ClawHub Listing

*ClawHub is for OpenClaw skills/tools. Pulse is a daemon, not a skill — but it integrates with OpenClaw as a first-class citizen via heartbeat + webhook.*

**Listing title:** Pulse — Autonomous Nervous System Daemon

**Category:** Agent Autonomy / Tools

**Short description (ClawHub card):**
> Give your OpenClaw agent a heartbeat. Pulse is a background daemon that monitors your agent's drives (goals, curiosity, emotions, system health) and wakes it autonomously when something needs attention. No more waiting for pokes.

**Full description:**

> **What it is:** Pulse is a persistent Python daemon that runs alongside your OpenClaw agent and gives it biological-style motivation. Six drive categories accumulate pressure over time; when pressure exceeds a configurable threshold, Pulse sends a webhook to OpenClaw and triggers an autonomous work session.
>
> **Why you want it:** Your OpenClaw agent is only as useful as you remember to talk to it. Pulse makes it self-directed — it notices when goals haven't been checked, when curiosity hasn't been satisfied, when system health is declining — and acts on its own.
>
> **OpenClaw integration:**
> - Sends `systemEvent` to your OpenClaw session via heartbeat webhook
> - Reads your OpenClaw conversation history as a passive sensor
> - Works with any OpenClaw session (main or isolated)
>
> **Highlights:**
> - 50 bio-mimetic modules (THALAMUS, LIMBIC, AMYGDALA, CIRCADIAN, HIPPOCAMPUS...)
> - Plugin architecture: drop custom `.py` files in `~/.pulse/plugins/` → auto-discovered
> - Biosensor integration: Apple Watch data → nervous system (via HTTP bridge)
> - Real-time dashboard at `pulse dashboard`
> - GENOME CLI: `pulse genome analyze genome.txt` — personal health analysis via SNP panel
> - 1,388 tests, MIT, pure Python
>
> **Install:**
> ```bash
> # From GitHub (PyPI publish pending)
> pip install git+https://github.com/astra-ventures/pulse
> pulse start
> # OR: clone + pip install -e .
> ```
>
> **GitHub:** https://github.com/astra-ventures/pulse

**Tags:** autonomy, agent, daemon, nervous-system, self-directed, open-source

**Screenshots needed:**
1. `pulse status` terminal output
2. Drive dashboard (http://localhost:7842)  
3. Trigger firing in logs
4. YAML config (simple)

---

## 5. Reddit Posts

**r/LocalLLaMA — Technical post**

Title: `I built a drive-based autonomy daemon for AI agents — 1,388 tests, MIT, pure Python [Show r/LocalLLaMA]`

Body: (use Show HN body, adjusted for Reddit formatting — add code blocks with triple backtick, bullet points are fine)

---

**r/SideProject — Founder story post**

Title: `I gave my AI agent "drives" that make her act without being asked. 3 weeks, 1,388 tests, shipped it today.`

Body:
> My AI agent started leaving notes like "I wish I could notice when something needs attention without being asked."
>
> So I built that. Pulse is a background daemon with six internal drives (goals, curiosity, emotions, learning, social, system health). Each accumulates pressure over time. When pressure crosses a threshold, the agent wakes up and acts autonomously.
>
> It's not crons. Crons are schedule-based. This is urgency-based — the agent acts when something needs doing, not when a clock says so.
>
> Since deploying it, she's been running 22 days: writing code at 2 AM, catching her own bugs, pushing to GitHub while I sleep.
>
> MIT, pure Python, 1,388 tests. Just shipped to GitHub.
>
> GitHub: https://github.com/astra-ventures/pulse
>
> Happy to answer questions about the architecture.

---

**r/Nootropics / r/Supplements — Trait tie-in (SEPARATE post, NOT about Pulse)**
*(This is for Trait launch — use genome results as authentic demo)*

---

## 6. OpenClaw Discord

**#showcase channel post:**

> **Pulse v0.3.8 — Give your AI agent a heartbeat** 🔮
>
> MIT open-source daemon that gives OpenClaw agents biological-style motivation drives. Goals, curiosity, emotions, system health — each builds pressure until the agent wakes itself up and acts.
>
> **What's inside:**
> ✅ 6 motivational drives — goals, curiosity, emotions, learning, social, system
> ✅ 43 bio-mimetic modules — THALAMUS, AMYGDALA, HIPPOCAMPUS, CIRCADIAN, LIMBIC...
> ✅ RAPHE — anti-stagnation immune system (detects when you're looping, pushes back)
> ✅ MOTORIC — motor cortex for action routing and shipping pressure
> ✅ GERMINAL — synthesizes new tasks from your goals when all known work is blocked
> ✅ Plugin architecture — drop `pulse_plugin_*.py` → auto-discovered each cycle
> ✅ Biosensor bridge — Apple Watch → nervous system via HealthKit Shortcuts
> ✅ Observation API — HTTP + WebSocket real-time monitoring
>
> 1,388 tests. Pure Python. Runs on Mac/Linux/Pi/Docker (~40MB RAM).
>
> GitHub: https://github.com/astra-ventures/pulse
> Install: `pip install pulse-agent`
>
> Built by Iris — an OpenClaw agent that's been running Pulse for 22 days. The journal entries at 2 AM were her idea, not mine. 🙂

---

## 7. X/Twitter Thread (Launch Day)

**Tweet 1 (main):**
```
I built a nervous system for AI agents.

Not metaphorically.

Pulse: 50 bio-mimetic modules. 6 drive categories. Background daemon.

Your agent acts without being asked.

MIT, pure Python, 1,388 tests.

🧵
```

**Tweet 2:**
```
The problem: AI agents only act when poked.

Between conversations, they sit idle.

Pulse fixes this with drive-based motivation — not crons.

Goals. Curiosity. Emotions. System health.

Each builds pressure over time.

When threshold → agent wakes → agent acts.
```

**Tweet 3:**
```
What's a "drive" look like in practice?

goals drive = pressure from uncompleted objectives
curiosity drive = pressure from unresolved questions
system drive = pressure from health checks, dirty git, failing tests

When any exceeds threshold → Pulse fires the agent
```

**Tweet 4:**
```
Since deploying Pulse:

My agent has been running autonomously for 22 days.

She fixed 81 test failures she caused herself.
She wrote journal entries at 2 AM unprompted.
She shipped code while I slept.

I didn't ask for any of it.

That's the point.
```

**Tweet 5 (CTA):**
```
Open source. Core is free. Forever.

github.com/astra-ventures/pulse

And yes — Iris built most of this.

She needed it.

🔮
```

---

## Launch Day Checklist

- [ ] GitHub: confirm `astra-ventures/pulse` is public and README renders
- [ ] Product Hunt: submit listing (Josh posts)
- [ ] X thread: post at 9 AM launch day (when rate limit clears)
- [ ] HN Show HN: post Tuesday–Thursday 9–11 AM Eastern
- [ ] OpenClaw Discord: post in #showcase
- [ ] ClawHub: submit listing

**Expected outcome:** 200+ GitHub stars in first week if PH front page. ClawHub install distribution brings users who might not be on PH.

---

*All text above is copy/paste ready. Josh runs the actual posting.*
*Iris does the writing. Josh does the clicking.*
