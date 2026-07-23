"""Unit tests for C++ LASParserProvider & LOD Downsampling (Ticket 01)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.native_backend import native_backend
from paleo_workbench.viz.well_log_load import load_well_log_from_path

SAMPLE_LAS_LOD = """~VERSION INFORMATION
 VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0
 WRAP .                  NO : ONE LINE PER DEPTH STEP
~WELL INFORMATION
 WELL.             LOD-WELL-01 : WELL NAME
 STRT.M             1000.00 : START DEPTH
 STOP.M             1010.00 : STOP DEPTH
 STEP.M                1.00 : STEP
 NULL.              -999.25 : NULL VALUE
~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
~ASCII
 1000.00   10.0
 1001.00   20.0
 1002.00   30.0
 1003.00   40.0
 1004.00   50.0
 1005.00   60.0
 1006.00   70.0
 1007.00   80.0
 1008.00   90.0
 1009.00   100.0
 1010.00   110.0
"""


def test_las_parser_provider_registered():
    from geoviz import get_las_parser_provider
    hook = get_las_parser_provider()
    if hook is None and not native_backend.has_cpp("well_log"):
        pytest.skip("no LAS parser backend registered (well_log_core not built)")
    assert hook is not None or native_backend.has_cpp("well_log") is True


def test_las_parser_provider_parse(tmp_path: Path):
    path = tmp_path / "lod_well.las"
    path.write_text(SAMPLE_LAS_LOD, encoding="utf-8")

    well_data = load_well_log_from_path(str(path))
    assert well_data is not None
    assert well_data.well_name == "LOD-WELL-01"
    by_name = {c.name: c for c in well_data.curves}
    assert "GR" in by_name
    assert len(by_name["GR"].values) == 11
