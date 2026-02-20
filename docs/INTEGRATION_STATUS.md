# Module Integration Status

*Last updated: February 20, 2026*

## Core (Wired into daemon loop)
| Module | Location | Integrated | Tests |
|--------|----------|-----------|-------|
| Drive Engine | `src/drives/engine.py` | ✅ Yes | ✅ |
| Sensors | `src/sensors/` | ✅ Yes | ✅ |
| Evaluator | `src/evaluator/` | ✅ Yes | ✅ |
| State Persistence | `src/state/persistence.py` | ✅ Yes | ✅ |
| Config | `src/core/config.py` | ✅ Yes | ✅ |
| Health/Webhook | `src/core/health.py`, `webhook.py` | ✅ Yes | ✅ |
| Integrations | `src/integrations/` | ✅ Yes | — |
| Evolution/Mutator | `src/evolution/mutator.py` | ✅ Yes | — |

## Subsystems (Standalone — NOT wired into daemon)
| Module | Location | Purpose | Tests | Integration Plan |
|--------|----------|---------|-------|-----------------|
| Sanctum | `src/sanctum.py` | Dream/reflection sessions | ✅ 24 | Wire into daemon as night-mode loop |
| Thalamus | `src/thalamus.py` | Event broadcast bus | ✅ | Central bus — other modules import it |
| Amygdala | `src/amygdala.py` | Emotional processing | ✅ | Feed into drive weights |
| Immune | `src/immune.py` | Threat/anomaly detection | ✅ | Hook into sensor pipeline |
| Spine | `src/spine.py` | Reflex actions | ✅ | Pre-evaluator fast path |
| Vagus | `src/vagus.py` | Calming/regulation | ✅ | Drive pressure modulation |
| Limbic | `src/limbic.py` | Emotional memory | ✅ | Extend state persistence |
| Cerebellum | `src/cerebellum.py` | Motor learning/habits | ✅ | Action selection optimization |
| Circadian | `src/circadian.py` | Time-of-day rhythms | ✅ | Modulate trigger thresholds |
| Endocrine | `src/endocrine.py` | Mood/hormone simulation | ✅ | Global state modifier |
| Enteric | `src/enteric.py` | Gut feeling/pattern match | ✅ 13 | Pre-trigger heuristic |
| Proprioception | `src/proprioception.py` | Self-model/capabilities | ✅ 14 | CORTEX planning input |
| Retina | `src/retina.py` | Visual/UI perception | ✅ | Sensor extension |
| Adipose | `src/adipose.py` | Resource storage/budget | ✅ | Cost tracking |
| Buffer | `src/buffer.py` | Working memory buffer | ✅ | Context management |
| Myelin | `src/myelin.py` | Pathway strengthening | ✅ | Habit formation |
| Plasticity | `src/plasticity.py` | Adaptive learning | ✅ | Config auto-tuning |
| REM | `src/rem.py` | Sleep-cycle processing | ✅ | Sanctum companion |

## Key Insight

**19 subsystem modules exist but NONE are called from `src/core/daemon.py`.**

These are well-tested, well-designed standalone modules. The next major milestone is wiring them into the daemon loop. Suggested integration order:

1. **Thalamus** (event bus — everything else depends on this)
2. **Circadian** (time-based threshold modulation — high impact, low risk)
3. **Immune** (anomaly detection — safety feature)
4. **Amygdala + Endocrine** (emotional state → drive weights)
5. **Proprioception** (self-awareness for CORTEX)
6. **Sanctum + REM** (night-mode processing)
7. Everything else (cerebellum, spine, vagus, etc.)

Integration should be incremental — one module at a time, with tests verifying the daemon still works after each addition.
