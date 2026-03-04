# Pulse Metacognitive Module — Code Review

**Date:** March 4, 2026  
**Reviewer:** Iris (Trigger #31)  
**Modules reviewed:** `evaluator/model.py`, `evaluator/priority.py`, `germinal.py`, `evolution/mutator.py`  
**Tests added:** 15 (in `tests/test_metacognitive_review.py`)  
**Total tests after review:** 1153 (all passing)

---

## Summary

The Pulse metacognitive layer is well-architected with clear separation: `PriorityEvaluator` (rules), `ModelEvaluator` (LLM gate), `GERMINAL` (self-spawning), and `Mutator` (self-modification). The code is generally clean, well-documented, and defensively written. However, this review found **1 critical bug**, **3 moderate issues**, and **2 minor issues**.

---

## 🚨 Critical: GERMINAL Permanently Blocked (FIXED)

**File:** `germinal.py` → `attempt_birth()`  
**Bug:** The module ceiling check used `PULSE_SRC.glob("*.py")` which counts ALL Python files (52), not just biological modules (40). With `MAX_TOTAL_MODULES = 50`, the check `52 >= 50` is **always true**, meaning GERMINAL could **never birth a new module**.

**Root cause:** Infrastructure files (`__init__.py`, `__main__.py`, `cli.py`, `types.py`, `nervous_system.py`, `observation_api.py`, `plugin_registry.py`, etc.) were counted as modules. This probably started failing silently when the 50th and 51st `.py` files were added.

**Fix:** Added `_INFRA_FILES` frozenset and `_count_modules()` helper that excludes infrastructure files. Ceiling now correctly sees 40 modules with room for 10 more.

**Impact:** GERMINAL was dead code from the moment the src/ directory exceeded 50 files. The self-evolution feature — arguably the most novel part of Pulse — was silently disabled.

---

## ⚠️ Moderate Issues (FIXED)

### 1. ModelEvaluator: Fallback ignores conversation suppression

**File:** `evaluator/model.py` → `_fallback_evaluate()`  
**Bug:** When the model evaluator fails (network error, timeout, etc.), the fallback path didn't check `suppress_during_conversation`. An active conversation would correctly suppress the model path, but if the model call *failed*, the fallback would trigger anyway — violating the conversation-awareness contract.

**Fix:** Added conversation suppression check as the first gate in `_fallback_evaluate()`, mirroring `PriorityEvaluator.evaluate()`.

### 2. ModelEvaluator: Duplicate JSON fence stripping

**File:** `evaluator/model.py`  
**Issue:** `_parse_response()` and `_extract_suppress_minutes()` both contained identical markdown fence-stripping logic (strip ```` ```json ... ``` ````). The response was parsed twice — once for the decision, once for suppress_minutes.

**Fix:** Extracted `_strip_json_fences()` static method. Both callers now use the shared helper.

### 3. Mutator: `_remove_drive` validates before existence check

**File:** `evolution/mutator.py` → `_remove_drive()`  
**Bug:** Called `guardrails.validate_drive_removal(name)` before checking `name in self.drives.drives`. If a user tried to remove a non-existent drive that happened to be protected, they'd get a misleading guardrails error instead of a clear "drive doesn't exist" message.

**Fix:** Moved existence check before guardrails validation.

---

## 📝 Minor Issues (FIXED)

### 4. `datetime` imported inside method

**File:** `evaluator/model.py` → `_build_prompt()`  
**Issue:** `from datetime import datetime` was inside the method body. Moved to module-level import for consistency.

---

## 📋 Remaining Observations (Not Fixed — Future Work)

### 5. GERMINAL state file lacks locking

**File:** `germinal.py` → `attempt_birth()`, `_save_state()`  
**Observation:** State file operations use plain `read_text()` / `write_text()` without `fcntl.flock()`, unlike `Mutator.process_queue()` which properly locks. If multiple Pulse instances run simultaneously (e.g. during restart race), state could corrupt.

**Risk:** Low (Pulse is typically single-instance), but worth adding for correctness.

### 6. Blocking `subprocess.run` in async method

**File:** `evaluator/model.py` → `_evaluate_async()`  
**Observation:** `subprocess.run(["vm_stat"])` is synchronous inside an async method. Should use `asyncio.create_subprocess_exec()` or `loop.run_in_executor()`. Practical impact is near-zero since `vm_stat` completes in <1ms.

### 7. `_module_exists_for_drive` filename matching is fragile

**File:** `germinal.py`  
**Observation:** Converts archetype name like `"VAGAL_TONE"` to filename `"vagaltone.py"` by lowering + stripping underscores. This works but is brittle — if someone names a module `vagal_tone.py` (with underscore), it wouldn't match.

### 8. Evaluator model test coverage is prompt-only

**File:** `tests/test_evaluator_model.py`  
**Observation:** All 6 existing tests verify prompt text content (checking that specific strings appear in `EVALUATOR_SYSTEM_PROMPT`). There are no tests for the actual evaluation logic (`evaluate()`, `_parse_response()`, `_fallback_evaluate()`). The 4 new fallback tests in this review partially address this gap.

---

## Files Modified

| File | Change |
|------|--------|
| `src/germinal.py` | Added `_INFRA_FILES`, `_count_modules()`, fixed ceiling check |
| `src/evaluator/model.py` | Added `_strip_json_fences()`, conversation suppression in fallback, moved datetime import |
| `src/evolution/mutator.py` | Reordered existence check before guardrails in `_remove_drive` |
| `tests/test_metacognitive_review.py` | 15 new tests covering all fixes |

## Test Results

```
1153 passed in 3.39s
```
