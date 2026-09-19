#!/usr/bin/env python3
"""VIZ-B — cross-well model/orchestration oracle fixtures (frozen from the
real Python reference).

Reference: geo-viz-engine submodule gitlink 08851951 (frozen behaviour
source), packages/geoviz_cross_well + the coordinate contract of
geoviz_well_log.cross_well_widget / connection_overlay. The DTW kernel
itself is NOT re-frozen here — libs/ui_workers already replays
generate_dtw_fixtures.py; this generator freezes the model/planner/tie/
geometry layers that VIZ-B newly ports.

Determinism overlay (documented divergence, see
docs/development/cpp-viz-b/scope.md §2): numpy's SVD eigenvector SIGN is
implementation-defined, and the Python product itself acknowledges that
flipping v1 reverses the whole PCA ordering. The frozen reference
therefore canonicalizes the axis sign (largest-|component| positive,
ties resolved to +x) and uses a STABLE projection sort; the raw numpy
ordering is frozen alongside for documentation. The nearest-neighbour
reference starts from the canonical PCA endpoint and breaks distance
ties by input order (Python dict insertion order parity).

Real well data: the A4/A13/A16 project-area LAS wells (lasio) feed the
picks/tops/section round-trip fixtures with real curve arrays
(decimated ×4 to keep the JSON manageable — recorded in meta).

Run (venv with numpy+lasio+PySide6, offscreen Qt):
  QT_QPA_PLATFORM=offscreen /path/to/venv/bin/python \
      tools/oracle/generate_viz_b_cross_well_fixtures.py

Output: libs/visualization/src/cross_well/cross_well_tests/fixtures/
        viz_b_cross_well_oracle.json

Non-finite numbers are frozen as the tagged strings "inf"/"-inf"/"nan".
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "geo-viz-engine" / "packages"
for _project in ("geoviz_cross_well", "geoviz_well_log", "geoviz_well_tie"):
    sys.path.insert(0, str(PACKAGES / _project))


def _is_editable_finder(finder: object) -> bool:
    name = getattr(finder, "__name__", "") or ""
    return "editable" in name.lower() or "editable" in repr(finder).lower()


sys.meta_path = [f for f in sys.meta_path if not _is_editable_finder(f)]

from geoviz_cross_well.picks_model import HorizonPicksModel  # noqa: E402
from geoviz_cross_well.tops_model import (  # noqa: E402
    FormationTopsModel,
    _assign_color,
    _FORMATION_PALETTE,
)
from geoviz_cross_well import (  # noqa: E402
    plan_section_pca,
    plan_section_nearest_neighbor,
)
from geoviz_cross_well.seismic_tie import SeismicTie  # noqa: E402

import geoviz_cross_well as _gcw  # noqa: E402

assert str(_gcw.__file__).startswith(
    str(PACKAGES)
), f"reference must be this checkout's submodule, got {_gcw.__file__}"

OUT = (
    REPO_ROOT
    / "libs/visualization/src/cross_well/cross_well_tests/fixtures/viz_b_cross_well_oracle.json"
)

LAS_DIR = Path(
    "/home/kevin/projects/paleo_project/data/project_area/井曲线"
)
WELL_DECIMATION = 4


def _num(value) -> object:
    v = float(value)
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    return v


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values).ravel()]


def _picks_snapshot(model: HorizonPicksModel) -> dict:
    # deepcopy: to_dict() shares the live confidence dicts and
    # well_depths lists — later mutations (accept's clear(), set_depth)
    # would retroactively rewrite every stored snapshot.
    return {
        "dict": copy.deepcopy(model.to_dict()),
        "can_undo": model.undo_manager.can_undo(),
        "can_redo": model.undo_manager.can_redo(),
    }


def build_picks_cases() -> list[dict]:
    cases = []
    model = HorizonPicksModel()
    snapshots = []

    a = model.add_pick("Horizon-1", "W1", 1000.0)
    snapshots.append(("add1", _picks_snapshot(model)))
    b = model.add_pick("Sand-2", "W1", 1150.0, source="manual")
    snapshots.append(("add2", _picks_snapshot(model)))
    model.connect_picks(a, "W2", 1002.5)
    snapshots.append(("connect_w2", _picks_snapshot(model)))
    model.connect_picks(a, "W3", 1001.25)
    snapshots.append(("connect_w3", _picks_snapshot(model)))
    model.move_pick(a, "W2", 1004.0)
    snapshots.append(("move_w2", _picks_snapshot(model)))
    # DTW-source pick + accept/reject semantics.
    d = model.add_pick("Auto-3", "W1", 1230.0, source="dtw")
    model.connect_picks(d, "W2", 1233.5)
    pick_d = model.get_pick(d)
    pick_d.confidence["W2"] = 0.83
    snapshots.append(("dtw_add_confidence", _picks_snapshot(model)))
    model.reject_dtw_pick(d)
    snapshots.append(("dtw_reject", _picks_snapshot(model)))
    model.undo()  # reject is a delete -> undoable
    snapshots.append(("undo_reject", _picks_snapshot(model)))
    model.accept_dtw_pick(d)
    snapshots.append(("dtw_accept", _picks_snapshot(model)))
    model.delete_pick(b)
    snapshots.append(("delete2", _picks_snapshot(model)))
    model.undo()
    snapshots.append(("undo_delete", _picks_snapshot(model)))
    model.redo()
    snapshots.append(("redo_delete", _picks_snapshot(model)))
    # Deep undo to the first connect, then redo.
    model.undo()
    model.undo()
    model.undo()
    snapshots.append(("undo_x3", _picks_snapshot(model)))
    model.redo()
    snapshots.append(("redo_x1", _picks_snapshot(model)))

    cases.append(
        {
            "id": "picks_edit_sequence",
            "kind": "picks_sequence",
            "snapshots": [
                {"step": name, **snap} for name, snap in snapshots
            ],
        }
    )

    # Round-trip: to_json -> from_json -> to_json identity (the C++ side
    # must reproduce byte-identical dict content).
    text = model.to_json()
    model2 = HorizonPicksModel()
    model2.from_json(text)
    cases.append(
        {
            "id": "picks_json_roundtrip",
            "kind": "picks_roundtrip",
            "json_text": text,
            "roundtrip_text": model2.to_json(),
            "identical": model2.to_dict() == model.to_dict(),
        }
    )
    # from_json clears undo.
    cases.append(
        {
            "id": "picks_from_json_clears_undo",
            "kind": "picks_roundtrip_undo",
            "can_undo_after_load": model2.undo_manager.can_undo(),
        }
    )
    # Null depth survives the round trip (unconnected wells).
    model3 = HorizonPicksModel()
    c = model3.add_pick("H", "W1", 10.0)
    model3.connect_picks(c, "W2", 12.0)
    pick = model3.get_pick(c)
    pick.set_depth("W2", None)  # disconnect W2 (depth becomes None)
    cases.append(
        {
            "id": "picks_null_depth",
            "kind": "picks_roundtrip",
            "json_text": model3.to_json(),
            "connected_wells": model3.get_pick(c).connected_wells(),
            "depth_for_w2": model3.get_pick(c).depth_for_well("W2"),
        }
    )
    return cases


TOPS_CSV = "\n".join(
    [
        "# well,formation,depth",
        "W1,Formation-A,1000.5",
        "W1,Formation-B,1150.0",
        "W2,Formation-A,1005.25",
        "Formation-A,Formation-B,not-a-number",  # bad depth -> skipped
        "W2,Formation-B,1152.75",
        "W3,Formation-B,1160.0",
        "",
        "W3,Formation-A,1008.0",
    ]
) + "\n"


def build_tops_cases() -> list[dict]:
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tops.csv"
        path.write_text(TOPS_CSV, encoding="utf-8")
        model = FormationTopsModel()
        model.load_csv(str(path))
        all_tops = [
            {
                "well": t.well_name,
                "formation": t.formation_name,
                "depth": _num(t.depth_m),
                "color": t.color,
            }
            for t in model.all_tops()
        ]
        out_path = Path(tmp) / "tops_out.csv"
        model.save_csv(str(out_path))
        # newline="": csv.writer's \r\n terminator must survive into the
        # fixture byte-for-byte (default reads would translate it away).
        with open(out_path, "r", encoding="utf-8", newline="") as saved_file:
            saved_text = saved_file.read()
        cases.append(
            {
                "id": "tops_csv_roundtrip",
                "kind": "tops_csv",
                "csv_text": TOPS_CSV,
                "tops": all_tops,
                "formation_names": model.formation_names(),
                "well_names": model.well_names(),
                "saved_text": saved_text,
            }
        )
        # add/delete semantics.
        model.add_top(
            type(model.all_tops()[0])("W4", "Formation-A", 1010.0, "")
        )
        model.delete_top("W1", "Formation-B")
        cases.append(
            {
                "id": "tops_add_delete",
                "kind": "tops_mutate",
                "tops": [
                    {
                        "well": t.well_name,
                        "formation": t.formation_name,
                        "depth": _num(t.depth_m),
                        "color": t.color,
                    }
                    for t in model.all_tops()
                ],
                "formation_names": model.formation_names(),
                "well_names": model.well_names(),
            }
        )
    # Colour assignment table (first-seen palette + overflow hash).
    existing: dict[str, str] = {}
    colours = []
    for name in [f"F{i}" for i in range(13)]:
        colours.append(
            {"formation": name, "assigned": _assign_color(name, existing)}
        )
        existing.setdefault(name, _assign_color(name, existing))
    cases.append(
        {
            "id": "tops_palette_assignment",
            "kind": "tops_palette",
            "palette": list(_FORMATION_PALETTE),
            "assignments": colours,
        }
    )
    return cases


def _canonical_pca_reference(wells: list[tuple[str, float, float]]):
    """numpy math + canonical sign + stable sort (the frozen contract)."""
    coords = np.array([[w[1], w[2]] for w in wells])
    centroid = coords.mean(axis=0)
    centered = coords - centroid
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    v1 = vt[0].copy()
    if (abs(v1[0]) >= abs(v1[1]) and v1[0] < 0.0) or (
        abs(v1[1]) > abs(v1[0]) and v1[1] < 0.0
    ):
        v1 = -v1
    projections = centered @ v1
    order = np.argsort(projections, kind="stable")
    return [int(i) for i in order], [float(p) for p in projections]


def build_planner_cases() -> list[dict]:
    cases = []
    layouts = {
        "collinear_diag": [
            ("A", 0.0, 0.0),
            ("B", 1.0, 1.0),
            ("C", 2.0, 2.0),
            ("D", 3.0, 3.0),
            ("E", 4.0, 4.0),
        ],
        "reversed_input_order": [
            ("E", 4.0, 4.0),
            ("D", 3.0, 3.0),
            ("C", 2.0, 2.0),
            ("B", 1.0, 1.0),
            ("A", 0.0, 0.0),
        ],
        "dogleg": [
            ("A", 0.0, 0.0),
            ("B", 1.0, 0.2),
            ("C", 1.2, 1.5),
            ("D", 0.4, 2.6),
            ("E", -0.8, 3.0),
        ],
        "grid": [
            ("A", 0.0, 0.0),
            ("B", 0.0, 1.0),
            ("C", 1.0, 0.0),
            ("D", 1.0, 1.0),
            ("E", 0.5, 0.5),
        ],
        "two_wells_identity": [("A", 0.0, 0.0), ("B", 5.0, 5.0)],
        "tie_break": [
            ("A", 0.0, 0.0),
            ("B", 1.0, 0.0),
            ("C", 0.5, 0.0),
            ("D", 0.5, 0.0),
            ("E", -1.0, 0.0),
        ],
    }
    for name, wells in layouts.items():
        canonical, projections = _canonical_pca_reference(wells)
        raw = plan_section_pca(wells)
        raw_nn = plan_section_nearest_neighbor(wells)
        canonical_nn, _ = _nn_reference(wells)
        cases.append(
            {
                "id": f"planner_{name}",
                "kind": "planner",
                "wells": [
                    {"name": w[0], "lng": w[1], "lat": w[2]} for w in wells
                ],
                "pca_canonical": canonical,
                "pca_numpy_raw": [wells.index(w) for w in raw],
                "nn_canonical": canonical_nn,
                "nn_numpy_raw": [wells.index(w) for w in raw_nn],
                "projections": [_num(p) for p in projections],
            }
        )
    # Unknown method raises.
    try:
        from geoviz_cross_well import plan_section

        plan_section([("A", 0.0, 0.0), ("B", 1.0, 1.0)], "bogus")
        err = None
    except ValueError as exc:
        err = f"ValueError: {exc}"
    cases.append(
        {"id": "planner_unknown_method", "kind": "planner_error", "error": err}
    )
    return cases


def _nn_reference(wells: list[tuple[str, float, float]]):
    canonical, _ = _canonical_pca_reference(wells)
    parsed: dict[str, tuple[float, float]] = {}
    for w in wells:
        parsed[w[0]] = (w[1], w[2])
    start_name = wells[canonical[0]][0]
    path = [canonical[0]]
    visited = {start_name}
    current = start_name
    while len(path) < len(parsed):
        cx, cy = parsed[current]
        nearest, best = None, float("inf")
        for name, (x, y) in parsed.items():  # insertion order ties
            if name in visited:
                continue
            dist = (x - cx) ** 2 + (y - cy) ** 2
            if dist < best:
                best, nearest = dist, name
        if nearest is None:
            break
        path.append(wells.index(next(w for w in wells if w[0] == nearest)))
        visited.add(nearest)
        current = nearest
    return path, None


TIE_CSV = "\n".join(
    [
        "depth_m,twt,well",
        "1100.0,560.0,W1",
        "1000.0,520.0,W1",  # descending row -> sorted on load
        "1050.0,540.5,W1",
        "# comment",
        "1200.0,610.0,W2",
        "1250.0,635.0,W2",
        "900.0,470.0,W2",
    ]
) + "\n"


def build_tie_cases() -> list[dict]:
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "checkshot.csv"
        path.write_text(TIE_CSV, encoding="utf-8")
        tie = SeismicTie()
        tie.load_csv(str(path))
        tables = []
        for name in tie.well_names():
            table = tie.table_for_well(name)
            tables.append(
                {
                    "well": name,
                    "depths": _nums(table.depths_m),
                    "twts": _nums(table.twt_ms),
                }
            )
        probes = [
            {"well": "W1", "depth": 1025.0},
            {"well": "W1", "depth": 800.0},  # clamped low
            {"well": "W1", "depth": 2000.0},  # clamped high
            {"well": "W2", "depth": 1225.0},
            {"well": "MISSING", "depth": 1000.0},
        ]
        cases.append(
            {
                "id": "seismic_tie_csv",
                "kind": "seismic_tie",
                "csv_text": TIE_CSV,
                "tables": tables,
                "well_names": tie.well_names(),
                "twt_probes": [
                    None if tie.depth_to_twt(p["well"], p["depth"]) is None
                    else _num(tie.depth_to_twt(p["well"], p["depth"]))
                    for p in probes
                ],
                "depth_probes": [
                    {"well": "W1", "twt": 530.0},
                    {"well": "W1", "twt": 999.0},
                    {"well": "W2", "twt": 622.5},
                ],
                "depth_probe_results": [
                    _num(tie.twt_to_depth(p["well"], p["twt"]))
                    for p in [
                        {"well": "W1", "twt": 530.0},
                        {"well": "W1", "twt": 999.0},
                        {"well": "W2", "twt": 622.5},
                    ]
                ],
            }
        )
    return cases


def build_geometry_cases() -> list[dict]:
    """Drive the REAL geoviz_well_log coordinate helpers on fake hosts
    (identity mapTo) — the formulas are the frozen contract."""
    from types import SimpleNamespace

    from geoviz_well_log.cross_well_widget import CrossWellWidget

    def fake_canvas(depth_top, depth_bottom, header_h, height):
        track = SimpleNamespace(
            depth_top=depth_top,
            depth_bottom=depth_bottom,
            depth_span=depth_bottom - depth_top,
            header_height=header_h,
        )
        return SimpleNamespace(
            tracks=[track],
            height=lambda: height,
            mapTo=lambda parent, point: point,
            rect=lambda: SimpleNamespace(),
        )

    cases = []
    probes = [900.0, 1000.0, 1050.0, 1100.0, 1200.0]
    canvas = fake_canvas(1000.0, 1100.0, 56.0, 456.0)
    ys = [
        float(CrossWellWidget._y_to_depth(canvas, y))
        for y in [0.0, 56.0, 256.0, 456.0, -20.0]
    ]
    # depth_to_y through the real overlay method with an identity map.
    from geoviz_well_log.connection_overlay import ConnectionOverlay

    fake_overlay = SimpleNamespace(parent=lambda: None)
    depth_ys = [
        float(ConnectionOverlay.depth_to_y(fake_overlay, canvas, d))
        for d in probes
    ]
    cases.append(
        {
            "id": "geometry_normal",
            "kind": "section_geometry",
            "depth_top": 1000.0,
            "depth_bottom": 1100.0,
            "header_h": 56.0,
            "canvas_h": 456.0,
            "y_probes": [0.0, 56.0, 256.0, 456.0, -20.0],
            "y_to_depth": [_num(v) for v in ys],
            "depth_probes": probes,
            "depth_to_y": [_num(v) for v in depth_ys],
        }
    )
    degenerate_span = fake_canvas(1000.0, 1000.0, 56.0, 456.0)
    tiny = fake_canvas(1000.0, 1100.0, 600.0, 456.0)  # content_h <= 0
    cases.append(
        {
            "id": "geometry_degenerate",
            "kind": "section_geometry",
            "span0_y_to_depth": CrossWellWidget._y_to_depth(
                degenerate_span, 200.0
            ),
            "span0_depth_to_y": _num(
                ConnectionOverlay.depth_to_y(
                    fake_overlay, degenerate_span, 1050.0
                )
            ),
            "tiny_y_to_depth": CrossWellWidget._y_to_depth(tiny, 200.0),
            "tiny_depth_to_y": _num(
                ConnectionOverlay.depth_to_y(fake_overlay, tiny, 1050.0)
            ),
        }
    )
    return cases



class FakeWheelEvent:
    def __init__(self, angle_delta_y: int, y: float):
        self._angle = angle_delta_y
        self._y = y

    def angleDelta(self):
        return SimpleNamespaceAngle(self._angle)

    def position(self):
        return SimpleNamespacePos(0.0, self._y)

    def accept(self):
        pass


class FakeMouseEvent:
    def __init__(self, y: float):
        self._y = y

    def position(self):
        return SimpleNamespacePos(0.0, self._y)

    def accept(self):
        pass


class SimpleNamespaceAngle:
    def __init__(self, y: int):
        self._y = y

    def y(self) -> int:
        return self._y


class SimpleNamespacePos:
    def __init__(self, x: float, y: float):
        self._x = x
        self._y = y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


def build_preview_cases() -> dict:
    from PySide6.QtWidgets import QApplication

    from geoviz_cross_well.formation_preview import (
        FormationTopsPreviewWidget,
    )
    from geoviz_cross_well.tops_model import FormationTop

    app = QApplication.instance() or QApplication([])
    widget = FormationTopsPreviewWidget()
    tops_data = [
        ("W1", [("Formation-A", 1000.0), ("Formation-B", 1150.0)]),
        ("W2", [("Formation-A", 1005.0), ("Formation-B", 1152.5)]),
        ("W3", [("Formation-B", 1160.0)]),  # A missing in the middle
        ("W4", [("Formation-A", 1012.0), ("Formation-B", 1170.0)]),
    ]
    tops = [
        FormationTop(well_name=w, formation_name=n, depth_m=d)
        for w, formations in tops_data
        for n, d in formations
    ]
    widget.set_tops(tops)
    widget.resize(640, 480)
    # _connectors: (from_well_index, from_top, to_top) — adjacency rule.
    connections = [
        {
            "from_index": int(c[0]),
            "from_well": c[1].well_name,
            "from_formation": c[1].formation_name,
            "from_depth": _num(c[1].depth_m),
            "to_well": c[2].well_name,
            "to_formation": c[2].formation_name,
            "to_depth": _num(c[2].depth_m),
        }
        for c in widget._connectors
    ]
    full = widget._full_depth_range
    clamped = [
        widget._clamped_view_range(lo, hi)
        for lo, hi in [
            (0.0, 1.0),
            (990.0, 1180.0),
            (1000.0, 1100.0),
            (1100.0, 1200.0),
            (1155.0, 1155.0),
            (1050.0, 1040.0),
        ]
    ]
    zoomed = []
    for anchor_y in (38.0, 200.0, 400.0):
        widget._view_depth_range = (1000.0, 1200.0)
        widget.wheelEvent(FakeWheelEvent(120, anchor_y))
        zoomed.append(list(widget._view_depth_range))
    for anchor_y in (200.0,):
        widget._view_depth_range = (1000.0, 1200.0)
        widget.wheelEvent(FakeWheelEvent(-120, anchor_y))
        zoomed.append(list(widget._view_depth_range))
    panned = []
    for dy in (-50.0, 60.0):
        widget._drag_start_y = 200.0
        widget._drag_start_range = (1000.0, 1200.0)
        widget._view_depth_range = (1000.0, 1200.0)
        widget.mouseMoveEvent(FakeMouseEvent(200.0 + dy))
        panned.append(list(widget._view_depth_range))
    depth_ys = []
    for depth in (1000.0, 1080.0, 1160.0):
        widget._view_depth_range = (1000.0, 1200.0)
        depth_ys.append(_num(widget._depth_y(depth)))
    # Zero-span view centres vertically.
    widget._view_depth_range = (1100.0, 1100.0)
    zero_span_y = _num(widget._depth_y(1100.0))

    return {
        "id": "formation_preview",
        "kind": "formation_preview",
        "tops": [
            {"well": w, "formation": n, "depth": _num(d)}
            for w, formations in tops_data
            for n, d in formations
        ],
        "width": 640.0,
        "height": 480.0,
        "full_range": [_num(full[0]), _num(full[1])],
        "connections": connections,
        "clamped_views": [[_num(v) for v in pair] for pair in clamped],
        "zoomed_views": [[_num(v) for v in pair] for pair in zoomed],
        "panned_views": [[_num(v) for v in pair] for pair in panned],
        "depth_ys": depth_ys,
        "zero_span_y": zero_span_y,
        "margins": {
            "left": widget._LEFT,
            "right": widget._RIGHT,
            "top": widget._TOP,
            "bottom": widget._BOTTOM,
        },
    }


def _load_real_wells() -> list[dict]:
    import lasio

    wells = []
    coords = {"A4": (118.72, 28.31), "A13": (118.75, 28.33), "A16": (118.78, 28.29)}
    for name in ("A4", "A13", "A16"):
        las = lasio.read(LAS_DIR / f"{name}.Las")
        slice_ = slice(0, len(las.index), WELL_DECIMATION)
        depth = np.asarray(las["DEPT"])[slice_]
        curves = []
        for mnemonic, unit in (("GR", None), ("AC", None), ("DEN", None)):
            if mnemonic not in las.keys():
                continue
            curve = next(c for c in las.curves if c.mnemonic == mnemonic)
            curves.append(
                {
                    "name": mnemonic,
                    "unit": curve.unit,
                    "depths": _nums(depth),
                    "values": _nums(np.asarray(las[mnemonic])[slice_]),
                }
            )
        wells.append(
            {
                "name": name,
                "lng": coords[name][0],
                "lat": coords[name][1],
                "curves": curves,
            }
        )
    return wells


def main() -> None:
    cases: list[dict] = []
    cases.extend(build_picks_cases())
    cases.extend(build_tops_cases())
    cases.extend(build_planner_cases())
    cases.extend(build_tie_cases())
    geometry_cases, _ = build_geometry_cases()
    cases.extend(geometry_cases)
    preview_case = build_preview_cases()
    wells = _load_real_wells()
    payload = {
        "meta": {
            "generator": "tools/oracle/generate_viz_b_cross_well_fixtures.py",
            "reference": "geo-viz-engine@08851951 packages/geoviz_cross_well",
            "numpy": np.__version__,
            "python": sys.version.split()[0],
            "well_decimation": WELL_DECIMATION,
            "determinism": "canonical PCA sign (largest-|comp| positive) + stable projection sort; NN ties by input order",
        },
        "cases": cases,
        "formation_preview": preview_case,
        "real_wells": {
            "kind": "real_wells",
            "source": "lasio 0.32 + project_area LAS (A4/A13/A16)",
            "wells": wells,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"wrote {OUT} ({len(cases)} cases, preview 1, {len(wells)} real wells)"
    )


if __name__ == "__main__":
    main()
