#!/usr/bin/env python3
"""Oracle for CONV-GEO3D (native 3D geo-viz viewer).

Freezes, by calling the real Python modules:
  * paleo_workbench.viz.geomodel.scene_adapter
        (ObjectStyle defaults, _FACIES_PALETTE, _facies_face_colors,
         the per-axis horizon decimation ceiling)
  * paleo_workbench.viz.geomodel.measurements (format_result texts)
  * paleo_workbench.ui.pages.geo3d_workspace
        (_as_bool / _as_float coercions, save_state payload structure
         with demo provenance exclusion)
  * paleo_workbench.project.models.Geo3DWorkspaceState (seven-key schema)

Writes:
  * libs (tests) fixtures: tests/cpp/geo3d_viz/fixtures/geo3d_style_oracle.json
  *                        tests/cpp/geo3d_viz/fixtures/geo3d_state_oracle.json

Run with the conversion oracle venv:
  PYTHONPATH=<main checkout root> python3 tools/oracle/generate_geo3d_fixtures.py

PySide6 is only needed for the save_state scenario (the controller is a
QObject); without it the script freezes the numpy-only halves.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "tests" / "cpp" / "geo3d_viz" / "fixtures"


def freeze_style_oracle() -> dict:
    import numpy as np

    from paleo_workbench.viz.geomodel.scene_adapter import (
        ObjectStyle,
        _facies_face_colors,
        _FACIES_PALETTE,
    )

    style = ObjectStyle()
    payload = {
        "source": "paleo_workbench/viz/geomodel/scene_adapter.py",
        "generator": "tools/oracle/generate_geo3d_fixtures.py",
        "object_style": {
            "color": list(style.color),
            "opacity": style.opacity,
            "well_color": list(style.well_color),
            "well_width": style.well_width,
            "horizon_color": list(style.horizon_color),
            "fault_color": list(style.fault_color),
            "volume_color": list(style.volume_color),
            "tunnel_color": list(style.tunnel_color),
            "measurement_color": list(style.measurement_color),
            "selected_color": list(style.selected_color),
            "label_color": list(style.label_color),
            "show_well_labels": style.show_well_labels,
        },
        "facies_palette": [
            [round(float(v), 6) for v in row] for row in _FACIES_PALETTE
        ],
    }
    facies = [0, 1, 2, 99, 1, 3, 0, 2]  # 99 clamps to the last palette row
    faces = [[0, 1, 2], [3, 4, 5], [6, 7, 0], [1, 3, 5]]
    means = _facies_face_colors(
        np.asarray(facies), np.asarray(faces, dtype=np.int64)
    )
    payload["facies_face_colors"] = {
        "facies": facies,
        "faces": faces,
        "expected": [
            [round(float(v), 6) for v in face] for face in means
        ],
    }
    return payload


def freeze_decimation_oracle() -> dict:
    from paleo_workbench.viz.geomodel.scene_adapter import _MAX_HORIZON_DIM

    def stride(n: int) -> int:
        return max(1, math.ceil(max(n - 1, 1) / _MAX_HORIZON_DIM))

    return {
        "max_dim": _MAX_HORIZON_DIM,
        "cases": [
            {"shape": [1024, 1024], "stride": [stride(1024), stride(1024)]},
            {"shape": [513, 513], "stride": [stride(513), stride(513)]},
            {"shape": [64, 64], "stride": [stride(64), stride(64)]},
        ],
    }


def freeze_format_result_oracle() -> dict:
    from paleo_workbench.viz.geomodel import measurements as geo_measure

    d = geo_measure.distance((0.0, 0.0, 0.0), (3.0, 4.0, 0.0), crs="EPSG:4326")
    p = geo_measure.point_coordinate((1.0, 2.0, 3.0), crs="EPSG:4326")
    return {
        "distance": geo_measure.format_result(d),
        "point": geo_measure.format_result(p),
    }


def freeze_coercion_oracle() -> dict:
    from paleo_workbench.ui.pages.geo3d_workspace import _as_bool, _as_float

    cases = []
    for value, default in [
        (True, False),
        ("false", True),
        ("", True),
        (1, False),
        (0.5, True),
        ("YES", False),
        ("off", True),
        (None, True),
    ]:
        cases.append(
            {
                "value": value,
                "default": default,
                "expected": _as_bool(value, default),
            }
        )
    float_cases = []
    for value, default, lo, hi in [
        ("0.75", 0.5, 0.0, 1.0),
        (2.0, 0.5, 0.0, 1.0),
        (float("nan"), 0.25, None, None),
        ("bogus", 0.25, None, None),
        (-5.0, 0.0, 1.0, None),
    ]:
        float_cases.append(
            {
                "value": value,
                "default": default,
                "lo": lo,
                "hi": hi,
                "expected": _as_float(value, default, lo=lo, hi=hi),
            }
        )
    return {"as_bool": cases, "as_float": float_cases}


def freeze_state_oracle() -> dict:
    """save_state structure for a frozen scenario (needs PySide6)."""
    from paleo_workbench.ui.pages.geo3d_workspace import (
        Geo3DWorkspaceController,
    )
    from paleo_workbench.viz.geomodel import measurements as geo_measure
    from paleo_workbench.viz.geomodel.builders import (
        build_simplified_vertical_well,
    )
    from paleo_workbench.viz.geomodel.domain import Provenance

    controller = Geo3DWorkspaceController(lambda: None)  # viewport absent
    well = build_simplified_vertical_well(
        "W-1", (10.0, 20.0, 0.0), 120.0, crs="EPSG:4326"
    )
    controller.add_object(well)
    demo = build_simplified_vertical_well(
        "W-demo", (0.0, 0.0, 0.0), 10.0, crs="demo",
        provenance=Provenance(source_kind="demo", demo=True),
    )
    controller.add_object(demo)
    record = geo_measure.distance(
        (0.0, 0.0, 0.0), (3.0, 4.0, 0.0), crs="EPSG:4326"
    )
    controller.assembly.add(record)
    controller.set_measure_mode("distance")
    controller.set_selected("well:w-1", broadcast=False)
    controller.set_axis_clip("x", True, 0.25, False)

    payload = controller.save_state()
    return {
        "source": (
            "paleo_workbench/ui/pages/geo3d_workspace.py::save_state + "
            "paleo_workbench/project/models.py::Geo3DWorkspaceState"
        ),
        "payload_keys": list(payload.keys()),
        "expected": {
            "objects_count": len(payload["objects"]),
            "demo_objects_excluded": True,
            "measurements": [
                {
                    "object_id": m["object_id"],
                    "name": m["name"],
                    "measurement_kind": m["measurement_kind"],
                    "result": m["result"],
                    "unit": m["unit"],
                    "crs": m["crs"],
                    "vertical_domain": m["vertical_domain"],
                    "extra_keys": sorted(m["extra"].keys()),
                }
                for m in payload["measurements"]
            ],
            "clip": payload["clip"],
            "camera_empty_without_viewport": payload["camera"] == {},
            "views": payload["views"],
            "selected": payload["selected"],
        },
        "coercions": freeze_coercion_oracle(),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    style = freeze_style_oracle()
    style["decimation"] = freeze_decimation_oracle()
    style["format_result"] = freeze_format_result_oracle()
    (OUT_DIR / "geo3d_style_oracle.json").write_text(
        json.dumps(style, indent=2) + "\n", encoding="utf-8"
    )
    try:
        state = freeze_state_oracle()
    except Exception as exc:  # pragma: no cover - PySide6 absent
        print(f"state oracle skipped ({exc})")
        return 0
    (OUT_DIR / "geo3d_state_oracle.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
