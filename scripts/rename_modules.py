#!/usr/bin/env python3
"""Rename off-theme Pulse modules to biological equivalents."""

import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent

RENAMES = [
    ("raphe",  "raphe"),
    ("adrenal",       "adrenal"),
    ("pineal",      "pineal"),
    ("basal_ganglia",       "basal_ganglia"),
    ("broca",       "broca"),
    ("hippocampus",   "hippocampus"),
]

# All text substitutions: (old_pattern, new_string)
# Order matters — more specific first
def build_subs(old, new):
    old_upper = old.upper()
    new_upper = new.upper()
    old_title = old.title()
    new_title = new.title()
    # basal_ganglia special casing
    new_title = "".join(w.title() for w in new.split("_"))
    old_title = "".join(w.title() for w in old.split("_"))

    return [
        # UPPER constant style:  HIPPOCAMPUS  → HIPPOCAMPUS
        (old_upper, new_upper),
        # Title case class/key:  Hippocampus  → Hippocampus
        (old_title, new_title),
        # lowercase module ref:  hippocampus  → hippocampus
        (old, new),
        # state file: hippocampus.jsonl → hippocampus.jsonl
        (f"{old}.jsonl", f"{new}.jsonl"),
        (f"{old}.json",  f"{new}.json"),
    ]


def process_file(path: Path, all_subs: list):
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return False
    original = content
    for old_pat, new_str in all_subs:
        content = content.replace(old_pat, new_str)
    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


def main():
    all_subs = []
    for old, new in RENAMES:
        all_subs.extend(build_subs(old, new))

    # 1. Rename source files
    for old, new in RENAMES:
        for subdir in ["src", "tests", "build/lib/src"]:
            for suffix in [".py", f"_{old}.py"]:
                # src/hippocampus.py → src/hippocampus.py
                old_path = ROOT / subdir / f"{old}.py"
                new_path = ROOT / subdir / f"{new}.py"
                if old_path.exists() and not new_path.exists():
                    shutil.move(str(old_path), str(new_path))
                    print(f"  MOVED  {old_path.relative_to(ROOT)} → {new_path.relative_to(ROOT)}")

                # tests/test_hippocampus.py → tests/test_hippocampus.py
                old_test = ROOT / subdir / f"test_{old}.py"
                new_test = ROOT / subdir / f"test_{new}.py"
                if old_test.exists() and not new_test.exists():
                    shutil.move(str(old_test), str(new_test))
                    print(f"  MOVED  {old_test.relative_to(ROOT)} → {new_test.relative_to(ROOT)}")

    # 2. Rewrite content in all .py files (excluding venv/.venv/build)
    skip_dirs = {".venv", "venv", "__pycache__"}
    changed = []
    for py_file in ROOT.rglob("*.py"):
        parts = set(py_file.parts)
        if any(s in parts for s in skip_dirs):
            continue
        if process_file(py_file, all_subs):
            changed.append(py_file.relative_to(ROOT))

    # 3. Also update .md, .json, .toml, .cfg files at root level
    for ext in ["*.md", "*.toml", "*.cfg", "*.txt", "*.json"]:
        for f in ROOT.glob(ext):
            if process_file(f, all_subs):
                changed.append(f.relative_to(ROOT))
    for f in (ROOT / "docs").rglob("*.md"):
        if process_file(f, all_subs):
            changed.append(f.relative_to(ROOT))

    # 4. Rename any state files if they exist
    state_dir = ROOT / "state"
    if state_dir.exists():
        for old, new in RENAMES:
            for ext in [".jsonl", ".json"]:
                old_sf = state_dir / f"{old}{ext}"
                new_sf = state_dir / f"{new}{ext}"
                if old_sf.exists():
                    shutil.move(str(old_sf), str(new_sf))
                    print(f"  MOVED  state/{old}{ext} → state/{new}{ext}")

    print(f"\nDone. {len(changed)} files updated:")
    for f in sorted(changed):
        print(f"  {f}")


if __name__ == "__main__":
    main()
