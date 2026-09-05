"""V5 page integration tests: workspace controller on the real page,
tree/inspector/QC wiring, measurement flow, clipping, persistence."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.models import Geo3DWorkspaceState, ProjectDocument
from paleo_workbench.ui.pages.geological_modeling_3d_page import (
    GEO_TREE_ROOT_LABEL,
    GeologicalModeling3DPage,
)
from paleo_workbench.viz.geomodel.builders import build_simplified_vertical_well
from paleo_workbench.viz.geomodel.domain import (
    DomainError,
    Provenance,
    WellTrajectory,
)


@pytest.fixture()
def page(qtbot):
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    return page


class TestWorkspaceSection:
    def test_tree_has_geo_section(self, page):
        root = page.model_tree.invisibleRootItem()
        labels = [root.child(i).text(0) for i in range(root.childCount())]
        assert GEO_TREE_ROOT_LABEL in labels

    def test_add_object_updates_tree_and_qc(self, page):
        well = build_simplified_vertical_well(
            "W-9", (10.0, 20.0, 0.0), 300.0,
            crs="EPSG:32650",
            provenance=Provenance(source_kind="catalog", source_version_ids=("v1",)),
        )
        page._geo3d.add_object(well)
        root_item = page._geo3d_tree_root
        texts = []
        for i in range(root_item.childCount()):
            branch = root_item.child(i)
            for j in range(branch.childCount()):
                texts.append(branch.child(j).text(0))
        assert any("W-9" in t for t in texts)
        # simplified representation is honestly labelled in the tree
        assert any("简化垂直" in t for t in texts)

    def test_qc_panel_shows_blocker_for_unknown_crs(self, page):
        bad = build_simplified_vertical_well("W-bad", (0, 0, 0), 100.0)  # no CRS
        page._geo3d.add_object(bad)
        items = [
            page.geo_qc_list.item(i).text()
            for i in range(page.geo_qc_list.count())
        ]
        assert any("MISSING_CRS" in t for t in items)
        assert any("blocker" in t for t in items)

    def test_inspector_shows_identity(self, page):
        well = build_simplified_vertical_well(
            "W-insp", (1, 2, 0), 50.0, crs="EPSG:32650"
        )
        page._geo3d.add_object(well)
        page._geo3d.set_selected(well.object_id, broadcast=False)
        html = page.geo_inspector.toPlainText()
        assert "W-insp" in html
        assert "EPSG:32650" in html
        assert "simplified_vertical" in html


class TestTreeVisibility:
    def test_unchecking_hides_object(self, page, qtbot):
        well = build_simplified_vertical_well("W-h", (0, 0, 0), 100.0, crs="EPSG:32650")
        page._geo3d.add_object(well)
        page._refresh_geo_tree_section()
        root_item = page._geo3d_tree_root
        item = None
        from PySide6.QtCore import Qt

        for i in range(root_item.childCount()):
            branch = root_item.child(i)
            for j in range(branch.childCount()):
                if str(branch.child(j).data(0, Qt.ItemDataRole.UserRole)) == well.object_id:
                    item = branch.child(j)
        assert item is not None
        item.setCheckState(0, Qt.CheckState.Unchecked)
        assert page._geo3d.adapter.visibility(well.object_id) is False


class TestMeasurementFlow:
    def test_distance_measurement_via_stubbed_pick(self, page, qtbot):
        class StubPick:
            def __init__(self, pts):
                self.pts = list(pts)
                self.object_id = "well:x"
                self.kind = "well"

            def __call__(self, px, py):
                return self.pts.pop(0) if self.pts else None

        page._geo3d.set_measure_mode("distance")
        assert page._geo3d.measure_mode == "distance"
        # two clicks at distinct domain points
        from paleo_workbench.viz.geomodel.scene_adapter import DomainPick

        picks = [
            DomainPick("well:x", "well", (0.0, 0.0, 0.0), 1.0),
            DomainPick("well:x", "well", (3.0, 4.0, 0.0), 1.0),
        ]
        page._geo3d.adapter.pick = lambda *a, **k: picks.pop(0)
        assert page._geo3d.handle_viewport_click(10, 10) is True
        assert page._geo3d.handle_viewport_click(20, 20) is True
        measures = page._geo3d.assembly.objects("measure")
        assert len(measures) == 1
        assert measures[0].result == pytest.approx(5.0)
        # measurement mode auto-stays armed; clear removes records
        page._on_geo_measure_clear()
        assert len(page._geo3d.assembly.objects("measure")) == 0

    def test_no_pick_no_measure_is_not_consumed(self, page):
        page._geo3d.adapter.pick = lambda *a, **k: None
        assert page._geo3d.handle_viewport_click(1, 1) is False

    def test_well_selection_broadcast(self, page, qtbot):
        from paleo_workbench.viz.geomodel.scene_adapter import DomainPick

        well = build_simplified_vertical_well("W-bc", (0, 0, 0), 100.0, crs="EPSG:32650")
        page._geo3d.add_object(well)
        page._geo3d.adapter.pick = lambda *a, **k: DomainPick(
            well.object_id, "well", (0.0, 0.0, 50.0), 1.0
        )
        with qtbot.waitSignal(page.well_selected, timeout=2000):
            page._geo3d.handle_viewport_click(5, 5)


class TestClipping:
    def test_hidden_card_controls_drive_controller(self, page):
        page.chk_clip_x.setChecked(True)
        page.slide_clip_x.setValue(70)
        page._update_clipping()
        state = page._geo3d.clip_state["x"]
        assert state["enabled"] is True
        assert state["value"] == pytest.approx(0.70)
        page.chk_clip_x.setChecked(False)
        page._update_clipping()
        assert page._geo3d.clip_state["x"]["enabled"] is False

    def test_compact_rows_drive_controller(self, page):
        page._geo_clip_rows["z"][0].setChecked(True)
        page._geo_clip_rows["z"][1].setValue(25)
        assert page._geo3d.clip_state["z"]["enabled"] is True
        assert page._geo3d.clip_state["z"]["value"] == pytest.approx(0.25)
        page._on_geo_clip_reset()
        assert page._geo3d.clip_state["z"]["enabled"] is False


class TestDemoIngest:
    def test_demo_result_becomes_domain_objects(self, page):
        result = {
            "demo": True,
            "bh_raw": [
                {
                    "name": "ZK1",
                    "x": 10.0,
                    "y": 20.0,
                    "td": 300.0,
                    "layers": [
                        {"lithology": "sand", "top": 0.0},
                        {"lithology": "mud", "top": 120.0},
                    ],
                }
            ],
            "tunnels_raw": [
                {"name": "巷道A", "path": [[0, 0, 0], [50, 0, -10], [100, 0, -20]]}
            ],
            "faults_raw": [{"name": "F1", "normal": (0.0, 1.0, 0.0), "d": 20.0}],
            "extent": (-80.0, 80.0, -80.0, 80.0),
        }
        counts = page._geo3d.ingest_demo_result(result)
        assert counts == {"wells": 1, "tunnels": 1, "faults": 1}
        kinds = sorted(o.object_id.split(":")[0] for o in page._geo3d.assembly.objects())
        assert kinds == ["fault", "tunnel", "well"]
        well = page._geo3d.assembly.get("well:zk1")
        assert well.representation == "simplified_vertical"
        assert well.provenance.demo is True
        # tree shows the demo badge
        page._refresh_geo_tree_section()
        root_item = page._geo3d_tree_root
        texts = []
        for i in range(root_item.childCount()):
            branch = root_item.child(i)
            for j in range(branch.childCount()):
                texts.append(branch.child(j).text(0))
        assert any("(demo)" in t for t in texts)


class TestPersistence:
    def test_save_restore_roundtrip(self, page, tmp_path):
        project = ProjectDocument.new("geo3d-persist")
        well = build_simplified_vertical_well(
            "W-p", (5, 6, 0), 120.0,
            crs="EPSG:32650",
            provenance=Provenance(source_kind="catalog", source_version_ids=("v9",)),
        )
        page._geo3d.add_object(well)
        page._geo3d.set_visibility(well.object_id, False)
        page._geo3d.save_state(project)

        payload = project.geo3d_workspace.as_dict()
        assert payload["objects"][0]["object_id"] == well.object_id
        assert payload["display"][well.object_id]["visible"] is False

        # a fresh page restores references and display state
        page2 = GeologicalModeling3DPage()
        page2._geo3d_tree_root = None  # not mounted yet; restore must still work
        restored = page2._geo3d.restore_state(project)
        assert restored == [well.object_id]
        obj = page2._geo3d.assembly.get(well.object_id)
        assert obj is not None
        assert obj.name == "W-p"
        assert page2._geo3d.adapter.visibility(well.object_id) is False

    def test_demo_objects_not_persisted(self, page):
        project = ProjectDocument.new("geo3d-demo")
        page._geo3d.ingest_demo_result(
            {
                "bh_raw": [{"name": "ZKD", "x": 0, "y": 0, "td": 100, "layers": []}],
                "extent": (-80, 80, -80, 80),
            }
        )
        page._geo3d.save_state(project)
        assert project.geo3d_workspace.objects == []

    def test_broken_workspace_section_degrades(self, page):
        project = ProjectDocument.new("geo3d-broken")
        project.geo3d_workspace.replace(
            {
                "objects": [{"object_id": "well:bad", "name": "bad"}],
                "measurements": [],
                "display": {},
                "clip": {},
                "camera": {},
                "views": [],
            }
        )
        # malformed entry (missing provenance fields is fine; but unknown
        # kind entries are skipped) — must not raise
        project.geo3d_workspace.replace(
            {
                "objects": [{"object_id": "weird:bad", "name": "x"}],
                "measurements": [],
            }
        )
        restored = page._geo3d.restore_state(project)
        assert restored == []


class TestSaveReopenCycles:
    def test_repeated_project_switch_cycles(self, page, qtbot):
        """G17/E3: ≥30 open/load/close/reopen cycles without lifecycle
        failures (offscreen: the joint widget degrades to None, which is
        exactly the GL-less teardown path the controller must survive)."""
        project_a = ProjectDocument.new("cycle-a")
        project_b = ProjectDocument.new("cycle-b")
        well = build_simplified_vertical_well(
            "W-cycle", (0, 0, 0), 100.0, crs="EPSG:32650"
        )
        for cycle in range(30):
            page.set_project(project_a)
            page._geo3d.add_object(well)
            page._geo3d.save_state(project_a)
            page.set_project(project_b)
            assert well.object_id not in page._geo3d.assembly
            page.set_project(project_a)
            assert well.object_id in page._geo3d.assembly
            page.set_project(None)
        qtbot.wait(50)

    def test_controller_reset_between_projects(self, page):
        well = build_simplified_vertical_well("W-r", (0, 0, 0), 100.0, crs="EPSG:32650")
        page._geo3d.add_object(well)
        page._geo3d.reset()
        assert len(page._geo3d.assembly) == 0
        assert page._geo3d.selected_id is None
