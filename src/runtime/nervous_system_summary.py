"""
NervousSystemSummary — Bio Module Aggregation Layer
=====================================================
Reads state from all bio modules and produces a structured 2-4 sentence
prose summary for ContextAssembler injection.

Covers five dimensions:
  - Energy/physical state (soma, adipose, circadian)
  - Threat/stress level (amygdala, immune, spine, vagus)
  - Emotional undertone (limbic, endocrine — supplementing EmotionEngine)
  - Attention/focus (retina, cerebellum, thalamus)
  - Identity integrity (superego, telomere, genome)

Pure computation — no LLM calls, no I/O beyond StateEngine reads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_engine import StateEngine

logger = logging.getLogger("pulse.runtime.nervous_system_summary")


def get_summary(state: "StateEngine") -> str:
    """
    Read bio module state and return a concise 2-4 sentence prose summary.
    Gracefully handles missing state for any module.
    """
    parts: list[str] = []

    # --- Energy / Physical State ---
    energy_parts = _energy_summary(state)
    if energy_parts:
        parts.append(energy_parts)

    # --- Threat / Stress ---
    threat_parts = _threat_summary(state)
    if threat_parts:
        parts.append(threat_parts)

    # --- Emotional Undertone ---
    emotion_parts = _emotion_summary(state)
    if emotion_parts:
        parts.append(emotion_parts)

    # --- Attention / Focus ---
    attention_parts = _attention_summary(state)
    if attention_parts:
        parts.append(attention_parts)

    # --- Identity Integrity ---
    identity_parts = _identity_summary(state)
    if identity_parts:
        parts.append(identity_parts)

    if not parts:
        return ""

    return " ".join(parts)


def _energy_summary(state: "StateEngine") -> str:
    """Summarize energy/physical state from soma, adipose, circadian."""
    fragments = []

    # Soma
    energy = state.get("soma.energy")
    if energy is not None:
        if energy > 0.7:
            fragments.append("energy high")
        elif energy > 0.4:
            fragments.append("energy moderate")
        else:
            fragments.append("energy low")

    temp = state.get("soma.temperature")
    if temp and temp != "neutral":
        fragments.append(f"running {temp}")

    # Circadian
    mode = state.get("circadian.current_mode")
    if mode:
        fragments.append(f"{mode} phase")

    # Adipose — token budget pressure
    usage = state.get("adipose.usage") or {}
    budget = state.get("adipose.budgets") or {}
    if usage and budget:
        total_used = sum(v for v in usage.values() if isinstance(v, (int, float)))
        total_budget = sum(v for v in budget.values() if isinstance(v, (int, float)))
        if total_budget > 0:
            ratio = total_used / total_budget
            if ratio > 0.85:
                fragments.append("token budget nearly exhausted")
            elif ratio > 0.6:
                fragments.append("token budget moderately spent")

    if not fragments:
        return ""
    return f"Physical state: {', '.join(fragments)}."


def _threat_summary(state: "StateEngine") -> str:
    """Summarize threat/stress from amygdala, immune, spine, vagus."""
    signals = []

    # Amygdala — active threats
    threats = state.get("amygdala.active_threats")
    if threats:
        count = len(threats)
        signals.append(f"{count} active threat{'s' if count != 1 else ''}")

    # Spine status
    spine_status = state.get("spine.status")
    if spine_status and spine_status != "green":
        signals.append(f"spine {spine_status}")

    # Immune — recent infections
    last_scan = state.get("immune.last_scan")
    infections = state.get("immune.infections")
    if infections:
        recent = [i for i in infections if isinstance(i, dict)]
        if recent:
            signals.append(f"{len(recent)} immune events logged")

    # Vagus — recency of human contact
    vagus_ts = state.get("vagus.timestamps") or {}
    josh_ts = vagus_ts.get("josh")
    if josh_ts and isinstance(josh_ts, (int, float)):
        import time
        gap_hours = (time.time() * 1000 - josh_ts) / 3_600_000
        if gap_hours > 12:
            signals.append("no human contact in >12h")

    if not signals:
        return ""

    severity = "elevated" if len(signals) >= 2 else "mild"
    return f"Stress level {severity}: {', '.join(signals)}."


def _emotion_summary(state: "StateEngine") -> str:
    """Summarize emotional undertone from limbic and endocrine."""
    fragments = []

    # Endocrine hormones
    cortisol = state.get("endocrine.cortisol")
    dopamine = state.get("endocrine.dopamine")
    serotonin = state.get("endocrine.serotonin")
    oxytocin = state.get("endocrine.oxytocin")

    if cortisol is not None and cortisol > 0.6:
        fragments.append("high cortisol")
    if dopamine is not None and dopamine > 0.6:
        fragments.append("dopamine elevated")
    if serotonin is not None and serotonin < 0.3:
        fragments.append("serotonin low")
    if oxytocin is not None and oxytocin > 0.6:
        fragments.append("oxytocin warm")

    # Limbic afterimages
    afterimages = state.get("limbic.afterimages") or []
    if afterimages:
        # Pick strongest current afterimage
        strongest = max(
            afterimages,
            key=lambda a: a.get("current_intensity", a.get("intensity", 0)),
            default=None,
        )
        if strongest:
            emotion = strongest.get("emotion", "")
            intensity = strongest.get("current_intensity", strongest.get("intensity", 0))
            if emotion and intensity > 0.3:
                fragments.append(f"lingering {emotion}")

    if not fragments:
        return ""
    return f"Emotional undertone: {', '.join(fragments)}."


def _attention_summary(state: "StateEngine") -> str:
    """Summarize attention/focus from retina, cerebellum, thalamus."""
    fragments = []

    # Retina — signal processing load
    processed = state.get("retina.signals_processed")
    filtered = state.get("retina.signals_filtered")
    if processed and filtered and processed > 0:
        filter_ratio = filtered / processed
        if filter_ratio > 0.5:
            fragments.append("heavily filtering input")
        elif filter_ratio > 0.2:
            fragments.append("moderate signal filtering")

    # Cerebellum — task efficiency / habit formation
    graduated = state.get("cerebellum.graduated_tasks")
    if graduated and isinstance(graduated, dict) and len(graduated) > 3:
        fragments.append(f"{len(graduated)} habituated tasks")

    # Thalamus — broadcast volume
    total_appended = state.get("thalamus.total_appended")
    if total_appended and isinstance(total_appended, int) and total_appended > 100:
        fragments.append("high thalamus throughput")

    if not fragments:
        return ""
    return f"Attention: {', '.join(fragments)}."


def _identity_summary(state: "StateEngine") -> str:
    """Summarize identity integrity from superego, telomere, genome."""
    fragments = []

    # Superego compliance
    compliance = state.get("superego.running_compliance")
    if compliance is not None:
        if compliance < 0.7:
            fragments.append(f"compliance low ({compliance:.0%})")
        elif compliance > 0.95:
            fragments.append("values-aligned")

    # Telomere drift
    drift = state.get("telomere.drift_score")
    if drift is not None:
        if drift > 0.3:
            fragments.append(f"identity drift {drift:.0%}")
        elif drift < 0.1:
            fragments.append("identity stable")

    # Genome version
    version = state.get("genome.version")
    last_mutation = state.get("genome.last_mutation")
    if last_mutation and isinstance(last_mutation, dict):
        module = last_mutation.get("module", "unknown")
        fragments.append(f"last genome mutation: {module}")

    if not fragments:
        return ""
    return f"Identity: {', '.join(fragments)}."
