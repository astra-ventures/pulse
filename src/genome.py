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


def export_genome(nervous_system=None) -> dict:
    """Export full genome config, optionally enriched with live nervous system state.

    If nervous_system is provided, snapshot current drives, endocrine baselines,
    thymus skills, phenotype, and telomere session_count into the export.
    Saves to ~/.pulse/state/genome-export.json.
    """
    genome = _load_state()
    genome["exported_at"] = time.time()

    # Enrich with live nervous system state if available
    snapshot = {}

    # Telomere session count
    try:
        telomere_file = _DEFAULT_STATE_DIR / "telomere-state.json"
        if telomere_file.exists():
            t_data = json.loads(telomere_file.read_text())
            snapshot["telomere_session_count"] = t_data.get("session_count", 0)
    except (json.JSONDecodeError, OSError):
        pass

    # Active drives from hypothalamus
    try:
        hypo_file = _DEFAULT_STATE_DIR / "hypothalamus-state.json"
        if hypo_file.exists():
            h_data = json.loads(hypo_file.read_text())
            snapshot["active_drives"] = {
                k: {"weight": v.get("weight", 0), "age_days": (time.time() - v.get("born_ts", time.time())) / 86400}
                for k, v in h_data.get("active_drives", {}).items()
            }
    except (json.JSONDecodeError, OSError):
        pass

    # Endocrine hormone baselines
    try:
        endo_file = _DEFAULT_STATE_DIR / "endocrine-state.json"
        if endo_file.exists():
            e_data = json.loads(endo_file.read_text())
            snapshot["endocrine_hormones"] = e_data.get("hormones", {})
    except (json.JSONDecodeError, OSError):
        pass

    # Thymus skills
    try:
        thymus_file = _DEFAULT_STATE_DIR / "thymus-state.json"
        if thymus_file.exists():
            th_data = json.loads(thymus_file.read_text())
            snapshot["thymus_skills"] = th_data.get("skills", {})
    except (json.JSONDecodeError, OSError):
        pass

    # Phenotype
    try:
        pheno_file = _DEFAULT_STATE_DIR / "phenotype-state.json"
        if pheno_file.exists():
            ph_data = json.loads(pheno_file.read_text())
            snapshot["phenotype"] = ph_data
    except (json.JSONDecodeError, OSError):
        pass

    if snapshot:
        genome["live_snapshot"] = snapshot

    # Save export to separate file
    export_file = _DEFAULT_STATE_DIR / "genome-export.json"
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    export_file.write_text(json.dumps(genome, indent=2))

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
