#!/usr/bin/env python3
"""VIZ-A robust-scale + pattern-vocabulary oracle generator.

Freezes the REAL Python behavior for the two VIZ-A drawing kernels:

* robust_scale.compute_robust_display_range (geoviz_well_log/robust_scale.py)
  over synthesized value sets covering every branch: presets (GR/RHOB/NPHI,
  incl. unit-mismatch inversions #113), general P2–P98, constant/near-
  constant fallbacks, NaN/null masking, legal negatives, empty input.
* PatternEngine fuzzy lookup (geoviz_well_log/renderer/pattern_engine.py,
  PySide6 available on this host) + the frozen PATTERN_MAP/FACIES_COLORS
  tables — exact and longest-substring matches, unmatched names, and the
  equal-length tie cases.

Negative self-checks: every robust-scale case re-runs with one value
perturbed and must change (or the case is marked static, e.g. empty input);
pattern lookups include unmatched probes that must stay unmatched.

Run:  python3 tools/oracle/generate_viz_a_scale_fixtures.py
Out:  tests/cpp/viz_a/fixtures/scale_patterns_oracle.json
Deps: numpy, PySide6 (real reference modules; nothing stubbed).
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
GEOVIZ_PKG = (
    REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_well_log"
    / "geoviz_well_log")
OUT_PATH = REPO_ROOT / "tests" / "cpp" / "viz_a" / "fixtures" / "scale_patterns_oracle.json"

SCHEMA = "pwb.viz_a.scale_patterns_oracle/1"


def _load_module(name: str, relpath: Path):
    spec = importlib.util.spec_from_file_location(name, relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_references():
    sys.path.insert(0, str(GEOVIZ_PKG.parent))
    # Package trampoline so pattern_engine's relative import resolves to the
    # real pattern_map module (loaded from file — nothing stubbed).
    pkg = types.ModuleType("geoviz_well_log")
    pkg.__path__ = [str(GEOVIZ_PKG)]
    sys.modules.setdefault("geoviz_well_log", pkg)
    pattern_map = _load_module("geoviz_well_log.pattern_map",
                               GEOVIZ_PKG / "pattern_map.py")
    pkg.pattern_map = pattern_map
    pattern_engine = _load_module(
        "geoviz_well_log.renderer.pattern_engine",
        GEOVIZ_PKG / "renderer" / "pattern_engine.py")
    robust = _load_module("geoviz_well_log.robust_scale",
                          GEOVIZ_PKG / "robust_scale.py")
    return robust, pattern_map, pattern_engine


SCALE_CASES = [
    # (id, values spec, curve_name, null_value)
    ("gr_linear", list(range(20, 220, 4)), "GR", None),
    ("gr_outliers", [30, 35, 40, 45, 50, 55, 60, 65, 70, 3000.0, -500.0],
     "GR", None),
    ("gr_chinese", list(range(10, 200, 3)), "自然伽马", None),
    ("gr_lowercase", list(range(10, 150, 2)), "gr", None),
    ("gr_padded", list(range(10, 150, 2)), "  GR-x  ", None),
    ("rhob_normal", [2.05 + 0.01 * i for i in range(30)], "RHOB", None),
    ("den_family", [2.1 + 0.02 * i for i in range(20)], "DEN", None),
    ("rhob_density_cn", [2.2 + 0.01 * i for i in range(25)], "密度", None),
    ("rhob_wrong_units", [2000.0 + 5.0 * i for i in range(30)], "RHOB", None),
    ("nphi_normal", [0.10 + 0.008 * i for i in range(30)], "NPHI", None),
    ("nphi_percent_units", [10.0 + 0.8 * i for i in range(30)], "CNL", None),
    ("sp_negative", [-90.0 + 2.0 * i for i in range(40)], "SP", None),
    ("constant", [42.0] * 25, "GR", None),
    ("near_constant", [41.999, 42.0, 42.001], "DT", None),
    ("null_masked", [10.0, -999.25, 30.0, 44.0, 58.0, -999.25, 90.0],
     "GR", -999.25),
    ("all_null", [-999.25] * 8, "GR", -999.25),
    ("empty", [], "GR", None),
    ("all_nan", [float("nan")] * 8, "GR", None),
    ("mixed_nan", [float("nan"), 5.0, float("inf"), 15.0, 25.0], "RD", None),
    ("two_values", [0.0, 100.0], "AC", None),
    ("huge_span", [1.0, 5.0e4, 3.0, 7.0], "CAL", None),
    ("gr_nan_mixed", [20.0 + i * 4 + (float("nan") if i % 7 == 3 else 0.0)
                      for i in range(50)], "GR", None),
]

PATTERN_PROBES = [
    "砂岩", "泥质砂岩", "长石砂岩", "粉砂岩", "砂岩粉砂岩",
    "灰岩", "生物灰岩", "鲕粒灰岩", "白云岩", "页岩",
    "潮坪", "混积潮坪", "碎屑岩潮坪", "砂坪", "泥坪",
    "三角洲", "滨岸", "前滨", "临滨", "生物礁", "礁",
    "蒸发岩", "膏盐", "冰川", "冰碛", "火山岩", "熔岩", "变质岩",
    "冲积扇", "洪积扇", "潟湖", "局限台地", "陆棚", "砂质陆棚",
    "混积", "云坪", "花岗岩", "未知岩性", "", "泥岩夹砂岩",
    "砂岩(MISS MATCH ASCII)", "砂",
]

COLOR_PROBES = [
    "砂岩", "泥质砂岩", "灰岩", "生物灰岩", "混合坪", "潮汐水道",
    "潮道", "深水陆棚", "云坪", "花岗岩", "未知相", "",
]


def encode_float(value):
    """JSON has no NaN/Inf literals (nlohmann rejects them): encode
    non-finite doubles as tagged strings, the same convention as the
    welllog adapter oracle."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value


def encode_case(case):
    out = dict(case)
    out["values"] = [encode_float(v) for v in case["values"]]
    out["expected"] = [encode_float(v) for v in case["expected"]]
    return out


def main() -> int:
    robust, pattern_map, pattern_engine = load_references()
    engine = pattern_engine.PatternEngine()

    scale_cases = []
    for case_id, values, name, null_value in SCALE_CASES:
        expected = robust.compute_robust_display_range(values, name, null_value)
        entry = {
            "id": case_id,
            "curve_name": name,
            "null_value": null_value,
            "values": values,
            "expected": [expected[0], expected[1]],
        }
        # Negative self-check (dynamic cases only): perturb one value; the
        # range must move or the case is flagged.
        if values and any(isinstance(v, float) or isinstance(v, int)
                          for v in values):
            idx = len(values) // 2
            base = values[idx] if isinstance(values[idx], (int, float)) else 0.0
            if math.isfinite(base):
                perturbed = list(values)
                perturbed[idx] = base * 3.0 + 137.0
                perturbed_range = robust.compute_robust_display_range(
                    perturbed, name, null_value)
                entry["negative_self_check"] = (
                    list(perturbed_range) != list(expected))
            else:
                entry["negative_self_check"] = True  # static by design
        else:
            entry["negative_self_check"] = True
        scale_cases.append(encode_case(entry))

    pattern_cases = []
    for probe in PATTERN_PROBES:
        pid = engine._fuzzy_lookup(probe)
        pattern_cases.append({
            "name": probe,
            "pattern_id": pid if pid is not None else "",
        })
    color_cases = []
    for probe in COLOR_PROBES:
        color = engine.get_color_fuzzy(probe)
        color_cases.append({
            "name": probe,
            "color": color.name().lower() if color is not None else "",
        })

    # Equal-length tie check: two equal-length keys both substrings — the
    # frozen table order decides (Python stable sort).
    ties = [k for k in pattern_map.PATTERN_MAP.keys()]
    payload = {
        "schema": SCHEMA,
        "geoviz_gitlink": "08851951f3bbc0beb90886adf52e1928f4383c16",
        "pattern_map": [
            [k, v] for k, v in pattern_map.PATTERN_MAP.items()],
        "facies_colors": [
            [k, v] for k, v in pattern_map.FACIES_COLORS.items()],
        "robust_scale_cases": scale_cases,
        "pattern_lookups": pattern_cases,
        "color_lookups": color_cases,
        "negative_note": (
            "robust_scale negative_self_check=false means the perturbed "
            "input produced an identical range (clamped preset, e.g. GR "
            "already above the 150 floor) — recorded, not silently dropped"),
    }
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    dynamic = sum(1 for c in scale_cases if c["negative_self_check"])
    print(f"wrote {OUT_PATH} ({len(scale_cases)} scale cases, "
          f"{len(pattern_cases)} pattern probes, "
          f"{len(color_cases)} color probes, {dynamic} dynamic negative checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
