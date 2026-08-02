"""Multi-track template library + apply (#219)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.las_import import import_las_into_workspace
from well_log_workstation.shell import WellLogWorkstationWindow
from well_log_workstation.template_model import (
    apply_template,
    get_builtin_template,
    list_builtin_templates,
)
from well_log_workstation.workspace import create_workspace


def _write_las(path: Path) -> Path:
    path.write_text(
        """~VERSION INFORMATION
VERS. 2.0
WRAP. NO
~WELL INFORMATION
STRT.M 1000.0
STOP.M 1005.0
STEP.M 1.0
NULL. -999.25
WELL. MULTI-1
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
1005 70 100 2.7
""",
        encoding="utf-8",
    )
    return path


def test_builtin_library_has_multi_track() -> None:
    templates = list_builtin_templates()
    assert len(templates) >= 1
    std = get_builtin_template("std-gr-rt-den")
    assert std is not None
    assert len(std.tracks) >= 2
    roles = [t.get("role") for t in std.tracks]
    assert "depth" in roles
    assert roles.count("curve") >= 1


def test_apply_template_binds_multiple_tracks(tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws")
    las = _write_las(tmp_path / "m.las")
    result = import_las_into_workspace(ws, las)
    template = get_builtin_template("std-gr-rt-den")
    assert template is not None
    pres = apply_template(template, result.document)
    assert pres.track_count >= 2
    assert pres.curve_track_count >= 1
    # depth + at least one bound curve track
    assert any(t.role == "depth" for t in pres.tracks)
    bound_layers = sum(len(t.layers) for t in pres.tracks if t.role == "curve")
    assert bound_layers >= 1


def test_shell_apply_shows_multi_track_canvas(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ui", name="Tpl")
    las = _write_las(tmp_path / "u.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    pres = win.apply_template_to_well(well_id, "std-gr-rt-den")
    assert pres.track_count >= 2
    assert win.multi_track_canvas.track_count() >= 2
    assert win.active_presentation is not None
    assert win.multi_track_canvas.presentation() is not None
