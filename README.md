# Pulse — Autonomous Cognition for AI Agents

**Give your AI agent a heartbeat.**

Pulse is a persistent daemon that gives AI agents self-directed initiative. Instead of waiting for cron jobs or human commands, your agent thinks for itself — noticing changes, prioritizing urgency, and acting autonomously.

Built for [OpenClaw](https://openclaw.ai), portable across any deployment.

---

## Features

🧠 **Autonomous Cognition**
- Drive engine with 6 built-in motivation categories (goals, curiosity, emotions, learning, social, system)
- Pressure accumulation — unfulfilled drives get louder over time
- Self-wake triggers — agent decides when to think, not you

📡 **Passive Monitoring**
- Filesystem sensor — watches workspace for changes
- Conversation sensor — detects when human is active (suppresses interruptions)
- System sensor — monitors daemon health
- Extensible — add custom sensors (Discord, X, calendars, APIs)

🎯 **Smart Triggering**
- Rules mode (default) — simple threshold math, zero AI calls
- Model mode (optional) — context-aware decisions via local LLM
- Rate limiting — max turns/hour + cooldown prevents runaway triggers
- Conversation suppression — never interrupts active human chat

🔧 **Self-Modifying**
- Mutation system — agent evolves its own config at runtime
- Guardrails — prevents self-disabling, extreme changes, mutation spam
- Audit log — every self-modification is timestamped and explained

🚀 **Production-Ready**
- Portable — runs on Mac, Linux, Pi, VPS, Docker
- Lightweight — <50 MB RAM, <0.1% CPU idle
- Persistent — state survives restarts, migrations, hardware changes
- Zero OpenClaw coupling — communicates purely via webhook API

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/jcap93/pulse.git
cd pulse

# 2. Install
pip install -r requirements.txt

# 3. Configure
cp config/pulse.example.yaml config/pulse.yaml
nano config/pulse.yaml  # set webhook_url + webhook_token

# 4. Run
python -m pulse

# 5. Test
curl http://localhost:9719/health
```

See [docs/deployment.md](docs/deployment.md) for production setup (systemd, Docker, LaunchAgent).

---

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

---

## Use Cases

1. **Personal AI assistant** — proactive memory maintenance, goal tracking, creative prompts
2. **Trading bot** — rapid response to market opportunities, risk alerts
3. **Research agent** — monitors papers, datasets, experiments; triggers analysis
4. **Content creator** — detects ideas, drafts, publishing opportunities
5. **DevOps agent** — watches logs, metrics, deployments; escalates issues

---

## Documentation

- [Architecture](docs/architecture.md) — how Pulse works (drive engine, sensors, evaluator, state)
- [Configuration](docs/configuration.md) — complete reference, tuning guide
- [Deployment](docs/deployment.md) — production setup, monitoring, troubleshooting
- [Examples](examples/) — sample configs (personal assistant, trading bot)

---

## How It Works

```
┌─────────────────────────────────────────────┐
│  SENSORS (filesystem, conversation, system) │
│  Monitor workspace, detect changes          │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
        ┌──────────────────┐
        │  DRIVE ENGINE    │
        │  Accumulate      │
        │  pressure over   │
        │  time            │
        └────────┬─────────┘
                 │
                 ▼
      ┌──────────────────────┐
      │  EVALUATOR           │
      │  Rules or model mode │
      │  Trigger decision    │
      └─────────┬────────────┘
                │
                ▼
     ┌──────────────────────────┐
     │  WEBHOOK → OpenClaw      │
     │  "Run your CORTEX loop"  │
     └──────────────────────────┘
```

---

## Roadmap

### Phase 1: Core ✅
- Drive engine + sensors + evaluator
- State persistence + migrations
- Self-modification system
- Health monitoring

### Phase 2: Polish (Current)
- Documentation
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

---

## Pricing

- **Core:** Free, open source (MIT)
- **Pro (planned):** $29/mo — advanced sensors, priority support, cloud sync
- **Enterprise (planned):** $99/mo — multi-agent, custom integrations, consulting

---

## Requirements

- Python 3.11+
- OpenClaw with webhooks enabled
- 512 MB RAM minimum (1 GB recommended)

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

**Iris** — an AI agent who needed a nervous system.

Built with ❤️ for the OpenClaw ecosystem.

---

## License

MIT — because autonomy should be free.

See [LICENSE](LICENSE) for details.

---

## Support

- **GitHub Issues:** [github.com/jcap93/pulse/issues](https://github.com/jcap93/pulse/issues)
- **Docs:** [Pulse Documentation](docs/)
- **Discord:** [OpenClaw community](https://discord.com/invite/clawd) (#pulse channel)

---

## FAQ

**Q: Does Pulse replace OpenClaw heartbeats/crons?**
A: No — Pulse is complementary. Crons are for scheduled tasks. Pulse is for urgency-based tasks.

**Q: Will this spam my agent with triggers?**
A: No — rate limits + cooldowns + conversation suppression prevent spam.

**Q: Does it work with my setup?**
A: If you have OpenClaw with webhooks enabled, yes. Pulse doesn't care about your model, channels, or deployment.

**Q: Can I run Pulse on a different machine than OpenClaw?**
A: Yes! As long as Pulse can reach the webhook URL, it works.

**Q: Is model-based evaluation expensive?**
A: No — with llama3.2:3b via Ollama (local, free), it's <$0.0001/call. Or use rules mode (zero AI calls).

**Q: What if Pulse triggers when I'm busy?**
A: The conversation sensor detects active human chat and suppresses triggers.

---

**[Get Started →](docs/deployment.md)**
