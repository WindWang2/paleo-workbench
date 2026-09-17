#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-17 geometry_units + crs_contract
C++ leaves (task 17).

Imports the REAL implementations
(paleo_workbench.mapping.geological_pipeline.geometry_units,
 paleo_workbench.mapping.crs_contract)
and freezes their outputs to JSON so the C++ port in libs/mapping_kernel
can be verified value-exactly.

Two sections, same inputs:

* ``kernel`` — generated with pyproj import BLOCKED (a meta_path hook
  raises ImportError before pyproj is ever imported). ``from pyproj
  import ...`` inside the leaves fails for real, exactly the dependency
  profile of the Qt-free/pyproj-free C++ kernel. The C++ test compares
  these values. (A ``sys.modules["pyproj"] = None`` sentinel is NOT
  usable: it leaves a partially-initialized module entry behind and the
  restore pass then fails — measured.)
* ``pyproj_env`` — generated with pyproj importable. Recorded for
  humans/future wiring only; the C++ test does NOT compare these rows
  (same idea as the crs_policy oracle's ``pyproj_optional`` bucket).

Regenerate (cwd MUST be the worktree root so ``''`` on sys.path does not
shadow this checkout; interpreter needs numpy+PySide6 because
``paleo_workbench.mapping.__init__`` pulls map_render_backend):

    /home/kevin/project/oracle-venvs/conv12/bin/python3 \
        tools/oracle/generate_crs_units_fixtures.py

Case inputs are transcribed from the pytest contracts:
tests/test_geometry_units_qa.py, test_v9_interaction_facts.py (W3),
test_v9_review_fixes.py (R1-P1-1), test_topo_m0_foundation.py (§6),
plus branch-coverage rows the suites do not pin (marked inline).
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


# ---------------------------------------------------------------------------
# case inputs (id, crs) — CRS-relevant strings only; None = Python None
# ---------------------------------------------------------------------------

GEO_CASES = [
    ("null", None),
    ("empty", ""),
    ("ws_only", "   "),
    ("4326", "EPSG:4326"),
    ("4326_lower", "epsg:4326"),
    ("4326_mixed", "Epsg:4326"),
    ("4326_padded", "  EPSG:4326  "),
    ("4326_slash", "EPSG:4326 / WGS 84"),
    ("4326_slash_ns", "EPSG:4326/WGS84"),
    ("4490", "EPSG:4490"),
    ("4214", "EPSG:4214"),
    ("4269", "EPSG:4269"),
    ("4267", "EPSG:4267"),
    ("4610", "EPSG:4610"),
    ("3857", "EPSG:3857"),
    ("3857_slash", "EPSG:3857 / Pseudo-Mercator"),
    ("3857_padded", "  EPSG:3857  "),
    ("32650", "EPSG:32650"),
    ("99999", "EPSG:99999"),
    ("99999_padded", "  EPSG:99999  "),
    ("wgs84", "WGS84"),
    ("wgs84_utm", "WGS 84 / UTM zone 48N"),  # R3-P1 regression
    ("proj4_utm", "+proj=utm +zone=48 +datum=WGS84"),  # R3-P1 regression
]

LABEL_CASES = GEO_CASES  # area_unit_label over the same declaration set

# (id, crs, ring) — rings are CLOSED unless the id says open (Python
# convention pinned by the closed-vs-open square pair, qa suite + branch)
RING_CASES = [
    ("unit_projected", "EPSG:32650",
     [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]),
    ("equator_001", "EPSG:4326",
     [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]),
    ("lat60_001", "EPSG:4326",
     [[0.0, 60.0], [0.01, 60.0], [0.01, 60.01], [0.0, 60.01], [0.0, 60.0]]),
    ("latneg60_001", "EPSG:4326",
     [[0.0, -60.0], [0.01, -60.0], [0.01, -60.01], [0.0, -60.01], [0.0, -60.0]]),
    ("small_unknown_id", "EPSG:99999",
     [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]),
    ("small_empty_crs", "",
     [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]),
    ("small_null_crs", None,
     [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]),
    ("small_ws_crs", "   ",
     [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]),
    ("padded_projected", "  EPSG:3857  ",
     [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]),
    ("descriptive_4326", "EPSG:4326 / WGS 84",
     [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]),
    ("empty_ring_geo", "EPSG:4326", []),
    ("empty_ring_null_crs", None, []),
    ("two_point_geo", "EPSG:4326", [[0.0, 0.0], [3.0, 4.0]]),
    ("open_square_geo", "EPSG:4326",
     [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01]]),  # unclosed!
    ("triangle_projected", "EPSG:3857",
     [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]),
    ("padded_unknown_id", "  EPSG:99999  ",
     [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]),
]

# (id, crs, vertices)
LENGTH_CASES = [
    ("proj_2pt", "EPSG:32650", [[0.0, 0.0], [30.0, 40.0]]),
    ("geo_001", "EPSG:4326", [[0.0, 0.0], [0.01, 0.0]]),
    ("geo_multiseg", "EPSG:4326",
     [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01]]),
    ("geo_lat60", "EPSG:4326", [[0.0, 60.0], [0.01, 60.0]]),
    ("geo_descriptive", "EPSG:4326 / WGS 84", [[0.0, 0.0], [0.01, 0.0]]),
    ("undeclared_empty", "", [[0.0, 0.0], [3.0, 4.0]]),
    ("undeclared_null", None, [[0.0, 0.0], [3.0, 4.0]]),
    ("undeclared_ws", "   ", [[0.0, 0.0], [3.0, 4.0]]),
    ("padded_projected", "  EPSG:32650 ", [[0.0, 0.0], [30.0, 40.0]]),
    ("empty_geo", "EPSG:4326", []),
    ("single_point_geo", "EPSG:4326", [[5.0, 5.0]]),
    ("unknown_id", "EPSG:99999", [[0.0, 0.0], [3.0, 4.0]]),
]

NORMALIZE_CASES = [
    ("null", None),
    ("empty", ""),
    ("ws_only", "   "),
    ("ws_tab_nl", "\t epsg:4326 \n"),
    ("4326", "EPSG:4326"),
    ("4326_lower", "epsg:4326"),
    ("4326_mixed", "Epsg:4326"),
    ("4326_padded", "  EPSG:4326  "),
    ("4326_slash", "EPSG:4326 / WGS 84"),
    ("4326_slash_ns", "EPSG:4326/WGS84"),
    ("4326_dot", "EPSG:4326."),  # \b at '.' → match
    ("4326_letter", "EPSG:4326x"),  # no boundary → unchanged
    ("4326_underscore", "EPSG:4326_X"),  # '_' is \w → unchanged
    ("4326_leading_zeros", "EPSG:0123"),
    ("epsg_no_digits", "EPSG:"),
    ("digits_only", "4326"),
    ("wgs84", "WGS84"),
    ("prefix_not_at_start", "xxxEPSG:4326"),
    ("proj4", "+proj=utm +zone=48 +datum=WGS84"),
    ("local", "LOCAL"),
]

# (id, value, purpose, fallback)
RESOLVE_CASES = [
    ("declared_4326", "EPSG:4326", "测试", ""),
    ("declared_padded", "  EPSG:4326  ", "测试", ""),
    ("declared_descriptive", "EPSG:4326 / WGS84", "测试", ""),
    ("declared_unknown_id", "EPSG:99999", "测试", ""),  # declared, unverified
    ("declared_lower_4490", "epsg:4490", "测试", ""),
    ("empty_no_fallback", "", "测试", ""),
    ("null_no_fallback", None, "测试", ""),
    ("ws_no_fallback", "   ", "测试", ""),
    ("fallback_4326", "", "测试", "EPSG:4326"),
    ("fallback_padded_descriptive", "", "测试", " epsg:4326 / WGS 84 "),
    ("fallback_null", None, "测试", None),
    ("fallback_also_empty", "", "测试", ""),
    ("ws_value_fallback", "   ", "服务边界", "EPSG:4326"),
    ("empty_chinese_purpose", "", "图层导入", ""),
]

PANEL_CASES = [
    ("declared", "EPSG:4326", "图层面板发布"),
    ("empty", "", "图层面板发布"),
    ("null", None, "图层面板发布"),
    ("descriptive", "EPSG:4326 / WGS 84", "图层面板发布"),
    ("unknown_id", "EPSG:99999", "图层面板发布"),
    ("explicit_purpose", "", "首页面板发布"),
]

AXIS_METRES_CASES = [
    ("null", None),
    ("empty", ""),
    ("ws_only", "   "),
    ("4326", "EPSG:4326"),
    ("3857", "EPSG:3857"),
    ("32650", "EPSG:32650"),
    ("99999", "EPSG:99999"),
    ("wgs84", "WGS84"),
]

# (id, map_units_per_pixel, pixels_per_inch, crs)
SCALE_CASES = [
    ("metric_32650", 10.0, 96.0, "EPSG:32650"),
    ("degrees_4326", 10.0, 96.0, "EPSG:4326"),
    ("empty_crs", 10.0, 96.0, ""),
    ("null_crs", 10.0, 96.0, None),
    ("zero_mupp", 0.0, 96.0, "EPSG:32650"),
    ("neg_mupp", -1.0, 96.0, "EPSG:32650"),
    ("zero_ppi", 10.0, 0.0, "EPSG:32650"),
    ("neg_ppi", 10.0, -5.0, "EPSG:32650"),
    ("fractional", 2.5, 120.0, "EPSG:32650"),
]

DOMAIN_CASES = [
    ("null", None),
    ("empty", ""),
    ("ws_only", "   "),
    ("4326", "EPSG:4326"),
    ("4326_slash", "EPSG:4326 / WGS84"),
    ("4490_lower", "epsg:4490"),
    ("3857", "EPSG:3857"),
    ("32650", "EPSG:32650"),
    ("99999", "EPSG:99999"),
    ("wgs84", "WGS84"),
]

# (id, crs, extent-or-None)
MISMATCH_CASES = [
    ("local_under_4326", "EPSG:4326", (0.0, 0.0, 16000.0, 8000.0)),
    ("inside_4326", "EPSG:4326", (100.0, 20.0, 120.0, 40.0)),
    ("null_extent", "EPSG:4326", None),
    ("undeclared_crs", "", (0.0, 0.0, 16000.0, 8000.0)),
    ("projected_out", "EPSG:32650", (0.0, 0.0, 100.0, 100.0)),
    ("projected_inside", "EPSG:32650",
     (500000.0, 4400000.0, 510000.0, 4410000.0)),
    ("unknown_id", "EPSG:99999", (0.0, 0.0, 100.0, 100.0)),
    ("west_out", "EPSG:4326", (-181.0, 0.0, 0.0, 0.0)),
    ("lat_out", "EPSG:4326", (0.0, 90.5, 10.0, 91.0)),
    ("eps_absorbed", "EPSG:4326",
     (-180.0000001, -90.0000001, 180.0, 90.0)),
    ("beyond_eps", "EPSG:4326", (-180.001, -90.0, 180.0, 90.0)),
    ("boundary_exact", "EPSG:4326", (-180.0, -90.0, 180.0, 90.0)),
    ("inverted_extent", "EPSG:4326", (16000.0, 8000.0, 0.0, 0.0)),
    ("descriptive_crs", "EPSG:4326 / WGS84", (0.0, 0.0, 16000.0, 8000.0)),
    ("null_crs", None, (0.0, 0.0, 10.0, 10.0)),
    ("ws_crs", "   ", (0.0, 0.0, 10.0, 10.0)),
]

# (id, extent-or-None)
INFERENCE_CASES = [
    ("null_extent", None),
    ("local_data", (0.0, 0.0, 16000.0, 8000.0)),
    ("geographic_data", (100.0, 20.0, 120.0, 40.0)),
    ("inverted_extent", (16000.0, 8000.0, 0.0, 0.0)),
    ("boundary_exact", (-180.0, -90.0, 180.0, 90.0)),
    ("lat_out", (0.0, 90.5, 10.0, 91.0)),
    ("small_local_inside_domain", (0.0, 0.0, 200.0, 100.0)),
]


# ---------------------------------------------------------------------------
# collection (one pass per pyproj mode)
# ---------------------------------------------------------------------------

def _collect() -> dict:
    from paleo_workbench.mapping.crs_contract import (
        CRSInference,
        coordinate_domain_mismatch,
        crs_axis_unit_metres,
        crs_coordinate_domain,
        crs_is_geographic,
        infer_crs_from_extent,
        normalize_crs,
        panel_publish_crs,
        resolve_crs,
        scale_denominator_from_pixels,
    )
    from paleo_workbench.mapping.geological_pipeline.geometry_units import (
        _METRES_PER_DEGREE_LAT,
        area_unit_label,
        is_geographic_crs,
        polyline_length_with_unit,
        ring_area_with_unit,
    )
    import paleo_workbench.mapping.crs_contract as cc_mod

    section: dict = {}

    section["geometry_units"] = {
        "constants": {"METRES_PER_DEGREE_LAT": _METRES_PER_DEGREE_LAT},
        "is_geographic_crs": [
            {"id": cid, "crs": crs, "result": is_geographic_crs(crs)}
            for cid, crs in GEO_CASES
        ],
        "area_unit_label": [
            {"id": cid, "crs": crs, "result": area_unit_label(crs)}
            for cid, crs in LABEL_CASES
        ],
        "ring_area_with_unit": [
            dict(
                zip(
                    ("id", "crs", "ring", "area", "unit_label", "warning"),
                    (cid, crs, ring, *ring_area_with_unit(ring, crs)),
                )
            )
            for cid, crs, ring in RING_CASES
        ],
        "polyline_length_with_unit": [
            dict(
                zip(
                    ("id", "crs", "vertices", "length", "unit_label", "warning"),
                    (cid, crs, pts, *polyline_length_with_unit(pts, crs)),
                )
            )
            for cid, crs, pts in LENGTH_CASES
        ],
    }

    section["crs_contract"] = {
        "constants": {
            "GEOGRAPHIC_DEGREE_DOMAIN": list(cc_mod._GEOGRAPHIC_DEGREE_DOMAIN),
            "DOMAIN_EPSILON": cc_mod._DOMAIN_EPSILON,
            "PROJECTED_DOMAIN_SLACK": cc_mod._PROJECTED_DOMAIN_SLACK,
        },
        "normalize_crs": [
            {"id": cid, "crs": crs, "result": normalize_crs(crs)}
            for cid, crs in NORMALIZE_CASES
        ],
        "crs_is_geographic": [
            {"id": cid, "crs": crs, "result": crs_is_geographic(crs)}
            for cid, crs in GEO_CASES
        ],
        "resolve_crs": [
            _resolve_row(cid, value, purpose, fallback, resolve_crs)
            for cid, value, purpose, fallback in RESOLVE_CASES
        ],
        "panel_publish_crs": [
            {
                "id": cid,
                "value": value,
                "purpose": purpose,
                "result": panel_publish_crs(value, purpose=purpose),
            }
            for cid, value, purpose in PANEL_CASES
        ],
        "crs_axis_unit_metres": [
            {"id": cid, "crs": crs, "result": crs_axis_unit_metres(crs)}
            for cid, crs in AXIS_METRES_CASES
        ],
        "scale_denominator_from_pixels": [
            {
                "id": cid,
                "mupp": mupp,
                "ppi": ppi,
                "crs": crs,
                "result": scale_denominator_from_pixels(mupp, ppi, crs),
            }
            for cid, mupp, ppi, crs in SCALE_CASES
        ],
        "crs_coordinate_domain": [
            {
                "id": cid,
                "crs": crs,
                "result": _opt_domain(crs_coordinate_domain(crs)),
            }
            for cid, crs in DOMAIN_CASES
        ],
        "coordinate_domain_mismatch": [
            _mismatch_row(cid, crs, extent, coordinate_domain_mismatch)
            for cid, crs, extent in MISMATCH_CASES
        ],
        "infer_crs_from_extent": [
            _inference_row(cid, extent, infer_crs_from_extent, CRSInference)
            for cid, extent in INFERENCE_CASES
        ],
    }
    return section


def _resolve_row(cid, value, purpose, fallback, resolve_crs):
    row = {"id": cid, "value": value, "purpose": purpose, "fallback": fallback}
    resolution = resolve_crs(value, purpose=purpose, fallback=fallback)
    row["crs"] = resolution.crs
    row["declared"] = resolution.declared
    row["degraded_reason"] = resolution.degraded_reason
    row["ok"] = resolution.ok
    return row


def _opt_domain(domain):
    return None if domain is None else list(domain)


def _mismatch_row(cid, crs, extent, coordinate_domain_mismatch):
    row = {"id": cid, "crs": crs, "extent": None if extent is None else list(extent)}
    mismatch = coordinate_domain_mismatch(crs, extent)
    if mismatch is None:
        row["result"] = None
    else:
        row["result"] = {
            "crs": mismatch.crs,
            "extent": list(mismatch.extent),
            "domain": list(mismatch.domain),
            "describe": mismatch.describe(),
        }
    return row


def _inference_row(cid, extent, infer_crs_from_extent, crs_inference):
    row = {"id": cid, "extent": None if extent is None else list(extent)}
    inference = infer_crs_from_extent(extent)
    assert isinstance(inference, crs_inference)
    row["suggested_crs"] = inference.suggested_crs
    row["basis"] = inference.basis
    return row


def _clear_caches() -> None:
    from paleo_workbench.mapping import crs_contract as cc_mod
    from paleo_workbench.workflow import crs_policy as cp_mod

    cp_mod.crs_is_geographic.cache_clear()
    cc_mod._axis_unit_metres_cached.cache_clear()


class _PyprojBlocker:
    """Import hook: pyproj resolves to ImportError while installed."""

    def find_spec(self, name, path=None, target=None):
        if name == "pyproj" or name.startswith("pyproj."):
            raise ImportError("pyproj blocked for the oracle kernel section")
        return None


def main() -> None:
    # Pass 1 — kernel: block pyproj so the leaves' `from pyproj import ...`
    # raises ImportError for real (the C++ kernel's dependency profile).
    blocker = _PyprojBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        _clear_caches()
        kernel = _collect()
    finally:
        sys.meta_path.remove(blocker)

    # Pass 2 — pyproj_env: importable again; first lazy use imports it for
    # real (caches cleared so no blocked-pass verdict survives).
    _clear_caches()
    pyproj_env = _collect()

    try:
        import pyproj  # noqa: F401

        pyproj_version = getattr(pyproj, "__version__", None)
    except Exception:
        pyproj_version = None

    doc = {
        "generator": "tools/oracle/generate_crs_units_fixtures.py",
        "python": platform.python_version(),
        "pyproj_version": pyproj_version,
        "kernel": {"pyproj_blocked": True, **kernel},
        "pyproj_env": {"pyproj_blocked": False, **pyproj_env},
    }

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "crs_units_oracle.json"
    target.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    def count(section: dict) -> int:
        total = 0
        for module in ("geometry_units", "crs_contract"):
            for name, rows in section[module].items():
                if name == "constants":
                    continue
                total += len(rows)
        return total

    print(
        f"wrote {target} ({target.stat().st_size} bytes; "
        f"kernel cases={count(kernel)}, "
        f"pyproj_env cases={count(pyproj_env)}, "
        f"pyproj={pyproj_version!r})"
    )


if __name__ == "__main__":
    main()
