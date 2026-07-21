"""LAS table preview must not use lasio (C++ fast channel instead)."""
from __future__ import annotations

import sys
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.well_log_parsers import las_preview

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


class _Settings:
    table_max_rows = 100


def _resource(tmp_path: Path) -> ResourceItem:
    path = tmp_path / "well.las"
    path.write_text(SAMPLE_LAS, encoding="utf-8")
    return ResourceItem(name="well.las", path=str(path), type="well_log", format="las")


def test_preview_data_rows_without_lasio(tmp_path: Path, monkeypatch):
    # Forbid lasio entirely: preview must still produce the data table.
    monkeypatch.setitem(sys.modules, "lasio", None)
    result = las_preview(_resource(tmp_path), _Settings())
    assert result.data_headers == ("DEPT", "GR", "DT")
    assert len(result.data_rows) == 6
    assert result.data_rows[0] == ("2000", "45.2", "220")
    # NULL -> NaN display
    assert result.data_rows[1][2] == "NaN"
    assert result.data_rows[3][1] == "NaN"
