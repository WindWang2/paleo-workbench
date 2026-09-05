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
    from geoviz import set_las_parser_provider

    def _boom(content, null_val):
        raise RuntimeError("cpp broken")

    set_las_parser_provider(_boom)
    try:
        data = load_well_log_from_path(str(path))
        # Falls back to engine load_las_preview — still loads
        assert data is not None
        assert data.well_name == "WELL-01"
        assert {c.name for c in data.curves} == {"GR", "DT"}
    finally:
        set_las_parser_provider(None)


def test_fast_channel_actually_engages(tmp_path: Path):
    path = _write_las(tmp_path)
    from geoviz import set_las_parser_provider

    calls = []

    def _spy(content, null_val):
        calls.append(len(content))
        return ("DEPT", "GR", "DT"), np.array([
            [2000.0, 45.2, 220.0],
            [2001.0, 52.1, -999.25],
            [2002.0, 61.8, 215.4],
            [2003.0, -999.25, 210.1],
            [2004.0, 75.3, 205.0],
            [2005.0, 80.0, 200.0],
        ])

    set_las_parser_provider(_spy)
    try:
        # Pass a unique path to bypass cache
        p = tmp_path / "unique_spy.las"
        p.write_text(SAMPLE_LAS, encoding="utf-8")
        data = load_well_log_from_path(str(p))
        assert calls, "fast channel provider hook was never called"
        assert data is not None
        assert {c.name for c in data.curves} == {"GR", "DT"}
    finally:
        set_las_parser_provider(None)


def test_wrapped_las_falls_back_but_loads(tmp_path: Path):
    path = tmp_path / "wrapped.las"
    path.write_text(SAMPLE_LAS.replace("WRAP .                  NO", "WRAP .                 YES"), encoding="utf-8")
    from geoviz import set_las_parser_provider

    def _boom(content, null_val):
        raise AssertionError("fast channel should not run on wrapped LAS")

    set_las_parser_provider(_boom)
    try:
        # fast channel must bail BEFORE parsing data; fallback still loads
        data = load_well_log_from_path(str(path))
        assert data is not None
        assert data.well_name == "WELL-01"
    finally:
        set_las_parser_provider(None)


def test_well_log_cache_is_bounded(tmp_path: Path):
    import paleo_workbench.viz.well_log_load as mod

    for i in range(25):
        p = tmp_path / f"well_{i}.las"
        p.write_text(SAMPLE_LAS, encoding="utf-8")
        load_well_log_from_path(str(p))

    assert len(mod._las_cache) <= 16



# ---------------------------------------------------------------------------
# #403 — the LAS ~C DEPT unit must survive loading (workbench wrapper), so the
# engine adapter no longer hardcodes depth_unit="m".
# ---------------------------------------------------------------------------

FEET_LAS = """~VERSION INFORMATION
 VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0
~WELL INFORMATION
 WELL.             WELL-01 : WELL NAME
 NULL.              -999.25 : NULL VALUE
~CURVE INFORMATION
 DEPT  .FT                  : DEPTH
 GR    .API                 : GAMMA RAY
~A
 2000.00   45.2
 2001.00   52.1
"""


def test_403_feet_las_carries_depth_unit_wrapper(tmp_path: Path):
    from paleo_workbench.viz.well_log_load import (
        WellLogDataWithDepthUnit,
        detect_depth_unit,
        load_well_log_from_path,
    )

    path = tmp_path / "feet.las"
    path.write_text(FEET_LAS, encoding="utf-8")
    assert detect_depth_unit(str(path)) == "ft"
    data = load_well_log_from_path(str(path))
    assert isinstance(data, WellLogDataWithDepthUnit)
    assert data.depth_unit == "ft"


def test_403_meter_las_stays_unwrapped(tmp_path: Path):
    from paleo_workbench.viz.well_log_load import (
        WellLogDataWithDepthUnit,
        detect_depth_unit,
        load_well_log_from_path,
    )

    path = tmp_path / "meter.las"
    path.write_text(SAMPLE_LAS, encoding="utf-8")  # DEPT .M fixture
    assert detect_depth_unit(str(path)) == "m"
    data = load_well_log_from_path(str(path))
    assert not isinstance(data, WellLogDataWithDepthUnit)


def _write_big_las(path: Path, rows: int = 120_000) -> Path:
    lines = SAMPLE_LAS.splitlines(keepends=True)
    head, ascii_start = [], 0
    for i, line in enumerate(lines):
        if line.startswith("~ASCII"):
            ascii_start = i + 1
            break
        head.append(line)
    body = [
        f" {2000.0 + i * 0.05:.2f}   {45.0 + (i % 50) * 0.1:.1f}   {220.0 - (i % 30) * 0.2:.1f}\n"
        for i in range(rows)
    ]
    path.write_text("".join(head) + "~ASCII\n" + "".join(body), encoding="utf-8")
    return path


def test_small_file_not_decimated(tmp_path: Path):
    data = load_well_log_from_path(str(_write_las(tmp_path)))
    assert data is not None
    assert data.decimated is False
    assert data.total_rows == 6


def test_big_file_decimated_with_provenance_and_warning(tmp_path: Path, caplog):
    import logging

    path = _write_big_las(tmp_path / "big.las")
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.viz.well_log_load"):
        data = load_well_log_from_path(str(path))
    assert data is not None
    assert data.decimated is True
    assert data.total_rows == 120_000
    assert any("decimated" in r.message for r in caplog.records)


def test_corrupt_file_logs_reason_and_returns_none(tmp_path: Path, caplog):
    import logging

    path = tmp_path / "bad.las"
    path.write_bytes(b"\x00\xff not las at all \xfe")
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.viz.well_log_load"):
        assert load_well_log_from_path(str(path)) is None
    assert any("could not load" in r.message for r in caplog.records)
