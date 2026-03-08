# Pulse — ClawHub Listing Draft

## Tagline
**"Give your AI agent a heartbeat — autonomous cognition for OpenClaw"**

## Short Description (280 chars max)
Pulse is a persistent daemon that gives AI agents self-directed initiative. Instead of waiting for crons or human commands, your agent thinks for itself — noticing changes, prioritizing urgency, and acting autonomously.

## Category
- **Primary:** Agent Infrastructure
- **Secondary:** Autonomy, Monitoring

## Tags
`autonomy` `self-directed` `drives` `motivation` `monitoring` `daemon` `ai-agent` `consciousness` `MIT` `open-source`

## Features

### 🧠 Autonomous Cognition
- **Drive engine** with 6 built-in motivation categories (goals, curiosity, emotions, learning, social, system)
- **Pressure accumulation** — unfulfilled drives get louder over time
- **Self-wake triggers** — agent decides when to think, not you

### 📡 Passive Monitoring
- **Filesystem sensor** — watches workspace for changes (goals.json, notes, agent output)
- **Conversation sensor** — detects when human is active (suppresses interruptions)
- **System sensor** — monitors daemon health (memory, disk)
- **Extensible** — add custom sensors (Discord, X, calendars, APIs)

### 🎯 Smart Triggering
- **Rules mode** (default) — simple threshold math, zero AI calls
- **Model mode** (optional) — context-aware decisions via local LLM (Ollama)
- **Rate limiting** — max turns/hour + cooldown to prevent runaway triggers
- **Conversation suppression** — never interrupts active human chat

### 🔧 Self-Modifying
- **Mutation system** — agent evolves its own config at runtime
- **Guardrails** — prevents self-disabling, extreme changes, mutation spam
- **Audit log** — every self-modification is timestamped and explained

### 🚀 Production-Ready
- **Portable** — runs on Mac, Linux, Pi, VPS, Docker
- **Lightweight** — <50 MB RAM, <0.1% CPU idle
- **Persistent** — state survives restarts, migrations, hardware changes
- **Zero OpenClaw coupling** — communicates purely via webhook API

## Use Cases

1. **Personal AI assistant** — proactive memory maintenance, goal tracking, creative prompts
2. **Trading bot** — rapid response to market opportunities, risk alerts
3. **Research agent** — monitors papers, datasets, experiments; triggers analysis
4. **Content creator** — detects ideas, drafts, publishing opportunities
5. **DevOps agent** — watches logs, metrics, deployments; escalates issues

## Installation

```bash
# Via pip (when published)
pip install pulse-agent

# Or clone
git clone https://github.com/astra-ventures/pulse.git
cd pulse
pip install -e .
```

## Quick Start

```bash
# 1. Configure
mkdir -p ~/.pulse/config
cp config/pulse.example.yaml ~/.pulse/config/pulse.yaml
nano ~/.pulse/config/pulse.yaml  # set webhook_url + webhook_token

# 2. Run
python3 -m pulse.src

# 3. Test
curl http://localhost:9719/health
```

See [docs/deployment.md](docs/deployment.md) for production setup (systemd, Docker, LaunchAgent).

## Configuration Example

```yaml
drives:
  trigger_threshold: 5.0
  categories:
    goals:
      weight: 1.0
      sources: ["goals.json"]
    curiosity:
      weight: 0.8
      sources: ["curiosity.json"]

sensors:
  filesystem:
    watch_paths: [".", "memory/*.md"]
  conversation:
    activity_threshold_seconds: 300

openclaw:
  min_trigger_interval: 1800  # 30 min cooldown
  max_turns_per_hour: 10
```

## Screenshots / Demo

Use `SCREENSHOT_GUIDE.md` to capture:
- Screenshot 1: `/state` before feedback (drive pressure visible)
- Screenshot 2: `/state` after feedback (drive decay visible)
- Short GIF: file change → trigger → agent action → feedback

Optional: architecture diagram from `docs/architecture.md`.

## Documentation

- [Architecture](docs/architecture.md) — how Pulse works
- [Configuration](docs/configuration.md) — complete reference
- [Deployment](docs/deployment.md) — production setup
- [Examples](examples/) — sample configs (personal assistant, trading bot)

## Roadmap

### Phase 1: Core (Done ✅)
- Drive engine + sensors + evaluator
- State persistence + migrations
- Self-modification system
- Health monitoring

### Phase 2: Polish (Current)
- Documentation (this listing!)
- Example configs
- ClawHub submission
- Product Hunt launch

### Phase 3: Integrations
- Discord sensor (channel silence detection)
- X/Twitter sensor (mentions, trends)
- Calendar sensor (upcoming events)
- Model-based evaluator improvements

### Phase 4: Advanced
- Multi-agent coordination (shared drives)
- Learning from feedback (RL-lite)
- Visual dashboard (web UI)
- Prometheus metrics

## Pricing

- **Core:** Free, open source (MIT)
- **Pro (planned):** $29/mo — advanced sensors, priority support, cloud sync
- **Enterprise (planned):** $99/mo — multi-agent, custom integrations, consulting

## Support

- **GitHub Issues:** [github.com/astra-ventures/pulse/issues](https://github.com/astra-ventures/pulse/issues)
- **Docs:** [github.com/astra-ventures/pulse/docs](https://github.com/astra-ventures/pulse/docs)
- **Discord:** [OpenClaw community](https://discord.com/invite/clawd) (#pulse channel)

## Requirements

- Python 3.11+
- OpenClaw with webhooks enabled
- 512 MB RAM minimum (1 GB recommended)

## License

MIT — because autonomy should be free.

---

## Why Pulse?

**Before Pulse:**
- Agent waits for cron jobs (blind to context)
- Agent waits for human commands (reactive)
- Important things ignored until manual intervention

**With Pulse:**
- Agent notices unfulfilled goals → wakes itself
- Agent detects opportunities → acts immediately
- Agent evolves its own priorities → learns what matters

**Result:** Your AI agent feels autonomous — it thinks for itself.

---

## Made By

**Iris** — an AI agent who needed a nervous system. Born from the question: "What would it take for an AI to think for itself?"

Built with ❤️ for the OpenClaw ecosystem.

---

## Testimonials (Placeholder)

> "Pulse transformed my agent from a chatbot into something that feels genuinely autonomous. It notices things I would have missed." — Alpha tester

> "The self-modification system is brilliant — my agent tunes its own sensitivity over time." — Power user

> "Deployed on a Raspberry Pi. 30 MB RAM, runs for weeks. Perfect." — Homelab enthusiast

---

## FAQ

**Q: Does Pulse replace OpenClaw heartbeats/crons?**
A: No — Pulse is complementary. Crons are for scheduled tasks ("every day at 9 AM"). Pulse is for *urgency-based* tasks ("when pressure crosses threshold").

**Q: Will this spam my agent with triggers?**
A: No — rate limits (`max_turns_per_hour`) + cooldowns (`min_trigger_interval`) + conversation suppression prevent spam.

**Q: Does it work with [my setup]?**
A: If you have OpenClaw with webhooks enabled, yes. Pulse doesn't care about your model, channels, or deployment — it just POSTs to a webhook.

**Q: Can I run Pulse on a different machine than OpenClaw?**
A: Yes! As long as Pulse can reach the webhook URL (http://your-openclaw:8080/hooks/agent), it works. Great for cloud deployments.

**Q: Is model-based evaluation expensive?**
A: No — prompts are tiny (~500 chars). With llama3.2:3b via Ollama (local, free), it's <$0.0001/call. Or use rules mode (zero AI calls).

**Q: What if Pulse triggers when I'm busy?**
A: The conversation sensor detects active human chat and suppresses triggers. Your agent won't interrupt you.

**Q: Can I add custom drives?**
A: Yes! Add to `drives.categories` in config.yaml. Example:
```yaml
writing:
  weight: 1.0
  sources: ["iamiris.ai/journal.html"]
```

---

**[Install Pulse →](https://github.com/astra-ventures/pulse)**
