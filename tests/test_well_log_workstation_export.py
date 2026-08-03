"""Export active multi-track presentation to SVG/PDF (#221)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.export_plot import (  # noqa: E402
    ExportError,
    export_presentation_pdf,
    export_presentation_svg,
)
from well_log_workstation.shell import WellLogWorkstationWindow  # noqa: E402
from well_log_workstation.workspace import create_workspace  # noqa: E402


def _write_las(path: Path, well: str = "EXP-1") -> Path:
    path.write_text(
        f"""~VERSION INFORMATION
VERS. 2.0
WRAP. NO
~WELL INFORMATION
STRT.M 1000.0
STOP.M 1004.0
STEP.M 1.0
NULL. -999.25
WELL. {well}
~CURVE INFORMATION
DEPT.M
GR.GAPI
RT.OHMM
RHOB.G/C3
~ASCII
1000 20 2 2.2
1001 30 5 2.3
1002 40 10 2.4
1003 50 20 2.5
1004 60 50 2.6
""",
        encoding="utf-8",
    )
    return path


def test_export_svg_and_pdf_nonempty(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws", name="Export")
    las = _write_las(tmp_path / "e.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    assert win.active_presentation is not None
    assert win.active_presentation.track_count >= 2

    svg_path = tmp_path / "out" / "plot.svg"
    pdf_path = tmp_path / "out" / "plot.pdf"
    out_svg = win.export_active_plot_svg(svg_path)
    out_pdf = win.export_active_plot_pdf(pdf_path)

    assert out_svg.is_file()
    assert out_svg.stat().st_size >= 50
    text = out_svg.read_text(encoding="utf-8", errors="replace")
    assert "svg" in text.lower() or out_svg.stat().st_size > 200

    assert out_pdf.is_file()
    assert out_pdf.stat().st_size >= 50
    # PDF magic
    assert out_pdf.read_bytes()[:4] == b"%PDF"


def test_export_without_presentation_raises(qtbot, tmp_path: Path) -> None:
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    with pytest.raises(ExportError):
        win.export_active_plot_svg(tmp_path / "x.svg")
    with pytest.raises(ExportError):
        win.export_active_plot_pdf(tmp_path / "x.pdf")


def test_export_presentation_api_direct(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws2")
    las = _write_las(tmp_path / "d.las", well="DIR")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    pres = win.apply_template_to_well(well_id, "std-gr-rt-den")
    svg = export_presentation_svg(pres, tmp_path / "direct.svg")
    pdf = export_presentation_pdf(pres, tmp_path / "direct.pdf")
    assert svg.stat().st_size >= 50
    assert pdf.stat().st_size >= 50
