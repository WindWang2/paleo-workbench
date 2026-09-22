#!/usr/bin/env python3
"""Oracle fixture generator for the C++ factor-extract kernel (M6).

Imports the REAL implementation
(paleo_workbench.mapping.geological_pipeline.pipeline.GeologicalMappingPipeline.extract_factors)
and freezes its outputs to JSON so the C++ port in libs/mapping_kernel can be
verified against the Python extraction core. Regenerate with:

    python3 tools/oracle/generate_extract_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping.geological_pipeline.pipeline import (  # noqa: E402
    GeologicalMappingPipeline,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _point_json(p) -> dict:
    return {
        "name": p.name,
        "value": p.value,
        "unit": p.unit,
        "well_id": p.well_id,
        "well_name": p.well_name,
        "x": p.x,
        "y": p.y,
        "crs": p.crs,
        "formation": p.formation,
        "qc_flag": p.qc_flag,
        "metadata": p.metadata,
    }


def _dataset_json(ds) -> dict:
    return {
        "factor_name": ds.factor_name,
        "unit": ds.unit,
        "target_horizon": ds.target_horizon,
        "crs": ds.crs,
        "points": [_point_json(p) for p in ds.points],
        "metadata": ds.metadata,
    }


def _case(
    cid: str,
    records,
    factor_name: str,
    *,
    target_horizon: str = "",
    unit=None,
    crs: str = "",
) -> dict:
    ds = GeologicalMappingPipeline().extract_factors(
        records,
        factor_name,
        target_horizon=target_horizon,
        unit=unit,
        crs=crs,
    )
    return {
        "id": cid,
        "records": records,
        "factor_name": factor_name,
        "target_horizon": target_horizon,
        "unit": unit,
        "crs": crs,
        "expected": _dataset_json(ds),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    cases = [
        _case(
            "zero_origin",
            [
                {"well_id": "W0", "name": "origin", "x": 0.0, "y": 0.0, "porosity": 15.0},
                {"well_id": "W1", "name": "w1", "x": 114.0, "y": 22.5, "porosity": 18.0},
            ],
            "porosity",
        ),
        _case(
            "no_cross_pair",
            [{"well_id": "BAD", "x": 114.0, "lat": 22.5, "porosity": 10.0}],
            "porosity",
        ),
        _case(
            "project_beats_xy",
            [
                {
                    "well_id": "W1",
                    "x": 114.0,
                    "y": 22.5,
                    "project_x": 500000.0,
                    "project_y": 3400000.0,
                    "porosity": 12.0,
                }
            ],
            "porosity",
        ),
        _case(
            "missing_y",
            [
                {"well_id": "OK", "x": 1.0, "y": 2.0, "porosity": 10.0},
                {"well_id": "NOY", "x": 5.0, "porosity": 11.0},
                {"well_id": "NOX", "y": 7.0, "porosity": 12.0},
            ],
            "porosity",
        ),
        _case(
            "mixed_families",
            [
                {
                    "well_id": "P",
                    "project_x": 500000.0,
                    "project_y": 3400000.0,
                    "porosity": 10.0,
                },
                {"well_id": "G", "lng": 114.1, "lat": 22.6, "porosity": 12.0},
            ],
            "porosity",
        ),
        _case(
            "aliases_porosity",
            [
                {"well_id": "A", "x": 1.0, "y": 2.0, "POR": 10.0},
                {"well_id": "B", "x": 3.0, "y": 4.0, "porosity": 11.0},
                {"well_id": "C", "x": 5.0, "y": 6.0, "孔隙度": 12.0},
            ],
            "porosity",
        ),
        _case(
            "factor_name_POR",
            [{"well_id": "W", "name": "n", "x": 1.0, "y": 2.0, "POR": 11.0}],
            "POR",
        ),
        _case(
            "derived_sand_ratio",
            [
                {
                    "well_id": "w1",
                    "name": "W1",
                    "x": 1.0,
                    "y": 2.0,
                    "H_s": 4.0,
                    "H_t": 8.0,
                }
            ],
            "砂地比",
        ),
        _case(
            "mixed_derived_measured",
            [
                {
                    "well_id": "w1",
                    "name": "W1",
                    "x": 1.0,
                    "y": 2.0,
                    "H_s": 4.0,
                    "H_t": 8.0,
                },
                {"well_id": "w2", "name": "W2", "x": 3.0, "y": 4.0, "R_s": 50.0},
            ],
            "砂地比",
        ),
        _case(
            "derived_thickness",
            [
                {
                    "well_id": "w1",
                    "name": "W1",
                    "x": 1.0,
                    "y": 2.0,
                    "base_depth": 120.0,
                    "top_depth": 80.0,
                }
            ],
            "地层厚度",
        ),
        _case(
            "only_z_empty",
            [{"well_id": "w1", "name": "W1", "x": 1.0, "y": 2.0, "z": 10.0}],
            "砂地比",
        ),
        _case(
            "probability_unit_1",
            [{"well_id": "w1", "x": 1.0, "y": 2.0, "probability": 0.75}],
            "probability",
        ),
        _case(
            "nested_metadata_porosity",
            [
                {
                    "well_id": "W",
                    "x": 1.0,
                    "y": 2.0,
                    "properties": {"k": 1},
                    "metadata": {"porosity": 17.5},
                }
            ],
            "porosity",
        ),
        _case(
            "coordinates_array",
            [{"well_id": "W", "coordinates": [114.1, 22.5], "porosity": 10.0}],
            "porosity",
        ),
        _case(
            "unit_null",
            [{"well_id": "w1", "x": 1.0, "y": 2.0, "porosity": 1.0}],
            "porosity",
            unit=None,
        ),
        _case(
            "unit_empty",
            [{"well_id": "w1", "x": 1.0, "y": 2.0, "porosity": 1.0}],
            "porosity",
            unit="",
        ),
        _case(
            "crs_empty",
            [{"well_id": "w1", "x": 1.0, "y": 2.0, "porosity": 1.0}],
            "porosity",
            crs="",
        ),
        _case(
            "invalid_coord_string",
            [{"well_id": "W", "x": "not-a-number", "y": 1.0, "porosity": 10.0}],
            "porosity",
        ),
        _case(
            "empty_records",
            [],
            "porosity",
        ),
        _case(
            "top_level_val",
            [{"id": 1, "well": "N", "coordinates": [0.0, 0.0], "val": 12.5}],
            "porosity",
        ),
        _case(
            "well_id_name_fallbacks",
            [
                {"id": "ID1", "name": "N1", "x": 1.0, "y": 2.0, "porosity": 10.0},
                {
                    "well_id": "W2",
                    "well_name": "WN2",
                    "x": 3.0,
                    "y": 4.0,
                    "porosity": 11.0,
                    "qc_flag": "good",
                },
                {
                    "well_id": "W3",
                    "well": "WELL3",
                    "x": 5.0,
                    "y": 6.0,
                    "porosity": 12.0,
                    "formation": "Es3",
                },
            ],
            "porosity",
            target_horizon="T1",
        ),
        _case(
            "longitude_latitude",
            [{"well": "EN-01", "longitude": 100.0, "latitude": 200.0, "porosity": 14.0}],
            "porosity",
        ),
    ]

    doc = {"cases": cases}
    target = OUT / "extract_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, {len(cases)} cases)")


if __name__ == "__main__":
    main()
