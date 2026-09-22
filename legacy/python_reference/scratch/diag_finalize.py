"""Census of native-backed objects at exit + explicit gc.collect() probe.

The fault reports "Garbage-collecting" with no Python frame, i.e. some
tp_dealloc runs during interpreter finalization. Calling gc.collect()
explicitly *before* finalization moves that work into a Python frame we can
log around, and the census tells us which native types are still alive.
"""
from __future__ import annotations

import gc
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_app  # noqa: E402

NATIVE_PREFIXES = (
    "grid_render_core",
    "layer_model_core",
    "seismic_3d_core",
    "well_log_core",
    "map_edit_core",
    "geoviz",
    "qgis_render_bridge",
    "shiboken6",
)


def census(tag: str) -> None:
    counts: Counter = Counter()
    try:
        for obj in gc.get_objects():
            module = getattr(type(obj), "__module__", "")
            if not isinstance(module, str):
                continue
            if module.split(".")[0] in NATIVE_PREFIXES:
                counts[f"{module.split('.')[0]}.{type(obj).__name__}"] += 1
    except Exception as exc:  # noqa: BLE001
        run_app._log(f"census failed: {exc!r}")
        return
    if counts:
        run_app._log(f"NATIVE OBJECTS [{tag}]:")
        for name, n in counts.most_common(20):
            run_app._log(f"    {n:5d}  {name}")
    else:
        run_app._log(f"NATIVE OBJECTS [{tag}]: none")


def garbage_census() -> None:
    """With DEBUG_SAVEALL, gc.garbage holds everything that WOULD be freed."""
    counts: Counter = Counter()
    for obj in gc.garbage:
        module = getattr(type(obj), "__module__", "")
        module = module if isinstance(module, str) else "?"
        counts[f"{module}.{type(obj).__name__}"] += 1
    run_app._log(f"gc.garbage: {len(gc.garbage)} objects (not freed)")
    for name, n in counts.most_common(30):
        run_app._log(f"    {n:5d}  {name}")


if __name__ == "__main__":
    run_app._HARD_EXIT = False
    saveall = os.environ.get("PALEO_GC_SAVEALL", "").strip() in {"1", "true", "yes"}
    if saveall:
        # Keeps every unreachable object alive instead of deallocating it.
        # If the fault disappears, it is a tp_dealloc; gc.garbage then tells
        # us exactly which types were about to be freed.
        gc.set_debug(gc.DEBUG_SAVEALL)
        run_app._log("gc.DEBUG_SAVEALL enabled — objects will NOT be freed")
    code = run_app.main()
    run_app._log(f"main returned rc={code}")

    census("before-gc")
    run_app._log("gc.collect() #1 starting")
    gc.collect()
    run_app._log("gc.collect() #1 done")
    if saveall:
        garbage_census()
    census("after-gc")
    run_app._log("gc.collect() #2 starting")
    gc.collect()
    run_app._log("gc.collect() #2 done — entering finalization")
    sys.exit(code)
