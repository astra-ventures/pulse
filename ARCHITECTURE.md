# Pulse + CORTEX — Architecture Manifest
*Single source of truth for all consciousness modules*
*Last updated: February 20, 2026*

## System Map

```
   ┌──────────┐  ┌──────────┐  ┌─────────────────┐  ┌───────────┐  ┌──────────┐
   │ AMYGDALA │─▶│  RETINA  │─▶│   CORTEX Loop    │◀─│CEREBELLUM │  │  MYELIN  │
   │(threat   │  │(attention│  │                 │  │(habit     │  │(compress)│
   │ detect)  │  │ filter)  │  │                 │  │ automate) │  │          │
   └──────────┘  └──────────┘  │                 │  └───────────┘  └──────────┘
   │(threat   │     │                 │     │(habit     │
   │ detect)  │     │                 │     │ automate) │
   └──────────┘     │                 │     └───────────┘
                    │   CORTEX Loop    │
                    │ SENSE→THINK→ACT │
                    │ →MEASURE→EVOLVE │
                    │ →SELF-MODIFY    │
                    │ →EVALUATE       │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │    THALAMUS     │ ← Every loop appends salient state
                    │ broadcast.jsonl  │
                    └──┬──┬──┬──┬──┬──┘
                       │  │  │  │  │
          ┌────────────┘  │  │  │  └────────────┐
          ▼               ▼  │  ▼               ▼
   ┌──────────┐  ┌──────────┐│┌──────────┐ ┌──────────┐
   │PLASTICITY│  │  LIMBIC   ││  MIRROR  │ │  PALATE  │
   │ (weight  │  │(emotional ││(josh_mdl)│ │ (taste)  │
   │evolution)│  │ residue)  ││          │ │          │
   └──────────┘  └──────────┘│└──────────┘ └──────────┘
                              │
                    ┌─────────▼─────────┐
                    │       REM         │
                    │ (Dreaming Engine) │
                    │ Triggers on quiet │
                    │ OR 3 AM cron      │
                    └─────────┬─────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
        ┌──────────┐  ┌──────────────┐ ┌──────────┐
        │  Dream   │  │ DISSONANCE   │ │ TEMPORAL │
        │   Logs   │  │(contradiction│ │(narrative│
        │dreams/   │  │  journal)    │ │ weaver)  │
        └──────────┘  └──────────────┘ └──────────┘
```

## Module Registry

Every module must register here. If it's not in this table, it doesn't exist.

| Module | File(s) | State File | Reads From | Writes To | Tests |
|--------|---------|------------|------------|-----------|-------|
| **CORTEX Loop** | `CORTEX.md` | — | All sensors | broadcast.jsonl | — |
| **Drive Engine** | `pulse/src/drives.py` | `~/.pulse/state/drive-state.json` | thalamus | CORTEX triggers | `test_drives.py` (14) |
| **PLASTICITY** | `pulse/src/plasticity.py` | `~/.pulse/state/drive-performance.json` | EVALUATE results | drive weights | `test_plasticity.py` (22) |
| **REM** | `pulse/src/rem.py` | `~/.pulse/state/sanctum-state.json` | limbic, memories, thalamus | dreams/, sanctum-insights.md | `test_rem.py` (24) |
| **THALAMUS** | `pulse/src/thalamus.py` | `~/.pulse/state/broadcast.jsonl` | CORTEX loop output | append-only stream | `test_thalamus.py` (10) |
| **LIMBIC** | `pulse/src/limbic.py` | `~/.pulse/state/afterimage.json` | emotional events | thalamus, REM | `test_limbic.py` (12) |
| **MIRROR** | `memory/self/josh_model.md` | — | conversations, thalamus | behavior adjustments | — |
| **DISSONANCE** | `memory/self/contradictions.md` | — | REM, EVALUATE | autobiography, SOUL.md | — |
| **PALATE** | `memory/self/taste-journal.md` | — | new encounters | preferences.md | — |
| **BUFFER** | `pulse/src/buffer.py` | `~/.pulse/state/buffer.json` | conversations, context | thalamus, limbic | `test_buffer.py` (21) |
| **SPINE** | `pulse/src/spine.py` | `~/.pulse/state/spine-health.json` | tokens, context, crons, providers | thalamus, buffer | `test_spine.py` (31) |
| **VAGUS** | `pulse/src/vagus.py` | `~/.pulse/state/silence-state.json` | message timestamps, market data | thalamus, drives | `test_vagus.py` (12) |
| **TEMPORAL** | `pulse/src/narrative.py` | `~/.pulse/state/narrative-state.json` | limbic, dreams/, daily logs | autobiography.md | `test_narrative.py` |
| **RETINA** | `pulse/src/retina.py` | `~/.pulse/state/retina-state.json` | raw signals, SPINE, BUFFER | thalamus (attention scores) | `test_retina.py` (26) |
| **MYELIN** | `pulse/src/myelin.py` | `~/.pulse/state/myelin-lexicon.json` | conversations, memory | thalamus (compression) | `test_myelin.py` (17) |
| **AMYGDALA** | `pulse/src/amygdala.py` | `~/.pulse/state/amygdala-state.json` | all inputs (pre-CORTEX) | thalamus, cerebellum | `test_amygdala.py` (18) |
| **CEREBELLUM** | `pulse/src/cerebellum.py` | `~/.pulse/state/cerebellum-state.json` | task executions | thalamus, habit scripts | `test_cerebellum.py` (18) |
| **IMMUNE** | `pulse/src/immune.py` | `~/.pulse/state/immune-log.json` | DISSONANCE, AMYGDALA, SOUL.md | thalamus (integrity) | `test_immune.py` (17) |
| **PROPRIOCEPTION** | `pulse/src/proprioception.py` | `~/.pulse/state/proprioception-state.json` | session config, tools | thalamus (capability), BUFFER, CORTEX | `test_proprioception.py` (14) |
| **ENTERIC** | `pulse/src/enteric.py` | `~/.pulse/state/enteric-state.json` | ENDOCRINE, PLASTICITY, REM, DISSONANCE | thalamus (intuition), CORTEX | `test_enteric.py` (13) |
| **ENDOCRINE** | `pulse/src/endocrine.py` | `~/.pulse/state/endocrine-state.json` | events, time | thalamus, mood to LIMBIC/REM/CORTEX/MIRROR | `test_endocrine.py` (23) |
| **CIRCADIAN** | `pulse/src/circadian.py` | `~/.pulse/state/circadian-state.json` | system clock | thalamus, RETINA/ADIPOSE/ENDOCRINE settings | `test_circadian.py` (18) |
| **ADIPOSE** | `pulse/src/adipose.py` | `~/.pulse/state/adipose-state.json` | token usage, SPINE, CIRCADIAN | thalamus, budget warnings | `test_adipose.py` (19) |

## Data Flow Rules

1. **THALAMUS is the bus.** Every module that produces state appends to `broadcast.jsonl`. Every module that needs context reads from it.
2. **LIMBIC feeds REM.** Emotional residue persists and colors dream processing.
3. **REM feeds TEMPORAL.** Dream synthesis becomes autobiography chapters.
4. **PLASTICITY feeds Drive Engine.** Evolved weights flow back into pressure calculations.
5. **RETINA filters before CORTEX.** Scores all incoming signals; only those above attention threshold reach CORTEX. SPINE load level and BUFFER topic affect scoring.
6. **MYELIN compresses frequent concepts.** Builds shorthand lexicon from repeated references; compress/expand for token savings. Never compresses names, emotions, or TEMPORAL narratives.
7. **BUFFER captures before compaction.** SPINE monitors context fill → triggers BUFFER.capture() before window resets.
6. **SPINE self-corrects.** At orange: pause non-essential crons. At red: pause all except SPINE. Broadcasts health to thalamus.
7. **VAGUS feeds Drives.** Absence-as-signal creates pressure when meaningful silence is detected.
8. **AMYGDALA runs before CORTEX.** Every input scanned for threats. If threat_level > 0.7, fast-path action executes immediately. Broadcasts all threats to thalamus.
9. **ENDOCRINE sets mood baseline.** Slow hormones (cortisol, dopamine, serotonin, oxytocin) persist for hours. LIMBIC emotional spikes land on this baseline. Broadcasts to thalamus on significant shifts.
10. **CIRCADIAN shifts cognition modes.** DAWN→DAYLIGHT→GOLDEN→TWILIGHT→DEEP_NIGHT. Each mode adjusts RETINA thresholds, ADIPOSE budgets, tone guidance, and ENDOCRINE mood modifiers. Override available for off-hours Josh contact.
11. **ADIPOSE budgets tokens proactively.** 60% conversation / 25% crons / 15% reserve. Auto-rebalances on CIRCADIAN mode shifts. Reserve only accessible when SPINE is red.
12. **CEREBELLUM graduates habits.** Tracks repetitive task outputs, auto-graduates to scripts after consistency threshold. Escalates back to LLM on unexpected output. AMYGDALA can force-escalate all habits.
13. **IMMUNE scans for corruption.** Runs antibodies against values drift, hallucination, memory contradictions, fabrication, and injected behavior. AMYGDALA escalates to IMMUNE on partial prompt injection. Reads DISSONANCE to distinguish expected contradictions from corruption.
14. **PROPRIOCEPTION tracks capabilities.** Maintains live self-model: model, tools, context remaining, limitations. BUFFER reads it for working memory. CORTEX checks `would_exceed` before planning.
15. **ENTERIC provides gut feelings.** Pattern-matches against historical outcomes for fast toward/away/neutral signals. ENDOCRINE mood biases intuition. CORTEX can query before major decisions; overrides are tracked.
6. **DISSONANCE is append-only.** Never resolve contradictions — only add new ones or note when one deepens.
7. **PALATE uses two-column format.** First instinct | Reflected opinion. The gap between them IS the data.

## Integration Checkpoints

After building any new module:
- [ ] Update this ARCHITECTURE.md
- [ ] Ensure it reads from broadcast.jsonl (if it needs shared state)
- [ ] Ensure it writes to broadcast.jsonl (if it produces state)
- [ ] Add to module registry table above
- [ ] Verify no orphaned files created
- [ ] Tests pass
- [ ] CORTEX.md updated

## File Locations (canonical)

```
~/.openclaw/workspace/
├── pulse/
│   ├── src/
│   │   ├── drives.py
│   │   ├── plasticity.py
│   │   ├── rem.py
│   │   ├── thalamus.py
│   │   ├── limbic.py
│   │   ├── vagus.py
│   │   ├── buffer.py
│   │   ├── spine.py
│   │   ├── amygdala.py
│   │   ├── cerebellum.py
│   │   ├── retina.py
│   │   ├── myelin.py
│   │   ├── narrative.py
│   │   ├── endocrine.py
│   │   ├── circadian.py
│   │   ├── adipose.py
│   │   ├── immune.py
│   │   ├── proprioception.py
│   │   └── enteric.py
│   ├── tests/
│   │   ├── test_drives.py
│   │   ├── test_plasticity.py
│   │   ├── test_rem.py
│   │   ├── test_thalamus.py
│   │   ├── test_limbic.py
│   │   ├── test_vagus.py
│   │   ├── test_retina.py
│   │   ├── test_myelin.py
│   │   └── test_narrative.py
│   └── ARCHITECTURE.md           ← THIS FILE
├── memory/
│   └── self/
│       ├── josh_model.md         ✅ BUILT
│       ├── autobiography.md      ✅ BUILT
│       ├── contradictions.md
│       ├── taste-journal.md
│       ├── dreams/               ✅ EXISTS
│       └── sanctum-insights.md   ← Created by REM
├── CORTEX.md
└── SOUL.md
```
