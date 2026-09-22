#!/usr/bin/env python3
"""Local benchmarks for horizon interpretation edit/save/reload (not unit CI)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.interpretation_lifecycle import (
    open_draft_from_array,
    restore_draft_from_project_ref,
    save_draft_as_new_version,
)


def bench_size(n: int, n_edits: int = 100) -> dict:
    z = np.full((n, n), 100.0, dtype=np.float32)
    draft = open_draft_from_array(z, horizon_key="H1", name="H1")
    rng = np.random.default_rng(0)
    lat = []
    for _ in range(n_edits):
        x = float(rng.uniform(0, n - 1))
        y = float(rng.uniform(0, n - 1))
        t0 = time.perf_counter()
        draft.sculpt((x, y), delta_z=0.5, radius=max(2.0, n * 0.02))
        lat.append((time.perf_counter() - t0) * 1000.0)
    lat_s = sorted(lat)
    p50 = lat_s[len(lat_s) // 2]
    p95 = lat_s[int(len(lat_s) * 0.95)]

    # undo/redo
    t0 = time.perf_counter()
    while draft.can_undo():
        draft.undo()
    undo_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    while draft.can_redo():
        draft.redo()
    redo_ms = (time.perf_counter() - t0) * 1000.0

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.paleo.json"
        project = ProjectDocument.new("bench")
        ProjectManager(p).save(project)
        tracemalloc.start()
        t0 = time.perf_counter()
        ref, msg = save_draft_as_new_version(draft, project, p)
        save_ms = (time.perf_counter() - t0) * 1000.0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        ProjectManager(p).save(project)
        t0 = time.perf_counter()
        reopened = ProjectManager(p).load()
        restored = restore_draft_from_project_ref(reopened, p)
        reload_ms = (time.perf_counter() - t0) * 1000.0
        art = None
        if ref and ref.artifact_path:
            ap = Path(ref.artifact_path)
            if not ap.is_file():
                ap = p.parent / ref.artifact_path
            if ap.is_file():
                art = ap.stat().st_size

    return {
        "n": n,
        "n_edits": n_edits,
        "edit_p50_ms": p50,
        "edit_p95_ms": p95,
        "undo_all_ms": undo_ms,
        "redo_all_ms": redo_ms,
        "save_ms": save_ms,
        "reload_ms": reload_ms,
        "save_peak_alloc_bytes": peak,
        "artifact_bytes": art,
        "save_ok": msg == "ok",
    }


def main() -> None:
    rows = []
    for n in (256, 512, 1024):
        rows.append(bench_size(n, n_edits=100 if n < 1024 else 200))
    rows.append(bench_size(512, n_edits=1000))
    print(json.dumps({"rows": rows}, indent=2))


if __name__ == "__main__":
    main()
