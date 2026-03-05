# Pulse — Module Naming Conventions

## The Rule

**All Pulse modules must be named after biological structures, physiological processes, or anatomical systems.**

Pulse is a nervous system. Every module is an organ. Names should feel like they belong in a medical textbook, not a philosophy lecture or a marketing deck.

---

## ✅ Allowed

| Category | Examples |
|---|---|
| Brain regions | `thalamus`, `hippocampus`, `cerebellum`, `amygdala`, `parietal`, `broca`, `raphe`, `basal_ganglia` |
| Neural structures | `axon`, `dendrite`, `myelin`, `synapse`, `callosum`, `spine` |
| Glands / endocrine | `pineal`, `adrenal`, `endocrine`, `thymus`, `hypothalamus` |
| Body systems | `immune`, `enteric`, `vestibular`, `vagus`, `proprioception` |
| Physiological states | `circadian`, `rem`, `soma`, `adipose`, `nephron` |
| Biological processes | `plasticity`, `engram`, `germinal`, `phenotype`, `telomere` |
| Classical bio-Latin/Greek | `pneuma` (breath/vital spirit), `genome`, `aura`* |

*`aura` is retained as it has established neurological usage (pre-seizure sensory phenomenon).

---

## ❌ Not Allowed

| Type | Bad examples | Why |
|---|---|---|
| Abstract philosophy | `telos`, `logos` | Greek concepts, not anatomy |
| Non-biological Latin | `aurum` (gold), `vesper` (evening) | No anatomical basis |
| Generic English | `challenger`, `chronicle` | Could be anything |
| Freudian (borderline) | Prefer anatomical equivalents | Too abstract |
| Proper nouns | `darwin`, `watson` | Not anatomical |
| Marketing-speak | `pulse`, `signal`, `core` | Avoid as module names |

---

## Naming Checklist

Before naming a new module, ask:

1. **Is it a real anatomical structure or physiological process?** If yes → ✅
2. **Would it appear in Gray's Anatomy or a neuroscience textbook?** If yes → ✅
3. **Is the Greek/Latin root an established medical term?** If yes → ✅
4. **Is it named after a concept, emotion, or abstract idea?** If yes → ❌ find the biological equivalent

---

## Finding the Right Name

Map the *function* to the *organ that does it*:

| Function | Biological name | Module |
|---|---|---|
| Memory timeline / history | Hippocampus (temporal lobe memory) | `hippocampus` |
| Financial / survival pressure | Adrenal gland (stress response) | `adrenal` |
| Nightly synthesis / melatonin | Pineal gland | `pineal` |
| Goal-directed behavior | Basal ganglia | `basal_ganglia` |
| Language / directive parsing | Broca's area | `broca` |
| Novelty detection / stagnation | Raphe nuclei (serotonin, exploration) | `raphe` |

---

## Module Registry (Current)

All 50 active modules as of v0.3.7:

`adipose` `amygdala` `aura` `axon` `basal_ganglia` `biosensor_bridge`
`biosensor_cache` `broca` `buffer` `callosum` `cerebellum` `circadian`
`dendrite` `adrenal` `endocrine` `engram` `enteric` `genome` `germinal`
`hippocampus` `hypothalamus` `immune` `limbic` `memory_consolidation`
`mirror` `motoric` `myelin` `nephron` `oximeter` `parietal` `phenotype`
`pineal` `plasticity` `pneuma` `proprioception` `raphe` `rem` `retina`
`soma` `spine` `superego`* `synapse` `telomere` `thalamus` `thymus`
`vagus` `vestibular`

*`superego` is Freudian but retained as a legacy name pending a suitable anatomical replacement (candidate: `prefrontal`).

---

## Architecture is Complete

The module ceiling is **50**. Do not add modules without retiring one.
If a new capability is needed, extend an existing module rather than creating a new one.
If a new module is genuinely required, propose a retirement candidate first.
