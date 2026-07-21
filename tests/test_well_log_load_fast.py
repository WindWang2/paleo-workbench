"""Tests for the C++ fast LAS loading channel in well_log_load."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from paleo_workbench.viz.well_log_load import load_well_log_from_path

SAMPLE_LAS = """~VERSION INFORMATION
 VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0
 WRAP .                  NO : ONE LINE PER DEPTH STEP
~WELL INFORMATION
 WELL.             WELL-01 : WELL NAME
 STRT.M             2000.00 : START DEPTH
 STOP.M             2005.00 : STOP DEPTH
 STEP.M                1.00 : STEP
 NULL.              -999.25 : NULL VALUE
~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
 DT    .US/M                : ACOUSTIC TRANSIT TIME
~ASCII
 2000.00   45.2   220.0
 2001.00   52.1   -999.25
 2002.00   61.8   215.4
 2003.00   -999.25 210.1
 2004.00   75.3   205.0
 2005.00   80.0   200.0
"""


def _write_las(tmp_path: Path) -> Path:
    path = tmp_path / "well.las"
    path.write_text(SAMPLE_LAS, encoding="utf-8")
    return path


def test_fast_channel_loads_curves_with_units(tmp_path: Path):
    path = _write_las(tmp_path)
    data = load_well_log_from_path(str(path))
    assert data is not None
    assert data.well_name == "WELL-01"
    by_name = {c.name: c for c in data.curves}
    assert set(by_name) == {"GR", "DT"}
    assert by_name["GR"].unit == "API"
    assert by_name["DT"].unit == "US/M"
    assert data.top_depth == 2000.0
    assert data.bottom_depth == 2005.0
    assert len(by_name["GR"].depth) == 6


def test_fast_channel_null_values_become_nan(tmp_path: Path):
    path = _write_las(tmp_path)
    data = load_well_log_from_path(str(path))
    by_name = {c.name: c for c in data.curves}
    assert np.isnan(by_name["DT"].values[1])
    assert np.isnan(by_name["GR"].values[3])
    assert by_name["GR"].values[0] == 45.2


def test_fallback_when_fast_channel_raises(tmp_path: Path, monkeypatch):
    path = _write_las(tmp_path)
    import paleo_workbench.viz.well_log_load as mod

    def _boom(content):
        raise RuntimeError("cpp broken")

    monkeypatch.setattr(mod, "fast_las_parse_data", _boom)
    data = load_well_log_from_path(str(path))
    # Falls back to engine load_las_preview — still loads
    assert data is not None
    assert data.well_name == "WELL-01"
    assert {c.name for c in data.curves} == {"GR", "DT"}
