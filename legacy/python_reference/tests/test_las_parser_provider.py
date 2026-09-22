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
    from geoviz import (
        get_downsample_provider,
        get_isosurface_extractor,
        get_las_parser_provider,
        set_downsample_provider,
        set_isosurface_extractor,
        set_las_parser_provider,
    )
    from paleo_workbench.native_backend import _cpp_las_parser_provider, native_backend

    if not native_backend.has_cpp("well_log"):
        pytest.skip("well_log_core C++ extension not built in this environment")

    prev = (
        get_downsample_provider(),
        get_isosurface_extractor(),
        get_las_parser_provider(),
    )
    try:
        native_backend.install_all_hooks()
        hook = get_las_parser_provider()
        assert hook is _cpp_las_parser_provider, (
            "install_all_hooks() must register the native C++ LAS parser provider"
        )
        # The registered provider must parse a real LAS through the native backend.
        headers, data = hook("~A DEPT GR\n100.0 45.0\n100.1 48.0\n100.2 50.0\n", -999.0)
        assert headers == ("DEPT", "GR")
        assert data.shape == (3, 2)
        assert data[0, 0] == 100.0
    finally:
        set_downsample_provider(prev[0])
        set_isosurface_extractor(prev[1])
        set_las_parser_provider(prev[2])


def test_las_parser_provider_parse(tmp_path: Path):
    path = tmp_path / "lod_well.las"
    path.write_text(SAMPLE_LAS_LOD, encoding="utf-8")

    well_data = load_well_log_from_path(str(path))
    assert well_data is not None
    assert well_data.well_name == "LOD-WELL-01"
    by_name = {c.name: c for c in well_data.curves}
    assert "GR" in by_name
    assert len(by_name["GR"].values) == 11
