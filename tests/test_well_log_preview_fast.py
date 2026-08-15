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


def test_wrapped_las_preview_uses_lasio_fallback(tmp_path: Path):
    # Genuinely wrapped data section: each depth step spans two lines.
    header_part, data_part = SAMPLE_LAS.split("~ASCII\n")
    wrapped_lines = []
    for line in data_part.strip().splitlines():
        vals = line.split()
        wrapped_lines.append(" " + vals[0])
        wrapped_lines.append(" " + "   ".join(vals[1:]))
    wrapped = (
        header_part.replace("WRAP .                  NO", "WRAP .                 YES")
        + "~ASCII\n"
        + "\n".join(wrapped_lines)
        + "\n"
    )
    path = tmp_path / "wrapped.las"
    path.write_text(wrapped, encoding="utf-8")
    resource = ResourceItem(name="wrapped.las", path=str(path), type="well_log", format="las")
    result = las_preview(resource, _Settings())
    # Wrapped file: table still populated (via lasio fallback)
    assert result.data_headers == ("DEPT", "GR", "DT")
    assert len(result.data_rows) == 6
    assert result.data_rows[0] == ("2000", "45.2", "220")


# ---------------------------------------------------------------------------
# #433 — "~A LOG DATA" is a title, not inline headers: the preview table must
# show every ~CURVE column, and a column/curve mismatch must surface a warning.
# ---------------------------------------------------------------------------

LOG_DATA_LAS = """~VERSION INFORMATION
 VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0
~WELL INFORMATION
 WELL.             WELL-01 : WELL NAME
 NULL.              -999.25 : NULL VALUE
~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
 RHOB  .G/CC                : BULK DENSITY
~A LOG DATA
 2000.00   45.2   2.35
 2001.00   52.1   -999.25
 2002.00   61.8   2.41
"""


def test_433_a_log_data_preview_shows_all_curves(tmp_path: Path):
    path = tmp_path / "log_data.las"
    path.write_text(LOG_DATA_LAS, encoding="utf-8")
    resource = ResourceItem(name="log_data.las", path=str(path), type="well_log", format="las")
    result = las_preview(resource, _Settings())
    assert result.data_headers == ("DEPT", "GR", "RHOB")
    assert len(result.data_rows) == 3
    assert result.data_rows[0] == ("2000", "45.2", "2.35")
    assert result.data_rows[1][2] == "NaN"
    assert result.warning == ""


def test_433_preview_warns_on_column_curve_mismatch(tmp_path: Path):
    # ~CURVE declared after the ~A data section: the fast parser cannot see it
    # and falls back to the ~A words -> 2 columns vs 3 declared curves.
    path = tmp_path / "mismatch.las"
    path.write_text(
        "~VERSION INFORMATION\n"
        " VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0\n"
        "~WELL INFORMATION\n"
        " WELL.             WELL-01 : WELL NAME\n"
        " NULL.              -999.25 : NULL VALUE\n"
        "~A LOG DATA\n"
        " 2000.00   45.2   2.35\n"
        " 2001.00   52.1   2.38\n"
        "~CURVE INFORMATION\n"
        " DEPT  .M                   : DEPTH\n"
        " GR    .API                 : GAMMA RAY\n"
        " RHOB  .G/CC                : BULK DENSITY\n",
        encoding="utf-8",
    )
    resource = ResourceItem(name="mismatch.las", path=str(path), type="well_log", format="las")
    result = las_preview(resource, _Settings())
    assert "不一致" in result.warning
