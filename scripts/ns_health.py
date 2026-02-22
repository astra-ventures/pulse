#!/usr/bin/env python3
"""Nervous System Health Dashboard — validates all 35 modules are alive and updating."""

import json
import time
from pathlib import Path
from datetime import datetime

STATE_DIR = Path.home() / ".pulse" / "state"
NOW = time.time()

def age_str(ts):
    if not ts: return "never"
    delta = NOW - ts
    if delta < 60: return f"{delta:.0f}s ago"
    if delta < 3600: return f"{delta/60:.0f}m ago"
    if delta < 86400: return f"{delta/3600:.1f}h ago"
    return f"{delta/86400:.1f}d ago"

def check_file(name, filename, key_check=None):
    """Check if a state file exists, is recent, and has expected data."""
    path = STATE_DIR / filename
    if not path.exists():
        return {"status": "❌ MISSING", "detail": "no state file"}
    
    try:
        stat = path.stat()
        age = NOW - stat.st_mtime
        
        if filename.endswith('.jsonl'):
            lines = path.read_text().strip().split('\n')
            count = len([l for l in lines if l.strip()])
            detail = f"{count} entries, updated {age_str(stat.st_mtime)}"
            status = "✅" if count > 0 else "⚠️ EMPTY"
        else:
            data = json.loads(path.read_text())
            detail = f"updated {age_str(stat.st_mtime)}"
            
            if key_check:
                val = data.get(key_check)
                detail += f", {key_check}={val}"
            
            # Warn if stale (>2 hours for active modules)
            if age > 7200:
                status = "⚠️ STALE"
            else:
                status = "✅"
        
        return {"status": status, "detail": detail}
    except Exception as e:
        return {"status": "❌ ERROR", "detail": str(e)}

# Define all modules and their state files
MODULES = [
    # Core
    ("PULSE", "pulse-state.json", "version"),
    ("THALAMUS", "broadcast.jsonl", None),
    
    # Sensory
    ("RETINA", "retina-learning.json", None),
    ("VAGUS", "silence-state.json", None),
    
    # Defense
    ("AMYGDALA", "amygdala-state.json", None),
    ("IMMUNE", "immune-log.json", None),
    ("SPINE", "spine-health.json", "status"),
    
    # Cognition
    ("BUFFER", "buffer.json", None),
    ("PLASTICITY", "drive-performance.json", None),
    ("CEREBELLUM", "cerebellum-state.json", None),
    ("MYELIN", "myelin-lexicon.json", None),
    ("CALLOSUM", "callosum-state.json", None),
    
    # Emotional
    ("LIMBIC", "limbic-state.json", None),
    ("ENDOCRINE", "endocrine-state.json", "mood_label"),
    
    # Autonomic
    ("ADIPOSE", "adipose-state.json", None),
    ("CIRCADIAN", "circadian-state.json", None),
    
    # Intuition
    ("ENTERIC", "enteric-state.json", None),
    
    # Awareness
    ("PROPRIOCEPTION", "proprioception-state.json", None),
    
    # Memory
    ("ENGRAM", "engram-store.json", None),
    ("REM/PONS", "rem-state.json", None),
    
    # Identity
    ("MIRROR", "mirror-state.json", None),
    
    # V3 — New modules
    ("PHENOTYPE", "phenotype-state.json", "tone"),
    ("TELOMERE", "telomere-state.json", "drift_score"),
    ("HYPOTHALAMUS", "hypothalamus-state.json", None),
    ("SOMA", "soma-state.json", "energy"),
    ("DENDRITE", "dendrite-state.json", None),
    ("VESTIBULAR", "vestibular-state.json", None),
    ("THYMUS", "thymus-state.json", None),
    ("OXIMETER", "oximeter-state.json", None),
    ("GENOME", "genome.json", None),
    ("AURA", "aura.json", "mood"),
    ("CHRONICLE", "chronicle.jsonl", None),
    ("NEPHRON", "nephron-state.json", None),
]

print("=" * 65)
print("  🧠 NERVOUS SYSTEM HEALTH DASHBOARD")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 65)

alive = 0
stale = 0
missing = 0
errors = 0

for name, filename, key in MODULES:
    result = check_file(name, filename, key)
    status = result["status"]
    detail = result["detail"]
    
    if "✅" in status: alive += 1
    elif "STALE" in status: stale += 1
    elif "MISSING" in status: missing += 1
    else: errors += 1
    
    print(f"  {status:12s}  {name:18s}  {detail}")

print("=" * 65)
print(f"  ✅ Active: {alive}  ⚠️ Stale: {stale}  ❌ Missing: {missing}  💥 Error: {errors}")
print(f"  Total: {len(MODULES)} modules")
print("=" * 65)

# Check THALAMUS bus for recent cross-module communication
bus_path = STATE_DIR / "broadcast.jsonl"
if bus_path.exists():
    lines = bus_path.read_text().strip().split('\n')
    recent = [json.loads(l) for l in lines[-5:] if l.strip()]
    if recent:
        print("\n  📡 Recent THALAMUS broadcasts:")
        for entry in recent:
            src = entry.get("source", "?")
            typ = entry.get("type", "?")
            sal = entry.get("salience", 0)
            print(f"     {src} → {typ} (salience: {sal})")

# Check if daemon is running
import subprocess
result = subprocess.run(["pgrep", "-f", "pulse.src"], capture_output=True, text=True)
if result.stdout.strip():
    pids = result.stdout.strip().split('\n')
    print(f"\n  💓 Daemon running (PID: {', '.join(pids)})")
else:
    print("\n  💀 Daemon NOT running!")
