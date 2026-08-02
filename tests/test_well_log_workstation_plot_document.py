"""Single-well plot document persistence (#220)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.plot_document import (
    create_single_well_plot,
    load_plot_document,
)
from well_log_workstation.shell import WellLogWorkstationWindow
from well_log_workstation.workspace import create_workspace, open_workspace


def _write_las(path: Path) -> Path:
    path.write_text(
        """~VERSION INFORMATION
VERS. 2.0
WRAP. NO
~WELL INFORMATION
STRT.M 1000.0
STOP.M 1003.0
STEP.M 1.0
NULL. -999.25
WELL. PLOT-1
~CURVE INFORMATION
DEPT.M
GR.GAPI
RT.OHMM
~ASCII
1000 10 1
1001 20 2
1002 30 3
1003 40 4
""",
        encoding="utf-8",
    )
    return path


def test_create_persist_reopen_plot_metadata(tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws")
    # Catalog well without going through full import path for metadata test
    from well_log_workstation.workspace import add_well

    well = add_well(ws, name="W1", path="wells/w1.las", well_id="well-fixed")
    plot = create_single_well_plot(
        ws,
        well_id=well.id,
        well_name=well.name,
        template_id="std-gr-rt-den",
    )
    assert plot.path.startswith("plots/")
    assert (ws.root / plot.path).is_file()
    assert any(p.id == plot.id for p in ws.plots)

    again = open_workspace(ws.root)
    loaded = load_plot_document(again, plot.id)
    assert loaded.name == plot.name
    assert loaded.well_ids == [well.id]
    assert loaded.template_id == "std-gr-rt-den"
    assert loaded.type == "single_well"


def test_shell_create_and_reopen_plot_restores_tracks(qtbot, tmp_path: Path) -> None:
    ws_root = tmp_path / "ui-ws"
    ws = create_workspace(ws_root, name="Plots")
    las = _write_las(tmp_path / "p.las")

    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    plot = win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    assert win.active_plot_id == plot.id
    assert win.multi_track_canvas.track_count() >= 2
    assert (ws.root / plot.path).is_file()

    # Simulate reopen: new window, open workspace, open plot
    win2 = WellLogWorkstationWindow()
    qtbot.addWidget(win2)
    win2.set_workspace(open_workspace(ws_root))
    # Session empty until open
    assert win2.session.get(well_id) is None
    opened = win2.open_plot_document(plot.id)
    assert opened.id == plot.id
    assert win2.session.get(well_id) is not None
    assert win2.active_presentation is not None
    assert win2.multi_track_canvas.track_count() >= 2
    # Switching selection does not drop session docs
    assert well_id in win2.session.document_ids()
