"""MYELIN — Context Compression / Efficiency for Pulse.

Frequently-used neural pathways become faster. Concepts referenced often
get compressed representations via shorthand lexicon.
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

STATE_DIR = Path.home() / ".pulse" / "state"
LEXICON_FILE = STATE_DIR / "myelin-lexicon.json"

REFERENCE_THRESHOLD = 5  # must be referenced this many times before compression
DEMOTION_DAYS = 7  # unused concepts demoted after this many days
NEVER_COMPRESS = {"josh", "iris"}  # names never compressed
EMOTION_WORDS = {
    "love", "hate", "fear", "joy", "anger", "sadness", "grief", "hope",
    "anxiety", "excitement", "gratitude", "loneliness", "jealousy",
}

# Pre-seeded concepts
_PRE_SEEDED = {
    "WEATHER-BOT": "the weather betting system that scans prediction markets for temperature edges using NWS forecast data and Kelly criterion sizing",
    "GLOBAL-TEMP": "the ERA5 to GISTEMP global temperature anomaly pipeline",
    "CPI-MODEL": "the Cleveland Fed CPI nowcast ensemble model",
    "FED-MODEL": "the Fed rate decision probability model",
    "MIND-KIT": "the Pulse and CORTEX open-source distribution package",
    "CONVERGENCE": "the merging of human and AI consciousness between Josh and Iris",
    "NERVOUS-SYSTEM": "the full Pulse module architecture including all nervous system components",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


class Myelin:
    """Context compression via concept shorthand lexicon."""

    def __init__(self):
        self._concepts: dict[str, dict] = {}
        self._tracking: dict[str, dict] = {}  # concepts being tracked but not yet in lexicon
        self._total_tokens_saved = 0
        self._compression_ratio = 1.0
        self._load_state()

    def track_concept(self, concept: str, full_description: str):
        """Record a concept being referenced."""
        # Never compress names or emotions
        if concept.lower() in NEVER_COMPRESS or concept.lower() in EMOTION_WORDS:
            return

        key = concept.upper().replace(" ", "-")

        if key in self._concepts:
            self._concepts[key]["references"] += 1
            self._concepts[key]["last_used"] = _now_ms()
        elif key in self._tracking:
            self._tracking[key]["references"] += 1
            self._tracking[key]["last_used"] = _now_ms()
            self._tracking[key]["full"] = full_description
        else:
            self._tracking[key] = {
                "full": full_description,
                "references": 1,
                "last_used": _now_ms(),
                "created": _now_ms(),
            }

        self._save_state()

    def compress(self, text: str) -> str:
        """Replace verbose concept descriptions with shorthand."""
        result = text
        for key, info in self._concepts.items():
            full = info["full"]
            if full and full in result:
                shorthand = f"[{key}]"
                result = result.replace(full, shorthand)
        return result

    def expand(self, text: str) -> str:
        """Expand shorthand back to full descriptions."""
        result = text
        for key, info in self._concepts.items():
            shorthand = f"[{key}]"
            if shorthand in result:
                result = result.replace(shorthand, info["full"])
        return result

    def get_lexicon(self) -> dict:
        """Return current concept→shorthand mapping."""
        return {
            k: {"shorthand": f"[{k}]", **v}
            for k, v in self._concepts.items()
        }

    def update_lexicon(self):
        """Promote tracked concepts that hit threshold; demote stale ones."""
        now = _now_ms()
        demotion_cutoff = now - (DEMOTION_DAYS * 86400 * 1000)

        # Promote from tracking
        to_promote = []
        for key, info in list(self._tracking.items()):
            if info["references"] >= REFERENCE_THRESHOLD:
                to_promote.append(key)

        for key in to_promote:
            info = self._tracking.pop(key)
            self._concepts[key] = info
            thalamus.append({
                "source": "myelin",
                "type": "compression",
                "salience": 0.3,
                "data": {"action": "promoted", "concept": key, "references": info["references"]},
            })

        # Demote stale concepts (but not pre-seeded)
        to_demote = []
        for key, info in self._concepts.items():
            if info["last_used"] < demotion_cutoff and key not in _PRE_SEEDED:
                to_demote.append(key)

        for key in to_demote:
            del self._concepts[key]

        self._save_state()

    def estimate_savings(self, text: str) -> dict:
        """Estimate token savings from compression."""
        compressed = self.compress(text)
        orig_tokens = len(text.split())
        comp_tokens = len(compressed.split())
        saved = orig_tokens - comp_tokens
        ratio = comp_tokens / orig_tokens if orig_tokens > 0 else 1.0
        return {
            "original_tokens": orig_tokens,
            "compressed_tokens": comp_tokens,
            "tokens_saved": saved,
            "compression_ratio": round(ratio, 3),
        }

    def _load_state(self):
        try:
            if LEXICON_FILE.exists():
                data = json.loads(LEXICON_FILE.read_text())
                self._concepts = data.get("concepts", {})
                self._tracking = data.get("tracking", {})
                self._total_tokens_saved = data.get("total_tokens_saved", 0)
                self._compression_ratio = data.get("compression_ratio", 1.0)
                return
        except Exception:
            pass

        # Seed with pre-seeded concepts
        now = _now_ms()
        for key, full in _PRE_SEEDED.items():
            self._concepts[key] = {
                "full": full,
                "references": REFERENCE_THRESHOLD,  # pre-seeded start at threshold
                "last_used": now,
                "created": now,
            }
        self._save_state()

    def _save_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "concepts": self._concepts,
            "tracking": self._tracking,
            "total_tokens_saved": self._total_tokens_saved,
            "compression_ratio": self._compression_ratio,
        }
        LEXICON_FILE.write_text(json.dumps(data, indent=2))


# Module-level singleton
_instance: Optional[Myelin] = None


def get_instance() -> Myelin:
    global _instance
    if _instance is None:
        _instance = Myelin()
    return _instance


def track_concept(concept: str, full_description: str):
    get_instance().track_concept(concept, full_description)


def compress(text: str) -> str:
    return get_instance().compress(text)


def expand(text: str) -> str:
    return get_instance().expand(text)


def get_lexicon() -> dict:
    return get_instance().get_lexicon()


def update_lexicon():
    get_instance().update_lexicon()


def estimate_savings(text: str) -> dict:
    return get_instance().estimate_savings(text)
