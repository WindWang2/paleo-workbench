#!/usr/bin/env python3
"""Oracle for the VIZ-D crossplot core (CONV-VIZ V5).

Imports the REAL frozen geoviz reference (geo-viz-engine@08851951):

  * geoviz_seismic.crossplot.analyze_lithology_crossplot — GR/AI cluster
    stats (population std, "Unknown" fallback);
  * geoviz_seismic.attributes.compute_envelope /
    compute_instantaneous_frequency — the attribute crossplot's kernels,
    frozen on the same (n_samples, n_traces) planes the C++ path feeds
    through the science SDK (declared tolerance for the flatten/subsample
    and P1/P99 limits).

Run with a numpy/scipy interpreter:

    /opt/miniconda3/bin/python3 tools/oracle/generate_viz_d_crossplot_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
sys.path.insert(0, str(ENGINE))

from geoviz_seismic.attributes import (  # noqa: E402
    compute_envelope,
    compute_instantaneous_frequency,
)
from geoviz_seismic.crossplot import analyze_lithology_crossplot  # noqa: E402

OUT = REPO_ROOT / "tests" / "cpp" / "viz_d" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def _num(value):
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def lithology_cases() -> dict:
    rng = np.random.default_rng(5)
    n = 40
    gr = rng.normal(60, 25, size=n)
    ai = rng.normal(8000, 1500, size=n)
    labels = [rng.choice(["sandstone", "shale", "limestone"]) for _ in range(n)]
    cases = {}

    def run(case_id, gr_, ai_, labels_):
        result = analyze_lithology_crossplot(np.asarray(gr_, dtype=float),
                                            np.asarray(ai_, dtype=float), labels_)
        clusters = {}
        # dict insertion order == first-seen order
        for label, stats in result["clusters"].items():
            clusters[label] = {k: _num(v) for k, v in stats.items()}
        points = [
            {"gr": _num(p["gr"]), "ai": _num(p["ai"]), "lithology": p["lithology"]}
            for p in result["points"]
        ]
        cases[case_id] = {"gr": _nums(gr_), "ai": _nums(ai_), "labels": list(labels_),
                          "points": points, "clusters": clusters}

    run("basic", gr, ai, labels)
    run("short_labels", gr[:10], ai[:10], labels[:7])  # 3 fall back to Unknown
    run("empty_labels", gr[:4], ai[:4], [])
    run("with_nan", [1.0, float("nan"), 3.0, 4.0], [10.0, 20.0, float("nan"), 40.0],
        ["a", "a", "b", "b"])
    return cases


def attribute_cases() -> dict:
    rng = np.random.default_rng(9)
    dt_s = 0.004
    cases = {}

    def run(case_id, plane):
        env = compute_envelope(plane, axis=0)
        freq = compute_instantaneous_frequency(plane, axis=0, sample_interval=dt_s)
        # dialogs/crossplot.py worker parity: subsample step = max(1, size//5000)
        step = max(1, env.size // 5000)
        x = np.asarray(freq).flatten()[::step]
        y = np.asarray(env).flatten()[::step]
        xlo, xhi = float(np.nanpercentile(x, 1)), float(np.nanpercentile(x, 99))
        ylo, yhi = float(np.nanpercentile(y, 1)), float(np.nanpercentile(y, 99))
        if xhi <= xlo:
            xhi = xlo + 1
        if yhi <= ylo:
            yhi = ylo + 1
        cases[case_id] = {
            "plane": _nums(plane),
            "n_samples": plane.shape[0],
            "n_traces": plane.shape[1],
            "dt_s": dt_s,
            "step": step,
            "freq_sub": _nums(x),
            "env_sub": _nums(y),
            "x_limits": [_num(xlo), _num(xhi)],
            "y_limits": [_num(ylo), _num(yhi)],
        }

    t = np.arange(120.0)
    wave = (np.sin(2 * np.pi * 15.0 * t * 0.004)[:, None]
            * np.linspace(0.5, 1.5, 7)[None, :]).astype(np.float32)
    run("sine_7traces", wave)
    noisy = (wave + rng.normal(0, 0.2, size=wave.shape)).astype(np.float32)
    run("noisy", noisy)
    return cases


def main() -> None:
    fixture = {
        "generator": "tools/oracle/generate_viz_d_crossplot_fixtures.py",
        "engine": "geo-viz-engine@08851951",
        "lithology": lithology_cases(),
        "attribute": attribute_cases(),
    }
    path = OUT / "viz_d_crossplot_oracle.json"
    path.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
