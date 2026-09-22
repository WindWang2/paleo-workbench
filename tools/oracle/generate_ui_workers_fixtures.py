#!/usr/bin/env python3
"""Oracle for the UI-04 page-worker cores (libs/ui_workers).

Imports the REAL Python sources (geoviz facade, geoviz_seismic.stratal,
geoviz_plots.geomodel.primitives, geoviz_cross_well.dtw_engine,
paleo_workbench.workflow.{contour_draft,factor_prepare_scheduler,
stratigraphy_correlation,interpolation_fingerprint},
paleo_workbench.viz.adapter) and freezes deterministic input/output pairs
for the C++ replay test in libs/ui_workers/ui_workers_tests.

Two case families:
  * pure-kernel cases — the C++ port computes the same numbers the Python
    function does (levels, surfaces, slices, geometry, digests, keys).
  * orchestration cases — worker/scheduler loops whose per-task seam
    outputs are frozen alongside the expected progress/result sequences;
    the C++ test replays the frozen seams and diffs the orchestration.

Worker files that import PySide6 cannot be loaded, so source-verbatim
literals/functions are lifted out of them with ``ast`` (the geological
record tables, the catalog-status map, bounded_dtw_band) — never
re-typed by hand.

Run with the conv12 oracle venv (full project import chain, no Qt needed):

    /home/kevin/project/oracle-venvs/conv12/bin/python \
        tools/oracle/generate_ui_workers_fixtures.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
GEO_ENGINE = REPO_ROOT.parent / "paleo-workbench" / "geo-viz-engine"
if not GEO_ENGINE.exists():
    GEO_ENGINE = REPO_ROOT / "geo-viz-engine"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(GEO_ENGINE))

OUT = (
    REPO_ROOT
    / "libs"
    / "ui_workers"
    / "ui_workers_tests"
    / "fixtures"
    / "ui_workers_oracle.json"
)


# ---------------------------------------------------------------------------
# Freezing helpers.
# ---------------------------------------------------------------------------

def _num(value):
    """JSON-safe float: NaN/±inf are tagged strings so they stay
    distinguishable (JSON has no non-finite literal)."""
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def _grid(arr) -> dict:
    a = np.asarray(arr, dtype=np.float64)
    return {"rows": int(a.shape[0]), "cols": int(a.shape[1]),
            "data": _nums(a)}


def _volume(arr) -> dict:
    a = np.asarray(arr)
    return {"n_i": int(a.shape[0]), "n_x": int(a.shape[1]),
            "n_s": int(a.shape[2]), "data": _nums(a)}


def _jsonable(value):
    """Convert numpy/pydantic-ish leaves to plain JSON values."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, (np.floating, np.integer)):
        return _num(value)
    if isinstance(value, float):
        return _num(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _literal_assignments(path: Path) -> dict:
    """ast-literal-eval every Assign whose value is a literal (any depth).

    Worker modules import PySide6 and cannot be executed; their hardcoded
    record tables ARE the spec, so the oracle lifts them verbatim.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict = {}

    def _walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Assign):
                try:
                    value = ast.literal_eval(child.value)
                except (ValueError, SyntaxError):
                    value = None
                else:
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            found[target.id] = value
            _walk(child)

    _walk(tree)
    return found


def _load_function(path: Path, func_name: str, namespace: dict):
    """Extract one function def from a Qt-importing module via ast + exec.

    Only valid for self-contained pure functions (bounded_dtw_band uses
    only builtins + the injected _MAX_DTW_CELLS constant).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            mod = ast.Module(body=[node], type_ignores=[])
            exec(compile(mod, str(path), "exec"), namespace)
            return namespace[func_name]
    raise KeyError(func_name)


CASES: list[dict] = []


def case(kind: str, case_id: str, **payload):
    CASES.append({"id": case_id, "kind": kind, **payload})


# ---------------------------------------------------------------------------
# worker_common — Python builtins/math parity.
# ---------------------------------------------------------------------------

def gen_worker_common():
    for i, (value, digits) in enumerate(
        [(2.5, 0), (3.5, 0), (-2.5, 0), (1.005, 2), (2.675, 2),
         (1234.5678, 2), (0.125, 2), (float("nan"), 3)]):
        try:
            out = round(value, digits)
        except Exception:
            out = "error"
        case("py_round", f"round_{i}",
             input={"value": _num(value), "digits": digits},
             expected=_num(out) if out != "error" else "error")

    for i, (a, b, rel, absol) in enumerate(
        [(1.0, 1.0 + 1e-10, 1e-9, 0.0), (1.0, 1.0 + 1e-8, 1e-9, 0.0),
         (0.0, 1e-9, 1e-9, 0.0), (float("nan"), 0.0, 1e-9, 0.0),
         (2.0, 2.0000001, 1e-6, 0.0), (1.0, 1.05, 1e-9, 0.1)]):
        case("py_isclose", f"isclose_{i}",
             input={"a": _num(a), "b": _num(b),
                    "rel_tol": rel, "abs_tol": absol},
             expected=bool(math.isclose(a, b, rel_tol=rel, abs_tol=absol)))

    for i, (lo, hi, n) in enumerate(
        [(0.0, 1.0, 5), (-2.0, 2.0, 9), (0.0, 1.0, 1), (3.0, 3.0, 4)]):
        case("np_linspace", f"linspace_{i}",
             input={"lo": lo, "hi": hi, "n": n},
             expected=_nums(np.linspace(lo, hi, n)))

    # env_int parse semantics: int(raw.strip()) with ValueError -> fallback.
    for i, raw in enumerate(
        ["3", " 4 ", "-2", "abc", "", "0", "17x", "+5", "4.5", "9999"]):
        try:
            parsed = int(raw.strip())
        except ValueError:
            parsed = None
        case("env_int", f"env_{i}", input={"raw": raw, "fallback": 1},
             expected=parsed if parsed is not None else 1)

    # Python truthiness for the parameters[key] sample-points check.
    truthy_inputs = [
        ("missing", {"__missing__": True}),
        ("null", None), ("empty_list", []), ("empty_dict", {}),
        ("empty_str", ""), ("zero_int", 0), ("zero_float", 0.0),
        ("false", False), ("list_one", [1]), ("dict_one", {"a": 1}),
        ("str_x", "x"), ("int_two", 2), ("float_half", 0.5),
    ]
    for name, value in truthy_inputs:
        py_val = {} if name == "missing" else value
        expected = bool(py_val) if name != "missing" else False
        case("param_truthy", f"truthy_{name}",
             input={"value": value}, expected=expected)

    # str-or-fallback semantics (param_str `or` parity): Python
    # str((params.get(key) or "interpolation failed")) — a truthy scalar is
    # str()'d; a missing/None/empty value falls back.
    for name, value in [("missing", {"__missing__": True}), ("null", None),
                        ("empty", ""), ("text", "err msg"),
                        ("int_val", 7), ("zero", 0)]:
        py_val = {} if name == "missing" else value
        if py_val is None or (isinstance(py_val, dict) and
                              py_val.get("__missing__")):
            got = None
        else:
            got = py_val
        expected = str(got) if got else "interpolation failed"
        case("param_str_or", f"pstr_{name}",
             input={"value": value}, expected=expected)


# ---------------------------------------------------------------------------
# Path helpers — project.paths / VizAdapter._absolute_path /
# stratigraphy_correlation._resource_path.
# ---------------------------------------------------------------------------

def gen_paths():
    import _legacy_reference
    _legacy_reference.ensure_legacy_reference()  # archived-reference shim
    from paleo_workbench.project.paths import is_within_directory
    from paleo_workbench.workflow.stratigraphy_correlation import _resource_path
    from paleo_workbench.viz.adapter import VizAdapter

    root = "/pwb_oracle_root/proj"
    within_inputs = [
        f"{root}/data/a.las", f"{root}", f"{root}_sibling/x",
        f"{root}/../outside/x", "/etc/hostname",
        f"{root}/deep/../a.las", f"{root}/../../root2/a",
    ]
    for i, p in enumerate(within_inputs):
        case("is_within_directory", f"within_{i}",
             input={"path": p, "directory": root},
             expected=bool(is_within_directory(Path(p), Path(root))))

    # _resource_path(project, resource): file-or-absolute -> BARE candidate;
    # else confined root join; returns a Path.
    proj = SimpleNamespace(meta=SimpleNamespace(project_root=root))
    for i, p in enumerate(
        ["data/a.las", "./b.xml", "../escape/c.las", "/abs/d.las",
         "sub/dir/e.las"]):
        out = _resource_path(proj, SimpleNamespace(path=p))
        case("resource_path", f"respath_{i}",
             input={"path": p, "project_root": root},
             expected=str(out))

    # _absolute_path(path, project): is_file -> resolve(); absolute -> bare
    # candidate; else confined root join (escape -> bare candidate).
    adapter = VizAdapter.__new__(VizAdapter)
    for i, p in enumerate(
        ["data/a.las", "./b.xml", "../escape/c.las", "/abs/d.las"]):
        case("absolute_resource_path", f"abspath_{i}",
             input={"path": p, "project_root": root},
             expected=str(adapter._absolute_path(p, proj)))
    # Degenerate roots ("" / "." / "..") -> bare candidate, no join.
    for i, bad_root in enumerate(["", ".", ".."]):
        proj_bad = SimpleNamespace(
            meta=SimpleNamespace(project_root=bad_root))
        case("absolute_resource_path", f"abspath_root_{i}",
             input={"path": "data/a.las", "project_root": bad_root},
             expected=str(adapter._absolute_path("data/a.las", proj_bad)))
        case("resource_path", f"respath_root_{i}",
             input={"path": "data/a.las", "project_root": bad_root},
             expected=str(_resource_path(
                 proj_bad, SimpleNamespace(path="data/a.las"))))


# ---------------------------------------------------------------------------
# synthetic_sample_points + sha512 (geoviz real).
# ---------------------------------------------------------------------------

def gen_synthetic_points():
    from geoviz import synthetic_sample_points
    for i, (seed, ftype) in enumerate(
        [(0, "地层厚度"), (7, "砂岩含量"), (42, "砂地比"), (-3, "泥岩含量")]):
        pts = synthetic_sample_points(seed=seed, factor_type=ftype)
        case("synthetic_points", f"synth_{i}",
             input={"seed": seed, "factor_type": ftype, "count": 8},
             expected=_jsonable(pts))
    for i, text in enumerate(["abc", "", "地层厚度", "seed:42:x"]):
        case("sha512", f"sha_{i}", input={"text": text},
             expected=hashlib.sha512(text.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------------------
# contour_draft — real workflow.contour_draft + geoviz levels.
# ---------------------------------------------------------------------------

def gen_contour():
    from paleo_workbench.workflow import contour_draft as cd
    from paleo_workbench.project.models import (
        ContourDraft, ContourSegment, FactorMapTask)

    for i, (lo, hi, n) in enumerate(
        [(0.0, 10.0, 8), (1.0, 1.0, 8), (-5.0, 5.0, 4),
         (0.001, 0.002, 6), (100.0, 200.0, 3), (10.0, 0.0, 8)]):
        case("nice_levels_range", f"nlr_{i}",
             input={"lo": lo, "hi": hi, "n_levels": n},
             expected=_nums(cd.suggest_nice_levels_from_range(
                 lo, hi, n_levels=n)))

    grids = [
        np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        np.array([[np.nan, np.nan], [np.nan, np.nan]]),
        np.array([[7.0, 7.0], [7.0, 7.0]]),
        np.array([[0.0, 1.0, np.nan], [2.0, 3.0, 4.0]]),
    ]
    for i, g in enumerate(grids):
        case("nice_levels_grid", f"nlg_{i}",
             input={"grid": _grid(g), "n_levels": 8},
             expected=_nums(cd.suggest_nice_levels(g, n_levels=8)))

    # geoviz suggest_levels fallback — the raw linspace branch for an
    # explicit (lo,hi) range (endpoints excluded, round(v,6)).
    for i, (lo, hi, n) in enumerate(
        [(0.0, 10.0, 8), (1.0, 1.0, 8), (0.0, 1.0, 3)]):
        if math.isclose(lo, hi):
            expected = [lo]
        else:
            levels = np.linspace(lo, hi, max(2, n) + 2)[1:-1]
            expected = [round(float(v), 6) for v in levels]
        case("levels_fallback", f"lfb_{i}",
             input={"lo": lo, "hi": hi, "n_levels": n},
             expected=_nums(expected))

    # upsert_contour_draft — replace-by-task / replace-by-scope / append.
    cd._now_iso = lambda: "2024-01-02T03:04:05Z"  # pin the clock

    def _draft(**kw):
        base = dict(name="d", target_horizon="H1", factor_type="厚度",
                    linked_factor_task_id=None, levels=[1.0], segments=[],
                    source_grid_n=4, source_backend="idw",
                    source_value_range=[0.0, 1.0], status="draft",
                    generator_version=cd.GENERATOR_VERSION)
        base.update(kw)
        return ContourDraft(**base)

    # Case A: replace by linked task id keeps the existing id.
    proj = SimpleNamespace(contour_drafts=[
        _draft(id="keep-me", linked_factor_task_id="t1")])
    d = _draft(id="new-id", linked_factor_task_id="t1")
    out = cd.upsert_contour_draft(proj, d)
    # Freeze the scope fields the C++ replay rebuilds verbatim.
    scope = lambda dr: {"id": dr.id,
                        "linked_factor_task_id": dr.linked_factor_task_id,
                        "target_horizon": dr.target_horizon,
                        "factor_type": dr.factor_type}
    case("upsert_draft", "upsert_by_task",
         input={"ledger": [scope(x) for x in proj.contour_drafts],
                "draft": scope(d),
                "updated_at": "2024-01-02T03:04:05Z"},
         expected={"returned_id": out.id, "ledger_ids":
                   [x.id for x in proj.contour_drafts]})

    # Case B: scope match (no task id) replaces same horizon+factor+genver.
    proj = SimpleNamespace(contour_drafts=[
        _draft(id="scope-id", target_horizon="H1", factor_type="厚度")])
    d = _draft(id="other", target_horizon="H1", factor_type="厚度")
    out = cd.upsert_contour_draft(proj, d)
    case("upsert_draft", "upsert_by_scope",
         input={"ledger": [scope(x) for x in proj.contour_drafts],
                "draft": scope(d),
                "updated_at": "2024-01-02T03:04:05Z"},
         expected={"returned_id": out.id, "ledger_ids":
                   [x.id for x in proj.contour_drafts]})

    # Case C: no match -> append with the draft's own id.
    proj = SimpleNamespace(contour_drafts=[
        _draft(id="existing", target_horizon="H2")])
    d = _draft(id="appended", target_horizon="H1")
    out = cd.upsert_contour_draft(proj, d)
    case("upsert_draft", "upsert_append",
         input={"ledger": [scope(x) for x in proj.contour_drafts],
                "draft": scope(d),
                "updated_at": "2024-01-02T03:04:05Z"},
         expected={"returned_id": out.id, "ledger_ids":
                   [x.id for x in proj.contour_drafts]})

    # line_features_from_contour_draft — one skipped short segment.
    draft = _draft(
        id="d1", target_horizon="H1", factor_type="厚度",
        segments=[
            ContourSegment(id="s1", level=1.5,
                           coordinates=[[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]],
                           closed=False, properties={"k": "v"}),
            ContourSegment(id="s2", level=2.5, coordinates=[[9.0, 9.0]],
                           closed=False, properties={}),
        ])
    case("line_features", "lfeat_0",
         input={"draft": {"id": "d1", "factor_type": "厚度",
                          "target_horizon": "H1",
                          "segments": _jsonable(
                              [s.model_dump() for s in draft.segments])}},
         expected=_jsonable(cd.line_features_from_contour_draft(draft)))

    # compile_contour_drafts_for_project — real contourpy extract on a
    # small grid; the C++ test replays the frozen lines through its
    # extract seam and diffs the assembled draft + ledger upsert.
    grid_x = [0.0, 1.0, 2.0, 3.0]
    grid_y = [0.0, 1.0, 2.0]
    grid_z = np.array([[0.0, 1.0, 2.0, 3.0],
                       [1.0, 2.0, 3.0, 4.0],
                       [2.0, 3.0, 4.0, 5.0]])
    task = FactorMapTask(
        name="t1", target_horizon="H1", factor_type="厚度", method="IDW",
        status="complete", source_kind="mixed",
        parameters={"grid_x": grid_x, "grid_y": grid_y,
                    "grid_z": grid_z.tolist(), "grid_n": 4})
    proj = SimpleNamespace(factor_map_tasks=[task], contour_drafts=[])
    cd._now_iso = lambda: "2024-05-06T07:08:09Z"
    drafts = cd.compile_contour_drafts_for_project(
        proj, n_levels=4, apply_to_map=False)
    # Frozen extract seam I/O for the C++ replay: the engine was called
    # with (grid_x, grid_y, grid_z, use_levels); generated ids are replayed
    # in creation order — segments first, then the draft id.
    from geoviz import extract_contour_lines
    lines_dict = extract_contour_lines(
        np.asarray(grid_x), np.asarray(grid_y), grid_z,
        list(drafts[0].levels))
    frozen_lines = {
        str(_num(k)): [
            [[_num(p[0]), _num(p[1])] for p in np.asarray(line)]
            for line in lines
        ]
        for k, lines in sorted(lines_dict.items())
    }
    d0 = drafts[0]
    case("compile_drafts", "compile_0",
         input={"tasks": [{"id": task.id, "name": "t1",
                           "target_horizon": "H1", "factor_type": "厚度",
                           "method": "IDW", "status": "complete",
                           "source_kind": "mixed",
                           "parameters": {"grid_x": grid_x,
                                          "grid_y": grid_y,
                                          "grid_z": grid_z.tolist(),
                                          "grid_n": 4}}],
                "task_ids": None, "only_complete": True, "n_levels": 4,
                "updated_at": "2024-05-06T07:08:09Z"},
         seam={"levels": _nums(d0.levels), "lines": frozen_lines,
               "id_order": {"segment_ids": [s.id for s in d0.segments],
                            "draft_id": d0.id}},
         expected={
             "drafts": _jsonable([d.model_dump() for d in drafts]),
             "ledger_ids": [d.id for d in proj.contour_drafts]})

    # Status gate + id filter: the pending task is skipped — the complete
    # task is filtered out by id. Both gates are exercised at once; the
    # tasks are frozen for the C++ replay (same slice shape as compile_0).
    task2 = FactorMapTask(
        name="t2", target_horizon="H1", factor_type="厚度", method="IDW",
        status="pending", source_kind="mixed",
        parameters={"grid_x": grid_x, "grid_y": grid_y,
                    "grid_z": grid_z.tolist()})
    proj2 = SimpleNamespace(factor_map_tasks=[task, task2],
                            contour_drafts=[])
    drafts2 = cd.compile_contour_drafts_for_project(
        proj2, n_levels=4, apply_to_map=False, task_ids=[task2.id])
    case("compile_drafts", "compile_filtered",
         input={"tasks": [{"id": task.id, "name": "t1",
                           "target_horizon": "H1", "factor_type": "厚度",
                           "method": "IDW", "status": "complete",
                           "source_kind": "mixed",
                           "parameters": {"grid_x": grid_x,
                                          "grid_y": grid_y,
                                          "grid_z": grid_z.tolist(),
                                          "grid_n": 4}},
                          {"id": task2.id, "name": "t2",
                           "target_horizon": "H1", "factor_type": "厚度",
                           "method": "IDW", "status": "pending",
                           "source_kind": "mixed",
                           "parameters": {"grid_x": grid_x,
                                          "grid_y": grid_y,
                                          "grid_z": grid_z.tolist()}}],
                "task_ids": [task2.id], "only_complete": True,
                "n_levels": 4},
         expected={"draft_count": len(drafts2)})


# ---------------------------------------------------------------------------
# dtw_propagation — bounded_dtw_band (ast-lifted) + real DTWEngine.correlate.
# ---------------------------------------------------------------------------

def gen_dtw():
    worker = REPO_ROOT / "paleo_workbench" / "ui" / "pages" / \
        "dtw_propagation_worker.py"
    ns: dict = {"_MAX_DTW_CELLS": 4_000_000}
    band = _load_function(worker, "bounded_dtw_band", ns)
    for i, (n, br) in enumerate(
        [(100, None), (1000, None), (5, None), (10000, 500),
         (50, 3), (2000000, None), (10, 1)]):
        case("dtw_band", f"band_{i}",
             input={"n_samples": n, "band_radius": br},
             expected=int(band(n, br)))

    from geoviz_cross_well.dtw_engine import DTWEngine
    engine = DTWEngine()
    rng = np.random.default_rng(11)
    ref_d = np.linspace(100.0, 200.0, 60)
    ref_v = np.sin(ref_d / 9.0) + rng.standard_normal(60) * 0.05
    tgt_d = np.linspace(95.0, 210.0, 70)
    tgt_v = np.sin((tgt_d - 12.0) / 9.0) + rng.standard_normal(70) * 0.05
    res = engine.correlate(ref_v, ref_d, tgt_v, tgt_d,
                           band_radius=20, ref_depth=150.0)
    case("dtw_correlate", "corr_0",
         input={"ref_values": _nums(ref_v), "ref_depths": _nums(ref_d),
                "tgt_values": _nums(tgt_v), "tgt_depths": _nums(tgt_d),
                "band_radius": 20, "ref_depth": 150.0},
         expected={"feasible": bool(res.feasible),
                   "suggested_depth": _num(res.suggested_depth),
                   "cost": _num(res.cost),
                   "confidence": _num(res.confidence)})

    # ref_depth=None -> engine mid-index fallback (C++ NaN sentinel path).
    res2 = engine.correlate(ref_v, ref_d, tgt_v, tgt_d,
                            band_radius=15, ref_depth=None)
    case("dtw_correlate", "corr_no_ref_depth",
         input={"ref_values": _nums(ref_v), "ref_depths": _nums(ref_d),
                "tgt_values": _nums(tgt_v), "tgt_depths": _nums(tgt_d),
                "band_radius": 15, "ref_depth": None},
         expected={"feasible": bool(res2.feasible),
                   "suggested_depth": _num(res2.suggested_depth),
                   "cost": _num(res2.cost),
                   "confidence": _num(res2.confidence)})

    # Infeasible: |m-n| beyond the band.
    res3 = engine.correlate(ref_v[:10], ref_d[:10], tgt_v, tgt_d,
                            band_radius=3, ref_depth=150.0)
    case("dtw_correlate", "corr_infeasible",
         input={"ref_values": _nums(ref_v[:10]),
                "ref_depths": _nums(ref_d[:10]),
                "tgt_values": _nums(tgt_v), "tgt_depths": _nums(tgt_d),
                "band_radius": 3, "ref_depth": 150.0},
         expected={"feasible": bool(res3.feasible),
                   "suggested_depth": _num(res3.suggested_depth),
                   "cost": _num(res3.cost),
                   "confidence": _num(res3.confidence)})


# ---------------------------------------------------------------------------
# correlation_load — list_well_log_resources ordering/filter/clamp.
# ---------------------------------------------------------------------------

def gen_correlation():
    from paleo_workbench.workflow.stratigraphy_correlation import (
        list_well_log_resources)

    resources = [
        {"id": "r2", "name": "Well B", "type": "well_log", "path": "b.las"},
        {"id": "r1", "name": "Well B", "type": "well_log", "path": "a.las"},
        {"id": "r4", "name": "", "type": "well_log", "path": "e.las"},
        {"id": "r3", "name": "Well A", "type": "seismic", "path": "s.sgy"},
        {"id": "r5", "name": "Well C", "type": "well_log", "path": "c.las"},
    ]
    proj = SimpleNamespace(resources=[SimpleNamespace(**r) for r in resources])
    wells = list_well_log_resources(proj)
    case("well_log_resources", "order_0",
         input={"resources": resources},
         expected=[r.id for r in wells])

    wanted = {"r5", "r1"}
    filtered = [r for r in wells if r.id in wanted]
    case("well_log_resources", "filter_0",
         input={"resources": resources, "resource_ids": ["r5", "r1"],
                "max_wells": 8},
         expected=[r.id for r in filtered])
    case("well_log_resources", "clamp_0",
         input={"resources": resources, "max_wells": 0},
         expected=[r.id for r in wells[: max(1, 0)]])
    case("well_log_resources", "clamp_2",
         input={"resources": resources, "max_wells": 2},
         expected=[r.id for r in wells[:2]])


# ---------------------------------------------------------------------------
# stratal — real geoviz_seismic.stratal + viz.stratal_adapter.
# ---------------------------------------------------------------------------

def gen_stratal():
    from geoviz_seismic.stratal import (
        build_proportional_surfaces, extract_stratal_slice,
        stratal_slice_volume, validate_horizon_pair)
    from paleo_workbench.viz.stratal_adapter import (
        _ms_grids_to_preview_sample_indices, build_stratal_surfaces,
        make_demo_stratal_grids, make_synthetic_demo_volume,
        ms_to_preview_sample_index)

    top = np.array([[2.0, 3.0, np.nan], [4.0, 5.0, 6.0]])
    bot = np.array([[8.0, 9.0, 9.0], [10.0, 11.0, 3.0]])
    case("stratal_validate", "val_0",
         input={"top": _grid(top), "bot": _grid(bot), "n_samples": 12},
         expected=[bool(v) for v in
                   validate_horizon_pair(top, bot,
                                         volume_shape=(2, 3, 12)).ravel()])
    case("stratal_validate", "val_no_shape",
         input={"top": _grid(top), "bot": _grid(bot), "n_samples": None},
         expected=[bool(v) for v in
                   validate_horizon_pair(top, bot).ravel()])

    fracs = [0.25, 0.5, 0.75]
    surfs = build_proportional_surfaces(top, bot, fracs)
    case("stratal_surfaces", "surf_0",
         input={"top": _grid(top), "bot": _grid(bot),
                "fractions": fracs},
         expected=[_grid(s) for s in surfs])

    # Fraction clipping: values outside [0,1] clip like np.clip.
    surfs2 = build_proportional_surfaces(top, bot, [-0.5, 1.5])
    case("stratal_surfaces", "surf_clip",
         input={"top": _grid(top), "bot": _grid(bot),
                "fractions": [-0.5, 1.5]},
         expected=[_grid(s) for s in surfs2])

    vol = np.arange(2 * 3 * 12, dtype=np.float32).reshape(2, 3, 12) * 0.5
    surf = build_proportional_surfaces(top, bot, 0.5)
    for i, (window, mode, order) in enumerate(
            [(0, "rms", 1), (2, "rms", 1), (2, "mean", 1),
             (1, "max", 1), (0, "rms", 0), (3, "mean", 1)]):
        out = extract_stratal_slice(vol, surf, window=window, mode=mode,
                                    order=order)
        case("stratal_extract", f"ext_{i}",
             input={"volume": _volume(vol), "surface": _grid(surf),
                    "window": window, "mode": mode, "order": order},
             expected=_grid(out))

    # NaN window cells are skipped (nanmean/nanmax parity); all-NaN -> NaN.
    vol_nan = vol.copy()
    vol_nan[0, 0, 4:8] = np.nan
    out = extract_stratal_slice(vol_nan, surf, window=3, mode="mean")
    case("stratal_extract", "ext_nan_window",
         input={"volume": _volume(vol_nan), "surface": _grid(surf),
                "window": 3, "mode": "mean", "order": 1},
         expected=_grid(out))

    maps, surfaces = stratal_slice_volume(
        vol, top, bot, fracs, window=1, mode="rms", return_surfaces=True)
    case("stratal_slice_volume", "sv_0",
         input={"volume": _volume(vol), "top": _grid(top),
                "bot": _grid(bot), "fractions": fracs,
                "window": 1, "mode": "rms", "order": 1},
         expected={"maps": [_grid(m) for m in maps],
                   "surfaces": [_grid(s) for s in surfaces]})

    ms = np.array([[100.0, 110.0], [120.0, np.nan]])
    for i, (dt, t0, stride) in enumerate(
            [(2.0, 100.0, 1), (2.0, 100.0, 4), (0.0, 100.0, 2),
             (-1.0, 50.0, 1)]):
        out = ms_to_preview_sample_index(ms, dt_ms=dt, t0_ms=t0,
                                         sample_stride=stride)
        case("ms_to_preview", f"ms_{i}",
             input={"ms": _grid(ms), "dt_ms": dt, "t0_ms": t0,
                    "sample_stride": stride},
             expected=_grid(out))

    # Bilinear resample of full-survey ms grids onto preview indices.
    scene = SimpleNamespace(
        survey=SimpleNamespace(dt_ms=2.0, t0_ms=100.0),
        registration=SimpleNamespace(strides=(4.0, 2.0, 2)))
    top_ms = np.arange(9 * 7, dtype=float).reshape(9, 7) * 2.0 + 100.0
    bot_ms = top_ms + 20.0
    volume = np.zeros((3, 4, 6), dtype=np.float32)
    pair = _ms_grids_to_preview_sample_indices(scene, volume, top_ms, bot_ms)
    case("ms_grids_preview", "msg_0",
         input={"top_ms": _grid(top_ms), "bot_ms": _grid(bot_ms),
                "n_i_prev": 3, "n_x_prev": 4,
                "stride_i": 4.0, "stride_x": 2.0,
                "dt_ms": 2.0, "t0_ms": 100.0, "sample_stride": 2},
         expected=[_grid(pair[0]), _grid(pair[1])])

    # build_stratal_surfaces — valid pair and fully-inverted pair.
    bs = build_stratal_surfaces(top, bot, (2, 3, 12), fractions=fracs)
    case("build_stratal_surfaces", "bss_ok",
         input={"top_sidx": _grid(top), "bot_sidx": _grid(bot),
                "n_samples": 12, "fractions": fracs},
         expected={"surfaces": [_grid(s) for s in bs[0]],
                   "masked": [_grid(bs[1][0]), _grid(bs[1][1])]})
    inv_top = np.array([[9.0, 9.0], [9.0, 9.0]])
    inv_bot = np.array([[1.0, 1.0], [1.0, 1.0]])
    none_out = build_stratal_surfaces(
        inv_top, inv_bot, (2, 3, 12), fractions=fracs)
    case("build_stratal_surfaces", "bss_none",
         input={"top_sidx": _grid(inv_top), "bot_sidx": _grid(inv_bot),
                "n_samples": 12, "fractions": fracs},
         expected=None if none_out is None else "unexpected")

    # Demo volume — freeze the PCG64 noise separately so the C++ test
    # injects the same samples through DemoNoiseFn.
    shape = (6, 7, 10)
    noise = np.random.default_rng(7).standard_normal(shape)
    vol_demo = make_synthetic_demo_volume(shape, seed=7)
    case("demo_volume", "dvol_0",
         input={"shape": list(shape), "seed": 7, "n_reflectors": 3},
         noise=_volume(noise),
         expected=_volume(vol_demo))

    dv, dtop, dbot = make_demo_stratal_grids((6, 7, 10))
    case("demo_grids", "dgrid_0",
         input={"shape": [6, 7, 10]},
         noise=_volume(np.random.default_rng(7).standard_normal((6, 7, 10))),
         expected={"volume": _volume(dv), "top": _grid(dtop),
                   "bot": _grid(dbot)})


# ---------------------------------------------------------------------------
# geomodel primitives — real geoviz_plots.geomodel.primitives.
# ---------------------------------------------------------------------------

def _geom_primitive_payload(v, f, c) -> dict:
    return {"vertices": _nums(np.asarray(v)),
            "faces": [list(map(int, face)) for face in np.asarray(f)],
            "face_colors": _nums(np.asarray(c))}


def gen_geomodel_primitives():
    from geoviz_plots.geomodel.primitives import (
        generate_cylinder_geometry, generate_fault_geometry,
        generate_tube_geometry)

    cases = [
        ("cyl_0", (0.0, 0.0, 0.0), (0.0, 0.0, -30.0), 2.5,
         (0.8, 0.6, 0.4, 0.8), 12),
        ("cyl_degenerate", (1.0, 2.0, 3.0), (1.0, 2.0, 3.0), 2.5,
         (1.0, 0.0, 0.0, 1.0), 12),
        ("cyl_tilted", (-40.0, -40.0, 0.0), (-40.0, -40.0, -30.0), 2.5,
         (0.5, 0.5, 0.5, 0.8), 8),
    ]
    for cid, p1, p2, r, col, res in cases:
        v, f, c = generate_cylinder_geometry(p1, p2, radius=r, color=col,
                                             resolution=res)
        case("geom_cylinder", cid,
             input={"p1": list(p1), "p2": list(p2), "radius": r,
                    "color": list(col), "resolution": res},
             expected=_geom_primitive_payload(v, f, c))

    path = [[-50.0, -20.0, -30.0], [0.0, 0.0, -40.0], [50.0, 20.0, -50.0]]
    v, f, c = generate_tube_geometry(path, radius=3.5,
                                     color=(0.2, 0.8, 0.2, 0.9))
    case("geom_tube", "tube_0",
         input={"path": path, "radius": 3.5,
                "color": [0.2, 0.8, 0.2, 0.9], "resolution": 12},
         expected=_geom_primitive_payload(v, f, c))

    v, f, c = generate_fault_geometry(xlim=(-60, 60), ylim=(-60, 60),
                                      nx=8, ny=8,
                                      color=(0.9, 0.2, 0.2, 0.65))
    case("geom_fault", "fault_0",
         input={"xlim": [-60, 60], "ylim": [-60, 60], "nx": 8, "ny": 8,
                "color": [0.9, 0.2, 0.2, 0.65]},
         expected=_geom_primitive_payload(v, f, c))


# ---------------------------------------------------------------------------
# geological_modeling worker — ast-lifted records + verbatim volume formula.
# ---------------------------------------------------------------------------

def gen_geological_modeling():
    worker = (REPO_ROOT / "paleo_workbench" / "ui" / "pages" /
              "geological_modeling_workers.py")
    literals = _literal_assignments(worker)
    bh_raw = literals["bh_raw"]
    tunnel_raw = literals["tunnel_raw"]
    faults_raw = literals["faults_raw"]

    # Density -> dim mapping (the worker's three-way branch).
    for i, (density, expected_dim) in enumerate(
            [("低", 40), ("中", 80), ("高", 120), ("低分辨率", 40)]):
        dim = 40 if "低" in density else (80 if "中" in density else 120)
        assert dim == expected_dim
        case("geomodel_dim", f"gdim_{i}",
             input={"density": density}, expected=dim)

    # The worker's volume expression, verbatim (vectorized meshgrid form):
    #   val = kk + 8.0*sin(ii/8.0)*cos(jj/8.0); ((val/dim)*255).astype(u8)%256
    # astype(uint8) wraps mod-256; the trailing %256 is an identity no-op on
    # uint8 values (and would raise on NumPy>=2 scalar semantics — the wrap
    # already happened inside astype). Frozen at the real "低" dim=40 the
    # worker produces — the C++ port computes it inline inside
    # run_geological_modeling.
    dim = 40
    ii, jj, kk = np.meshgrid(
        np.arange(dim), np.arange(dim), np.arange(dim), indexing="ij")
    val = kk + 8.0 * np.sin(ii / 8.0) * np.cos(jj / 8.0)
    vol_data = ((val / dim) * 255).astype(np.uint8)
    case("geomodel_volume", "gvol_0",
         input={"density": "低", "expected_dim": dim},
         expected={"dim": dim, "volume_hex": vol_data.tobytes().hex()})

    case("geomodel_records", "grec_0",
         input={},
         expected={"bh_raw": _jsonable(bh_raw),
                   "tunnel_raw": _jsonable(tunnel_raw),
                   "faults_raw": _jsonable(faults_raw)})

    # The worker's own geometry assembly over the records (real engine
    # primitives + the worker's radii/colors/offsets).
    from geoviz_plots.geomodel.primitives import (
        generate_cylinder_geometry, generate_fault_geometry,
        generate_tube_geometry)
    bh_geom = []
    for bh in bh_raw:
        for lyr in bh["layers"]:
            p1 = (bh["x"], bh["y"], -lyr["top"])
            p2 = (bh["x"], bh["y"], -lyr["bottom"])
            v, f, c = generate_cylinder_geometry(
                p1, p2, radius=2.5, color=lyr["color"])
            bh_geom.append({"name": bh["name"],
                            **_geom_primitive_payload(v, f, c)})
    t_geom = []
    for tn in tunnel_raw:
        v, f, c = generate_tube_geometry(tn["path"], radius=3.5,
                                         color=tn["color"])
        t_geom.append({"name": tn["name"],
                       **_geom_primitive_payload(v, f, c)})
    f_geom = []
    for idx, offset in enumerate([20.0, 12.0]):
        v, f, c = generate_fault_geometry(
            xlim=(-60, 60), ylim=(-60, 60), color=faults_raw[idx]["color"])
        vv = np.asarray(v, dtype=np.float32).copy()
        vv[:, 2] += offset
        f_geom.append({"name": faults_raw[idx]["name"],
                       **_geom_primitive_payload(vv, f, c)})
    case("geomodel_scene", "gscene_0",
         input={"demo": True},
         expected={"boreholes": bh_geom, "tunnels": t_geom,
                   "faults": f_geom,
                   "source": "synthetic/demo",
                   "n_borehole_meshes": len(bh_geom)})


# ---------------------------------------------------------------------------
# integrity — sha256 (hashlib) + catalog-state map (ast-lifted) + summary.
# ---------------------------------------------------------------------------

def gen_integrity():
    worker = (REPO_ROOT / "paleo_workbench" / "ui" / "pages" /
              "integrity_worker.py")
    # _CATALOG_STATUS_TO_STATE maps status -> IntegrityState.<MEMBER>; the
    # values are enum references, not literals, so lift them via AST.
    tree = ast.parse(worker.read_text(encoding="utf-8"))
    status_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name)
                        and t.id == "_CATALOG_STATUS_TO_STATE"
                        for t in node.targets)):
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Attribute)):
                    status_map[k.value] = v.attr  # e.g. "VERIFIED"
    for i, status in enumerate(
            ["verified", "modified", "missing", "unknown", "bogus", ""]):
        expected = status_map.get(status, "UNKNOWN")
        case("integrity_catalog_state", f"ics_{i}",
             input={"status": status}, expected=expected)

    for i, payload in enumerate(
            [b"", b"hello world", bytes(range(256)) * 300,
             b"\x00\xff" * 40000]):
        case("sha256", f"sha_{i}",
             input={"bytes_hex": payload.hex()},
             expected=hashlib.sha256(payload).hexdigest())

    # summary_text — f"已校验: {v} · 已修改: {m} · 缺失: {x} · 外部链接: {u}"
    for i, (v, m, x, u) in enumerate(
            [(3, 1, 0, 2), (0, 0, 0, 0), (10, 4, 2, 1)]):
        case("integrity_summary", f"isum_{i}",
             input={"verified": v, "modified": m, "missing": x,
                    "unmanaged": u},
             expected=f"已校验: {v} · 已修改: {m} · 缺失: {x} · 外部链接: {u}")


# ---------------------------------------------------------------------------
# viz_resolve — real VizAdapter supports/ref_from_resource.
# ---------------------------------------------------------------------------

def gen_viz_resolve():
    from paleo_workbench.viz.adapter import VizAdapter
    adapter = VizAdapter.__new__(VizAdapter)

    norm_inputs = [
        ("Well_Log", ".LAS"), ("seismic", "SEGY"), ("GEOJSON", "json"),
        ("  well_log  ", " las "), ("map", ".geojson"),
        ("horizon", "dat"), ("prediction", ""), ("unknown_thing", "xyz"),
        ("formation_tops", "csv"), ("well_head", "txt"),
    ]
    for i, (rtype, fmt) in enumerate(norm_inputs):
        res = SimpleNamespace(type=rtype, format=fmt, id=f"r{i}",
                              name=f"res{i}", path=f"p/{i}")
        ref = adapter.ref_from_resource(res)
        case("viz_resource", f"vres_{i}",
             input={"type": rtype, "format": fmt, "id": f"r{i}",
                    "name": f"res{i}", "path": f"p/{i}"},
             expected={
                 "supports": bool(adapter.supports_resource(res)),
                 "ref": (None if ref is None else {
                     "kind": ref.kind, "id": ref.id, "path": ref.path,
                     "label": ref.label, "source": ref.source})})


# ---------------------------------------------------------------------------
# factor_prepare — schedule orchestration with frozen seam I/O.
# ---------------------------------------------------------------------------

def _task_slice_payload(task) -> dict:
    """Freeze the FactorTaskSlice fields the C++ side reconstructs."""
    return {
        "id": str(task.id), "name": task.name, "status": task.status,
        "target_horizon": task.target_horizon,
        "factor_type": task.factor_type, "method": task.method,
        "source_kind": task.source_kind,
        "seed": task.seed,
        "parameters": _jsonable(dict(task.parameters or {})),
        "grid_metadata": _jsonable(dict(task.grid_metadata or {})),
        "input_snapshot_hash": task.input_snapshot_hash or "",
        "grid_artifact_path": task.grid_artifact_path or "",
    }


def _progress_payload(p) -> dict:
    return {
        "generation": p.generation, "total_tasks": p.total_tasks,
        "clean": p.clean, "dirty": p.dirty, "completed": p.completed,
        "failed": p.failed, "cancelled": p.cancelled, "phase": p.phase,
        "current_task_id": p.current_task_id,
        "current_group": p.current_group, "message": p.message,
    }


def _task_result_payload(r) -> dict:
    return {
        "task_id": r.task_id, "dirty_state": r.dirty_state,
        "reused": bool(r.reused),
        "has_task": r.task is not None,
        "task_status": (r.task.status if r.task is not None else None),
        "task_last_error": (
            (r.task.parameters or {}).get("last_error")
            if r.task is not None else None),
        "scheduled_result_fingerprint": r.scheduled_result_fingerprint,
        "error": r.error,
        "grid_present": r.grid is not None,
    }


def _batch_result_payload(res) -> dict:
    return {
        "generation": res.generation, "method": res.method,
        "task_results": [_task_result_payload(r) for r in res.task_results],
        "clean_count": res.clean_count, "dirty_count": res.dirty_count,
        "executed_count": res.executed_count,
        "failed_count": res.failed_count,
        "cancelled": bool(res.cancelled),
        "cancelled_count": res.cancelled_count,
        "workers": res.workers,
        "created_default_tasks": bool(res.created_default_tasks),
        "grid_n": res.grid_n,
        "power": res.power,
        # ms fields are wall-clock — the C++ test only asserts >= 0.
        "ms_fields_nonneg": ["snapshot_ms", "classify_ms", "execute_ms"],
    }


def _snapshot_payload(snap) -> dict:
    return {
        "generation": snap.generation, "method": snap.method,
        "grid_n": snap.grid_n, "power": snap.power, "force": snap.force,
        "seed": snap.seed, "target_horizon": snap.target_horizon,
        "project_crs": snap.project_crs,
        "tasks": [_task_slice_payload(t) for t in snap.tasks],
        "created_defaults": snap.created_defaults,
    }


def gen_factor_prepare():
    from paleo_workbench.project.models import (
        FactorMapTask, ProjectDocument)
    from paleo_workbench.workflow import factor_prepare_scheduler as fps
    from paleo_workbench.workflow import factor_interpolation as fi
    from paleo_workbench.workflow.interpolation_fingerprint import (
        FactorDirtyState)
    from geoviz import JobCancelled, synthetic_sample_points

    def _project_with_tasks(tasks):
        proj = ProjectDocument.new("oracle")
        proj.factor_map_tasks = list(tasks)
        return proj

    def _mk(name, seed, factor="地层厚度", horizon="H1", **kw):
        base = dict(name=name, target_horizon=horizon,
                    factor_type=factor, method="IDW",
                    source_kind="mixed", seed=seed, status="pending",
                    parameters={})
        base.update(kw)
        return FactorMapTask(**base)

    def _synthesize_points(project, snapshot):
        """The schedule's pre-loop (verbatim): pending tasks get points."""
        for task in project.factor_map_tasks:
            params = task.parameters or {}
            if not params.get("sample_points"):
                task.parameters = {
                    **params,
                    "sample_points": synthetic_sample_points(
                        seed=(task.seed if task.seed is not None
                              else snapshot.seed),
                        factor_type=task.factor_type or task.name)}

    def _capture_real_seams(snapshot):
        """Run the real classify/batch/group-key seams on DEEP COPIES and
        freeze their per-task outputs — what the C++ replay stubs return.

        materialize_execution_project shares the snapshot's task objects;
        running the real batch on them would stamp fingerprints + populate
        the process-global live grid cache BEFORE the schedule under test
        runs, corrupting its own classification. Deep copies keep the
        captured outputs identical without touching the originals.
        """
        import copy
        exec_proj = copy.deepcopy(
            fps.materialize_execution_project(snapshot))
        _synthesize_points(exec_proj, snapshot)
        clean, dirty = fps.classify_snapshot_tasks(
            snapshot, exec_proj, fingerprint_memo={})
        classify = {t.id: {"state": s.value, "result_fp": fp}
                    for t, s, fp in clean + dirty}

        exec2 = copy.deepcopy(
            fps.materialize_execution_project(snapshot))
        _synthesize_points(exec2, snapshot)
        fi.batch_prepare_factor_maps(
            exec2, method=snapshot.method,
            target_horizon=snapshot.target_horizon,
            grid_n=snapshot.grid_n, power=snapshot.power,
            force=snapshot.force, seed=snapshot.seed,
            fingerprint_memo={})
        marks = {t.id: {"status": t.status,
                        "last_error":
                            (t.parameters or {}).get("last_error")}
                 for t in exec2.factor_map_tasks}
        group_keys = {}
        for t, _s, _fp in dirty:
            group_keys[t.id] = fi._task_plan_group_key(
                t, method=snapshot.method, grid_n=snapshot.grid_n,
                power=snapshot.power, project=exec_proj)
        return {"classify": classify,
                "batch": {"rules": [], "marks": marks,
                          "grids": None},  # grids filled from the result
                "group_keys": group_keys}

    def _emit_case(name, snap_payload, workers, seam, log, result, pcheck):
        """Emit a frozen case. `snap_payload` must be captured BEFORE the
        schedule run — the exec project shares task objects, so post-run
        snapshots would carry stamped statuses/fingerprints."""
        grids = [r.task_id for r in result.task_results
                 if r.grid is not None]
        seam["batch"]["grids"] = grids
        case("factor_schedule", name,
             input={"snapshot": snap_payload,
                    "workers": workers},
             seam=seam,
             expected={
                 "progress": log,
                 "result": _batch_result_payload(result)},
             progress_check=pcheck)

    def _collect():
        log = []
        return log, lambda p: log.append(_progress_payload(p))

    # -- Scenario 1: real seams, serial path, clean+dirty mix. -------------
    t_a = _mk("A-厚度", 0)
    proj_seed = _project_with_tasks([t_a])
    fi.batch_prepare_factor_maps(
        proj_seed, method="IDW", target_horizon="H1", grid_n=8,
        power=2.0, force=True, seed=0)
    stamped = proj_seed.factor_map_tasks[0].model_copy(deep=True)
    assert stamped.status == "complete"

    tasks = [stamped,
             _mk("B-砂岩", 1, factor="砂岩含量"),
             _mk("C-砂地比", 2, factor="砂地比"),
             _mk("D-泥岩", 3, factor="泥岩含量")]
    proj = _project_with_tasks(tasks)
    snapshot = fps.build_prepare_snapshot(
        proj, generation=7, method="IDW", grid_n=8, power=2.0, force=False,
        seed=0)
    snap_payload = _snapshot_payload(snapshot)  # pre-run freeze
    seam = _capture_real_seams(snapshot)
    log, emit = _collect()
    result = fps.run_factor_prepare_schedule(
        snapshot, progress=emit, workers=1)
    _emit_case("serial_mixed", snap_payload, 1, seam, log, result, "exact")

    # -- Scenario 2: all-clean early return (grid_n/power defaults quirk). --
    proj2 = _project_with_tasks([stamped.model_copy(deep=True)])
    fi.batch_prepare_factor_maps(
        proj2, method="IDW", target_horizon="H1", grid_n=8, power=3.0,
        force=True, seed=0)
    snap2 = fps.build_prepare_snapshot(
        proj2, generation=8, method="IDW", grid_n=8, power=3.0, force=False,
        seed=0)
    snap2_payload = _snapshot_payload(snap2)
    seam2 = _capture_real_seams(snap2)
    log2, emit2 = _collect()
    result2 = fps.run_factor_prepare_schedule(
        snap2, progress=emit2, workers=2)
    _emit_case("all_clean_quirk", snap2_payload, 2, seam2, log2, result2,
               "exact")

    # -- Scripted-seam scenarios ------------------------------------------
    # Each scripted batch records: oracle_marks{task_id:{status,last_error}}
    # applied by the C++ stub; oracle_rules matched on task NAME first
    # (raise cancelled/error instead of marking); oracle_grids — the ids
    # whose grid_peek returns a payload.
    def _scripted_case(name, tasks, workers, *, classify_map, batch_fn,
                       group_key_map=None, snapshot_kw=None,
                       progress_check="exact", snapshot_override=None):
        kw = dict(generation=11, method="IDW", grid_n=8, power=2.0,
                  force=False, seed=0)
        kw.update(snapshot_kw or {})
        proj = _project_with_tasks(tasks)
        # snapshot_override runs (and freezes) a caller-built snapshot —
        # required when task ids must be known ahead of classify_map
        # (e.g. the synthesized-defaults case regenerates ids per build).
        snap = snapshot_override or fps.build_prepare_snapshot(proj, **kw)

        saved = {
            "classify_snapshot_tasks": fps.classify_snapshot_tasks,
            "batch_prepare_factor_maps": fps.batch_prepare_factor_maps,
            "peek_live_factor_grid": fps.peek_live_factor_grid,
            "group_key": getattr(fi, "_task_plan_group_key", None),
        }
        batch_fn.oracle_marks = {}
        batch_fn.oracle_grids = set()
        try:
            def fake_classify(_snapshot, project, fingerprint_memo=None):
                clean, dirty = [], []
                for task in project.factor_map_tasks:
                    state, fp = classify_map[task.id]
                    pair = (task, FactorDirtyState(state), fp)
                    (clean if state == "CLEAN" else dirty).append(pair)
                return clean, dirty

            fps.classify_snapshot_tasks = fake_classify
            fps.batch_prepare_factor_maps = batch_fn
            fps.peek_live_factor_grid = (
                lambda tid: {"grid_of": tid}
                if tid in batch_fn.oracle_grids else None)
            if group_key_map is not None:
                fi._task_plan_group_key = (
                    lambda task, **kw: group_key_map.get(task.id))

            log, emit = _collect()
            snap_payload = _snapshot_payload(snap)  # pre-run freeze
            result = fps.run_factor_prepare_schedule(
                snap, progress=emit, workers=workers)
        finally:
            fps.classify_snapshot_tasks = saved["classify_snapshot_tasks"]
            fps.batch_prepare_factor_maps = saved[
                "batch_prepare_factor_maps"]
            fps.peek_live_factor_grid = saved["peek_live_factor_grid"]
            if saved["group_key"] is not None:
                fi._task_plan_group_key = saved["group_key"]

        seam = {
            "classify": {tid: {"state": st, "result_fp": fp}
                         for tid, (st, fp) in classify_map.items()},
            "batch": {"rules": getattr(batch_fn, "oracle_rules", []),
                      "marks": batch_fn.oracle_marks,
                      "grids": None},
            "group_keys": group_key_map or {},
        }
        _emit_case(name, snap_payload, workers, seam, log, result,
                   progress_check)

    def _apply_batch(project, **_kw):
        for task in project.factor_map_tasks:
            task.status = "complete"
            _apply_batch.oracle_marks[task.id] = {
                "status": "complete", "last_error": None}
            _apply_batch.oracle_grids.add(task.id)

    # -- Scenario 3: parallel groups (incl. a shared None key). -----------
    t1 = _mk("P1", 0); t2 = _mk("P2", 1); t3 = _mk("P3", 2); t4 = _mk("P4", 3)
    cmap = {t.id: ("DIRTY_VALUES", f"fp-{t.id}") for t in (t1, t2, t3, t4)}
    _apply_batch.oracle_rules = []
    _scripted_case(
        "parallel_groups", [t1, t2, t3, t4], 3,
        classify_map=cmap, batch_fn=_apply_batch,
        group_key_map={t1.id: "grpA", t2.id: "grpA",
                       t3.id: "grpB", t4.id: None},
        progress_check="sorted_by_group")

    # -- Scenario 4: one group raises -> group failure isolation. ---------
    def _fail_named_batch(project, **_kw):
        names = {t.name for t in project.factor_map_tasks}
        if "g-fail" in names:
            raise RuntimeError("boom")
        for task in project.factor_map_tasks:
            task.status = "complete"
            _fail_named_batch.oracle_marks[task.id] = {
                "status": "complete", "last_error": None}
            _fail_named_batch.oracle_grids.add(task.id)
    _fail_named_batch.oracle_rules = [
        {"when_task_name": "g-fail", "raise": "error", "message": "boom",
         "delay_ms": 0}]

    fa = _mk("g-ok-1", 0); fb = _mk("g-ok-2", 1); fc = _mk("g-fail", 2)
    cmap = {t.id: ("DIRTY_GEOMETRY", f"fp-{t.id}") for t in (fa, fb, fc)}
    _scripted_case(
        "parallel_group_failure", [fa, fb, fc], 2,
        classify_map=cmap, batch_fn=_fail_named_batch,
        group_key_map={fa.id: "gA", fb.id: "gA", fc.id: "gB"},
        progress_check="sorted_by_group")

    # -- Scenario 5: JobCancelled inside one group -> cancelled marks. ----
    # The cancelled group sleeps first so the ok group completes before the
    # drain loop sees the raise — deterministic as_completed ordering.
    def _cancel_named_batch(project, **_kw):
        names = {t.name for t in project.factor_map_tasks}
        if "g-cancel" in names:
            time.sleep(0.30)
            raise JobCancelled()
        for task in project.factor_map_tasks:
            task.status = "complete"
            _cancel_named_batch.oracle_marks[task.id] = {
                "status": "complete", "last_error": None}
            _cancel_named_batch.oracle_grids.add(task.id)
    _cancel_named_batch.oracle_rules = [
        {"when_task_name": "g-cancel", "raise": "cancelled",
         "delay_ms": 300}]

    ca = _mk("g-ok", 0); cb = _mk("g-cancel", 1)
    cmap = {t.id: ("DIRTY_VALUES", f"fp-{t.id}") for t in (ca, cb)}
    _scripted_case(
        "parallel_group_cancel", [ca, cb], 2,
        classify_map=cmap, batch_fn=_cancel_named_batch,
        group_key_map={ca.id: "gA", cb.id: "gB"},
        progress_check="exact")

    # -- Scenario 6: serial cancel -> every dirty task marked cancelled. --
    def _cancel_all_batch(project, **_kw):
        raise JobCancelled()
    _cancel_all_batch.oracle_rules = [
        {"when_task_name": "*", "raise": "cancelled", "delay_ms": 0}]

    s1 = _mk("s-1", 0); s2 = _mk("s-2", 1)
    cmap = {t.id: ("MISSING_OUTPUT", f"fp-{t.id}") for t in (s1, s2)}
    _scripted_case("serial_cancel", [s1, s2], 1,
                   classify_map=cmap, batch_fn=_cancel_all_batch,
                   progress_check="exact")

    # -- Scenario 7: serial per-task failure (batch marks, no raise). -----
    def _one_bad_batch(project, **_kw):
        for task in project.factor_map_tasks:
            if task.name == "f-bad":
                task.status = "failed"
                task.parameters = {**(task.parameters or {}),
                                   "last_error": "bad input"}
                _one_bad_batch.oracle_marks[task.id] = {
                    "status": "failed", "last_error": "bad input"}
            else:
                task.status = "complete"
                _one_bad_batch.oracle_marks[task.id] = {
                    "status": "complete", "last_error": None}
                _one_bad_batch.oracle_grids.add(task.id)
    _one_bad_batch.oracle_rules = []

    f1 = _mk("f-ok", 0); f2 = _mk("f-bad", 1)
    cmap = {t.id: ("DIRTY_VALUES", f"fp-{t.id}") for t in (f1, f2)}
    _scripted_case("serial_task_failure", [f1, f2], 1,
                   classify_map=cmap, batch_fn=_one_bad_batch,
                   progress_check="exact")

    # -- Scenario 8: empty task list -> synthesized defaults. -------------
    proj_e = _project_with_tasks([])
    snap_e = fps.build_prepare_snapshot(proj_e, generation=12, method="IDW",
                                        grid_n=8, power=2.0, force=False,
                                        seed=5)
    cmap = {t.id: ("DIRTY_VALUES", f"fp-{t.id}") for t in snap_e.tasks}
    _scripted_case("defaults_created", [], 1,
                   classify_map=cmap, batch_fn=_apply_batch,
                   snapshot_kw=dict(generation=12, seed=5),
                   progress_check="exact",
                   snapshot_override=snap_e)


# ---------------------------------------------------------------------------
# Negative self-check seed: one intentionally-wrong expectation the C++
# harness must detect (mutated nice-levels output).
# ---------------------------------------------------------------------------

def gen_negative_selfcheck():
    from paleo_workbench.workflow import contour_draft as cd
    good = cd.suggest_nice_levels_from_range(0.0, 10.0, n_levels=8)
    bad = list(good)
    bad[0] = bad[0] + 0.5  # intentional drift — harness must flag it
    case("nice_levels_range", "neg_selfcheck_mutated",
         input={"lo": 0.0, "hi": 10.0, "n_levels": 8},
         expected=_nums(bad), expect_mismatch=True)


def main():
    gen_worker_common()
    gen_paths()
    gen_synthetic_points()
    gen_contour()
    gen_dtw()
    gen_correlation()
    gen_stratal()
    gen_geomodel_primitives()
    gen_geological_modeling()
    gen_integrity()
    gen_viz_resolve()
    gen_factor_prepare()
    gen_negative_selfcheck()

    payload = {
        "meta": {
            "generator": "tools/oracle/generate_ui_workers_fixtures.py",
            "slice": "M10 UI-04 core-workers",
            "python": sys.version.split()[0],
            "numpy": np.__version__,
        },
        "cases": CASES,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1,
                   sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"wrote {OUT} ({len(CASES)} cases)")


if __name__ == "__main__":
    main()
