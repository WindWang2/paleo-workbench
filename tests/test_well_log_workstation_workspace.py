"""Workspace catalog model + shell tree wiring (#217)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.shell import WellLogWorkstationWindow
from well_log_workstation.workspace import (
    WORKSPACE_FILENAME,
    WorkspaceError,
    add_plot,
    add_well,
    create_workspace,
    open_workspace,
    save_workspace,
)


def test_create_workspace_skeleton(tmp_path: Path) -> None:
    root = tmp_path / "field-a"
    ws = create_workspace(root, name="Field A")
    assert ws.root == root.resolve()
    assert ws.name == "Field A"
    assert (root / WORKSPACE_FILENAME).is_file()
    assert (root / "wells").is_dir()
    assert (root / "plots").is_dir()
    assert (root / "templates").is_dir()
    data = json.loads((root / WORKSPACE_FILENAME).read_text(encoding="utf-8"))
    assert data["schemaVersion"] == 1
    assert data["name"] == "Field A"
    assert data["wells"] == []
    assert data["plots"] == []
    # Must not look like an engine Manifest whole-project
    assert "schemaVersion" in data
    assert "document" not in data
    assert "requiredSdkVersion" not in data


def test_open_round_trip_catalog_entries(tmp_path: Path) -> None:
    root = tmp_path / "field-b"
    ws = create_workspace(root)
    well = add_well(ws, name="Well-A", path="wells/Well-A.las")
    plot = add_plot(
        ws,
        name="Well-A 单井分析图",
        plot_type="single_well",
        well_ids=[well.id],
        template_id="std-gr-rt-den",
        path="plots/well-a-single.json",
    )
    add_plot(
        ws,
        name="A–C 对比",
        plot_type="correlation",
        well_ids=[well.id],
    )

    again = open_workspace(root)
    assert again.name == root.name
    assert len(again.wells) == 1
    assert again.wells[0].id == well.id
    assert again.wells[0].name == "Well-A"
    assert again.wells[0].path == "wells/Well-A.las"
    assert len(again.plots) == 2
    names = {p.name for p in again.plots}
    assert "Well-A 单井分析图" in names
    assert "A–C 对比" in names
    single = next(p for p in again.plots if p.id == plot.id)
    assert single.type == "single_well"
    assert single.well_ids == [well.id]
    assert single.template_id == "std-gr-rt-den"


def test_create_rejects_nonempty_without_clobber(tmp_path: Path) -> None:
    root = tmp_path / "busy"
    root.mkdir()
    (root / "noise.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not empty"):
        create_workspace(root)


def test_open_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="not a workspace"):
        open_workspace(tmp_path / "nope")


def test_shell_tree_shows_catalog(qtbot, tmp_path: Path) -> None:
    root = tmp_path / "ui-field"
    ws = create_workspace(root, name="UI Field")
    add_well(ws, name="Well-X", path="wells/x.las")
    add_plot(ws, name="X 单井", plot_type="single_well", well_ids=[ws.wells[0].id])

    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)

    assert win.workspace is not None
    assert win.workspace.name == "UI Field"
    # Flatten tree labels
    labels: list[str] = []

    def walk(item) -> None:
        labels.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(win.workspace_tree.topLevelItemCount()):
        walk(win.workspace_tree.topLevelItem(i))

    assert any("UI Field" in x or x == "UI Field" for x in labels)
    assert "Well-X" in labels
    assert any("X 单井" in x for x in labels)
    assert "Well Log Workstation" in win.windowTitle() or "UI Field" in win.windowTitle()
