#!/usr/bin/env python3
"""Oracle for the VIZ-E dat preview parser (viz_e_dat_preview) — freezes
the REAL geoviz previews/dat.py well-head/horizon payload behavior for the
C++ replay test in tests/cpp/viz_e.

The two fixture files under tests/cpp/viz_e/fixtures are parsed by the real
Python backend helpers; the frozen fields are the observable surface the
C++ port reproduces (records, totals, diagnostics counts, declared
CRS/unit, horizon axis decisions). A negative self-check perturbs one
numeric leaf and requires the digest to change.

Run with the geoviz venv:

    <repo>/../main/geo-viz-engine/.venv/bin/python \
        tools/oracle/generate_viz_e_dat_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = [
    REPO_ROOT.parent.parent / "main" / "geo-viz-engine",
    REPO_ROOT.parent / "geo-viz-engine",
    REPO_ROOT / "geo-viz-engine",
]
GEO_ENGINE = next(
    (c for c in CANDIDATES if (c / "geoviz" / "previews" / "dat.py").is_file()),
    None,
)
if GEO_ENGINE is None:
    raise SystemExit("geo-viz-engine not found for the dat preview oracle")
sys.path.insert(0, str(GEO_ENGINE))

OUT = REPO_ROOT / "tests" / "cpp" / "viz_e" / "fixtures" / "viz_e_dat_oracle.json"
FIXTURES = REPO_ROOT / "tests" / "cpp" / "viz_e" / "fixtures"
GEOVIZ_GITLINK = "08851951f3bbc0beb90886adf52e1928f4383c16"


def freeze() -> dict:
    import geoviz.previews.dat as dat

    provenance_sha = subprocess.check_output(
        ["git", "-C", str(GEO_ENGINE), "rev-parse", "HEAD"], text=True
    ).strip()
    if provenance_sha != GEOVIZ_GITLINK:
        raise SystemExit(
            f"provenance mismatch: {GEO_ENGINE} @ {provenance_sha}, "
            f"expected {GEOVIZ_GITLINK} — refusing to freeze"
        )

    out: dict = {
        "geoviz_sha": provenance_sha,
        "well_head": None,
        "well_head_bad": None,
        "horizon": None,
    }

    from geoviz.contracts import PreviewOptions, PreviewRequest

    options = PreviewOptions()

    def request_for(path: Path, semantic: str) -> PreviewRequest:
        return PreviewRequest(
            resource_id="oracle",
            path=str(path),
            format="dat",
            semantic_type=semantic,
            options=options,
        )

    # Well head: payload fields the C++ port reproduces.
    payload = dat._well_head_payload(str(FIXTURES / "well_head_smi.dat"), options)
    out["well_head"] = {
        "records": [
            [str(n), float(x), float(y), str(u)]
            for n, x, y, u in zip(
                payload.names,
                payload.x,
                payload.y,
                payload.uwis or [""] * len(payload.names),
            )
        ],
        "total_records": payload.diagnostics.total_records,
        "valid_records": payload.diagnostics.valid_records,
        "skipped": payload.diagnostics.skipped_count,
        "source_crs": payload.source_crs,
        "coordinate_units": payload.coordinate_units,
    }

    # Malformed well head (missing Y column) — the error message shape.
    bad = FIXTURES / "well_head_missing_y.tmp.dat"
    bad.write_text(
        "#WellHead File From SMI\n#Name X\nA1 10\n", encoding="utf-8-sig"
    )
    try:
        dat._well_head_payload(str(bad), options)
        out["well_head_bad"] = {"error": ""}
    except Exception as error:  # GeoVizError / _DatSchemaError
        out["well_head_bad"] = {"error": str(error)}
    finally:
        bad.unlink()

    # Horizon: the observable pieces of _surface_payload's XYZ path — the
    # sampled points, axis ranges and grid cadence the C++ port mirrors
    # through parse_horizon_points + horizon_grid_resolution.
    horizon = dat._surface_payload(
        str(FIXTURES / "horizon_smi.dat"), options
    )
    out["horizon"] = {
        "grid_x": [float(v) for v in horizon.grid_x],
        "grid_y": [float(v) for v in horizon.grid_y],
        "grid_shape": [int(horizon.grid_z.shape[0]), int(horizon.grid_z.shape[1])],
        "levels": [float(v) for v in horizon.levels],
        "finite_cells": int(
            sum(1 for v in horizon.grid_z.ravel() if math.isfinite(float(v)))
        ),
    }

    # Raw row view (what parse_horizon_points returns before gridding).
    rows = list(dat._iter_data_lines_with_source(str(FIXTURES / "horizon_smi.dat")))
    out["horizon_rows"] = [[tokens, source_row] for tokens, source_row in rows]
    return out


def negative_self_check(fixture: dict) -> None:
    digest = lambda d: hashlib.sha256(  # noqa: E731
        json.dumps(d, sort_keys=True).encode()
    ).hexdigest()
    base = digest(fixture)
    tampered = json.loads(json.dumps(fixture))
    tampered["well_head"]["records"][0][1] += 25.0
    if digest(tampered) == base:
        raise SystemExit("negative self-check failed: tamper undetected")
    print("negative self-check: OK")


def main() -> None:
    fixture = freeze()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
    negative_self_check(json.loads(json.dumps(fixture)))
    print(f"geoviz source: {GEO_ENGINE} @ {GEOVIZ_GITLINK}")


if __name__ == "__main__":
    main()
