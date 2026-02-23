"""GENOME — Exportable DNA Config for Pulse.

All module settings/thresholds/weights in one exportable config.
Mutatable by PLASTICITY. Import/export for cloning.
"""

import json
import time
from pathlib import Path
from typing import Optional

from pulse.src import thalamus

_DEFAULT_STATE_DIR = Path.home() / ".pulse" / "state"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "genome.json"

# Default genome
_DEFAULT_GENOME = {
    "version": "3.0",
    "created_at": 0,
    "modules": {
        "endocrine": {
            "decay_rates": {"cortisol": -0.05, "dopamine": -0.08, "serotonin": -0.02, "oxytocin": -0.04, "adrenaline": -0.28, "melatonin": -0.01},
            "high_threshold": 0.5,
            "low_threshold": 0.3,
        },
        "limbic": {
            "half_life_ms": 14400000,
            "decay_threshold": 0.5,
            "contagion_multiplier": 0.5,
        },
        "retina": {
            "default_threshold": 0.3,
            "focus_threshold": 0.8,
        },
        "circadian": {
            "dawn_hours": [6, 9],
            "daylight_hours": [9, 17],
            "golden_hours": [17, 22],
        },
        "amygdala": {
            "fast_path_threshold": 0.7,
        },
        "phenotype": {
            "default_humor": 0.3,
            "default_intensity": 0.5,
        },
        "telomere": {
            "drift_threshold": 0.3,
        },
        "hypothalamus": {
            "signal_threshold": 3,
            "retirement_days": 30,
            "weight_floor": 0.1,
        },
        "soma": {
            "energy_cost_per_token": 0.001,
            "rem_replenish": 0.5,
        },
        "dendrite": {
            "trust_increment": 0.01,
            "trust_decrement": 0.05,
        },
        "vestibular": {
            "building_shipping_range": [0.3, 0.7],
            "working_reflecting_range": [0.4, 0.8],
        },
    },
}


def _load_state() -> dict:
    if _DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(_DEFAULT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    genome = dict(_DEFAULT_GENOME)
    genome["created_at"] = time.time()
    return genome


def _save_state(state: dict):
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    _DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2))


def export_genome() -> dict:
    """Export full genome config."""
    genome = _load_state()
    genome["exported_at"] = time.time()
    return genome


def import_genome(genome: dict) -> dict:
    """Import a genome config. Returns the imported genome."""
    genome["imported_at"] = time.time()
    _save_state(genome)
    
    thalamus.append({
        "source": "genome",
        "type": "import",
        "salience": 0.6,
        "data": {"version": genome.get("version", "unknown")},
    })
    return genome


def get_module_config(module_name: str) -> Optional[dict]:
    """Get config for a specific module."""
    genome = _load_state()
    return genome.get("modules", {}).get(module_name)


def mutate(module_name: str, key: str, value) -> dict:
    """Mutate a specific setting. Used by PLASTICITY."""
    genome = _load_state()
    if module_name not in genome.get("modules", {}):
        genome.setdefault("modules", {})[module_name] = {}
    genome["modules"][module_name][key] = value
    genome["last_mutation"] = {"module": module_name, "key": key, "ts": time.time()}
    _save_state(genome)
    
    thalamus.append({
        "source": "genome",
        "type": "mutation",
        "salience": 0.4,
        "data": {"module": module_name, "key": key},
    })
    return genome["modules"][module_name]


def get_status() -> dict:
    """Return genome status."""
    genome = _load_state()
    return {
        "version": genome.get("version", "unknown"),
        "modules": len(genome.get("modules", {})),
        "last_mutation": genome.get("last_mutation"),
    }
