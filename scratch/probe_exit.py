"""Import one module then exit normally; used to bisect the teardown crash.

Usage: .venv/Scripts/python.exe scratch/probe_exit.py <module|none>
"""
from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

faulthandler.enable(file=open(REPO_ROOT / ".workbuddy" / "probe_crash.log", "w"), all_threads=True)

target = sys.argv[1] if len(sys.argv) > 1 else "none"
if target != "none":
    __import__(target)
print(f"imported {target}", flush=True)
sys.exit(0)
