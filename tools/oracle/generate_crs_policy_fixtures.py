#!/usr/bin/env python3
"""Oracle fixture generator for the C++ crs_policy kernel (M7 first slice).

Imports the REAL implementation (paleo_workbench.workflow.crs_policy) and
freezes its outputs to JSON so the C++ port in libs/mapping_kernel can be
verified sample-exactly. Regenerate with:

    python3 tools/oracle/generate_crs_policy_fixtures.py

Split:
  * ``builtin`` — ids decided by the module's own table (or empty/None)
    before pyproj is consulted. C++ must match these bit-for-bit.
  * ``pyproj_optional`` — unknown ids. Python may call pyproj and return
    True/False; C++ has no pyproj and returns nullopt. The C++ test skips
    Python-value comparison and only asserts unknown → nullopt.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.workflow import crs_policy as py  # noqa: E402
from paleo_workbench.workflow.crs_policy import (  # noqa: E402
    DISTANCE_POLICIES,
    POLICY_PLANAR,
    POLICY_PLANAR_DEGREES,
    POLICY_PROJECTED,
    POLICY_UNDECLARED,
    crs_is_geographic,
    resolve_distance_policy,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)

logging.getLogger("paleo_workbench.workflow.crs_policy").setLevel(logging.ERROR)


def _pyproj_info() -> tuple[bool, str | None]:
    try:
        import pyproj  # noqa: F401

        return True, getattr(pyproj, "__version__", None)
    except Exception:
        return False, None


def _is_builtin_crs(crs: str | None) -> bool:
    """True when Python never consults pyproj for this crs string."""
    if not crs:
        return True
    token = crs.split("/")[0].strip().upper()
    return token in py._KNOWN_GEOGRAPHIC or token in py._PROJECTED_EXCEPTIONS


def _dump_geo(cid: str, crs: str | None) -> dict:
    return {
        "id": cid,
        "crs": crs,
        "result": crs_is_geographic(crs),
    }


def _dump_resolve(cid: str, crs: str | None, distance_policy: str | None) -> dict:
    rec: dict = {
        "id": cid,
        "crs": crs,
        "distance_policy": distance_policy,
    }
    try:
        rec["result"] = resolve_distance_policy(crs, distance_policy)
    except ValueError as exc:
        rec["error"] = str(exc)
    return rec


def main() -> None:
    pyproj_available, pyproj_version = _pyproj_info()

    geo_inputs: list[tuple[str, str | None]] = [
        ("null", None),
        ("empty", ""),
        ("4326", "EPSG:4326"),
        ("4269", "EPSG:4269"),
        ("4267", "EPSG:4267"),
        ("4214", "EPSG:4214"),
        ("4610", "EPSG:4610"),
        ("4490", "EPSG:4490"),
        ("3857", "EPSG:3857"),
        ("4326_lower", "epsg:4326"),
        ("4326_padded", "  EPSG:4326  "),
        ("4326_slash", "EPSG:4326 / WGS 84"),
        ("3857_slash", "EPSG:3857 / Pseudo-Mercator"),
        ("unknown_99999", "EPSG:99999"),
        ("unknown_99999999", "EPSG:99999999"),
        ("utm_32650", "EPSG:32650"),
        ("whitespace_only", "  "),
    ]

    resolve_inputs: list[tuple[str, str | None, str | None]] = [
        ("undeclared_default", None, None),
        ("undeclared_planar", None, "planar"),
        ("undeclared_planar_degrees", None, "planar_degrees"),
        ("undeclared_projected", None, "projected"),
        ("empty_default", "", None),
        ("empty_planar_degrees", "", "planar_degrees"),
        ("empty_projected", "", "projected"),
        ("4326_default", "EPSG:4326", None),
        ("4326_empty_policy", "EPSG:4326", ""),
        ("4326_ws_policy", "EPSG:4326", "   "),
        ("4326_explicit_planar", "EPSG:4326", "planar"),
        ("4326_planar_degrees", "EPSG:4326", "planar_degrees"),
        ("4326_projected", "EPSG:4326", "projected"),
        ("4326_padded_policy", "EPSG:4326", "  planar_degrees  "),
        ("4326_padded_crs", "  EPSG:4326  ", None),
        ("4326_slash", "EPSG:4326 / WGS 84", None),
        ("4490_default", "EPSG:4490", None),
        ("4490_planar_degrees", "EPSG:4490", "planar_degrees"),
        ("3857_default", "EPSG:3857", None),
        ("3857_planar", "EPSG:3857", "planar"),
        ("3857_planar_degrees", "EPSG:3857", "planar_degrees"),
        ("3857_projected", "EPSG:3857", "projected"),
        ("unknown_99999_default", "EPSG:99999", None),
        ("unknown_99999_planar_degrees", "EPSG:99999", "planar_degrees"),
        ("unknown_99999_projected", "EPSG:99999", "projected"),
        ("utm_32650_default", "EPSG:32650", None),
        ("utm_32650_planar_degrees", "EPSG:32650", "planar_degrees"),
        ("utm_32650_projected", "EPSG:32650", "projected"),
        ("err_4326_lightyears", "EPSG:4326", "planar_lightyears"),
        ("err_null_geodesic", None, "geodesic"),
        ("err_4326_PLANAR", "EPSG:4326", "PLANAR"),
        ("err_4326_not_a_policy", "EPSG:4326", "not-a-policy"),
    ]

    builtin_geo: list[dict] = []
    optional_geo: list[dict] = []
    for cid, crs in geo_inputs:
        rec = _dump_geo(cid, crs)
        if _is_builtin_crs(crs):
            builtin_geo.append(rec)
        else:
            optional_geo.append(rec)

    builtin_resolve: list[dict] = []
    builtin_errors: list[dict] = []
    optional_resolve: list[dict] = []
    for cid, crs, policy in resolve_inputs:
        rec = _dump_resolve(cid, crs, policy)
        bucket_builtin = _is_builtin_crs(crs)
        if "error" in rec:
            # Invalid policy is raised before axis-dependent branches; the
            # message is pyproj-independent even for unknown ids.
            if bucket_builtin:
                builtin_errors.append(rec)
            else:
                optional_resolve.append(rec)
        elif bucket_builtin:
            builtin_resolve.append(rec)
        else:
            optional_resolve.append(rec)

    doc = {
        "constants": {
            "POLICY_PLANAR": POLICY_PLANAR,
            "POLICY_PLANAR_DEGREES": POLICY_PLANAR_DEGREES,
            "POLICY_PROJECTED": POLICY_PROJECTED,
            "POLICY_UNDECLARED": POLICY_UNDECLARED,
            "DISTANCE_POLICIES": list(DISTANCE_POLICIES),
            "KNOWN_GEOGRAPHIC": sorted(py._KNOWN_GEOGRAPHIC),
            "PROJECTED_EXCEPTIONS": sorted(py._PROJECTED_EXCEPTIONS),
        },
        "pyproj_available": pyproj_available,
        "pyproj_version": pyproj_version,
        "builtin": {
            "crs_is_geographic": builtin_geo,
            "resolve": builtin_resolve,
            "errors": builtin_errors,
        },
        "pyproj_optional": {
            "crs_is_geographic": optional_geo,
            "resolve": optional_resolve,
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "crs_policy_oracle.json"
    target.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {target} ({target.stat().st_size} bytes, "
        f"builtin geo={len(builtin_geo)} resolve={len(builtin_resolve)} "
        f"errors={len(builtin_errors)}; "
        f"pyproj_optional geo={len(optional_geo)} "
        f"resolve={len(optional_resolve)}; "
        f"pyproj={pyproj_available})"
    )


if __name__ == "__main__":
    main()
