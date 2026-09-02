"""CompositeDocument GIS-authority regressions (CRS chain + convergence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


class _SnapshotSpy:
    def __init__(self, canvas) -> None:
        self._canvas = canvas
        self._original = canvas.set_layer_snapshot
        self.snapshots: list = []

    def __enter__(self):
        canvas = self._canvas
        spy = self

        def _capture(snapshot):
            spy.snapshots.append(snapshot)
            return spy._original(snapshot)

        canvas.set_layer_snapshot = _capture
        return self

    def __exit__(self, *args):
        self._canvas.set_layer_snapshot = self._original


def test_composite_preserves_project_crs_through_layer_updates(qtbot, tmp_path):
    """CRS 权威链：图层显示增量（toggle/opacity/reorder）不得篡改项目 CRS。"""
    project = _project(tmp_path)
    project.coordinate.project_crs = "EPSG:32650"  # projected CRS, not 4326
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)

    doc.edit_controller.create_layer("断层线", "line", template="fault")
    doc.edit_controller.create_layer("相带", "polygon")
    doc._sync_composition()

    assert doc.edit_controller.project_crs == "EPSG:32650"
    assert doc.layer_manager._project_crs == "EPSG:32650"

    layer_ids = list(doc.edit_controller.layer_ids())
    with _SnapshotSpy(doc.canvas) as spy:
        doc.layer_manager.set_layer_visible(layer_ids[0], False)
        doc.layer_manager.set_layer_opacity(layer_ids[1], 0.55)
        doc.layer_manager.move_layer(layer_ids[0], +1)
        assert spy.snapshots, "layer state updates must republish the snapshot"
        for snapshot in spy.snapshots:
            assert snapshot.project_crs == "EPSG:32650"


def test_composite_reloads_crs_on_project_change(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    assert doc.layer_manager._project_crs == str(
        doc.edit_controller.project_crs
    )

    other = _project(tmp_path)
    other.coordinate.project_crs = "EPSG:3857"
    doc.set_project(other)
    assert doc.edit_controller.project_crs == "EPSG:3857"
    doc._sync_composition()
    assert doc.layer_manager._project_crs == "EPSG:3857"
