"""Joint analysis project persistence (#90)."""

from __future__ import annotations

from paleo_workbench.project.models import (
    JointAnalysisState,
    JointTimeSliceState,
    ProjectDocument,
)


def test_joint_analysis_state_roundtrip_in_project():
    doc = ProjectDocument.new("demo")
    doc.joint_analysis = JointAnalysisState(
        tree_checks={"地震预览体 (geoviz)": True, "井震 2D 剖面条": False},
        well_visibility={"A1": False, "A2": True},
        well_identity_asset_id="res:wells",
        well_identity_map={"name:A1": "source:a1", "name:A2": "source:a2"},
        orthogonal_inline_index=12,
        orthogonal_crossline_index=34,
        time_slices=[
            JointTimeSliceState(time_ms=800.0),
            JointTimeSliceState(time_ms=1200.0, visible=False),
        ],
        active_time_slice_ms=1200.0,
        time_slice_opacity=65,
        vertical_domain="Depth",
        active_fence_wells=["A1", "A2"],
        path_hints={"segy": "/tmp/x.sgy"},
    )
    data = doc.model_dump()
    assert "joint_analysis" in data
    # The persisted joint analysis carries the tree-check state (the prior
    # `... or True` escape let this pass while asserting nothing).
    assert data["joint_analysis"]["tree_checks"]["地震预览体 (geoviz)"] is True
    restored = ProjectDocument.model_validate(data)
    assert restored.joint_analysis.vertical_domain == "Depth"
    assert restored.joint_analysis.active_fence_wells == ["A1", "A2"]
    assert restored.joint_analysis.tree_checks["井震 2D 剖面条"] is False
    assert restored.joint_analysis.well_visibility == {"A1": False, "A2": True}
    assert restored.joint_analysis.well_identity_asset_id == "res:wells"
    assert restored.joint_analysis.well_identity_map == {
        "name:A1": "source:a1",
        "name:A2": "source:a2",
    }
    assert restored.joint_analysis.orthogonal_inline_index == 12
    assert restored.joint_analysis.orthogonal_crossline_index == 34
    assert [
        (item.time_ms, item.visible)
        for item in restored.joint_analysis.time_slices
    ] == [(800.0, True), (1200.0, False)]
    assert restored.joint_analysis.active_time_slice_ms == 1200.0
    assert restored.joint_analysis.time_slice_opacity == 65
    # No voxel payload
    assert "shape" not in data["joint_analysis"]


def test_geomodel_collect_joint_state(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
    from paleo_workbench.project.models import ProjectDocument

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    doc = ProjectDocument.new("t")
    doc.joint_analysis.well_identity_asset_id = "res:wells"
    doc.joint_analysis.well_identity_map = {
        "asset:test|name:A1": "source:a1"
    }
    page.set_project(doc)
    page._joint_domain.setCurrentText("Depth")
    state = page.collect_joint_analysis_state()
    assert state.vertical_domain == "Depth"
    assert state.well_identity_map == {
        "asset:test|name:A1": "source:a1"
    }
    assert state.well_identity_asset_id == "res:wells"
    page.save_joint_analysis_to_project()
    assert page._project.joint_analysis.vertical_domain == "Depth"


def test_color_scale_card_updates_scene_and_roundtrips_project_settings(
    qtbot, tmp_path, monkeypatch
):
    from geoviz_well_seismic_3d import JointDisplaySettings
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )
    from paleo_workbench.viz import joint_host as host_mod

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    project = ProjectDocument.new("colors")
    project.joint_analysis = JointAnalysisState(
        seismic_color_scale="gray",
        gr_color_scale="plasma",
        well_width_px=7,
    )
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)

    page.set_project(project)
    page._joint_color_card_btn.click()

    assert page._joint_color_card.isVisibleTo(page)
    assert page._joint_seismic_color.currentData() == "gray"
    assert page._joint_gr_color.currentData() == "plasma"
    assert page._joint_well_width.value() == 7
    assert page._joint_host.scene.display_settings == JointDisplaySettings(
        seismic_color_scale="gray",
        gr_color_scale="plasma",
        well_width_px=7,
    )
    state = page.collect_joint_analysis_state()
    assert (
        state.seismic_color_scale,
        state.gr_color_scale,
        state.well_width_px,
    ) == ("gray", "plasma", 7)


def test_orthogonal_slice_card_restores_stack_domain_and_project_state(
    qtbot, tmp_path, monkeypatch
):
    import numpy as np

    from geoviz_well_seismic_3d import InMemoryVolumeAccess
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )
    from paleo_workbench.viz import joint_host as host_mod

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    project = ProjectDocument.new("slice-stack")
    project.joint_analysis = JointAnalysisState(
        orthogonal_inline_index=1,
        orthogonal_crossline_index=2,
        time_slices=[
            JointTimeSliceState(time_ms=40.0),
            JointTimeSliceState(time_ms=160.0, visible=False),
        ],
        active_time_slice_ms=160.0,
        time_slice_opacity=65,
    )
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page._joint_host.scene.set_survey_from_corners(
        (0, 0, 0.0, 0.0),
        (0, 4, 40.0, 0.0),
        (4, 4, 40.0, 40.0),
        n_samples=101,
        dt_ms=2.0,
    )
    page._joint_host.scene.set_volume_access(
        InMemoryVolumeAccess(np.zeros((5, 7, 11), dtype=np.float32))
    )
    page._refresh_joint_slice_card()

    assert page._joint_slice_card_btn.isChecked()
    assert not page._joint_slice_card.isHidden()
    assert (
        page._joint_inline_slice.value(),
        page._joint_crossline_slice.value(),
    ) == (1, 2)
    assert page._joint_slice_card.maximumHeight() == 52
    assert page._joint_slice_card.sizeHint().height() <= 52
    assert page._joint_time_selector.count() == 2
    assert [
        page._joint_time_selector.itemData(index)
        for index in range(page._joint_time_selector.count())
    ] == [40.0, 160.0]
    assert page._joint_time_selector.currentData() == 160.0
    assert page._joint_active_time_editor.value() == 160.0
    assert not page._joint_active_time_visible.isChecked()
    assert page._joint_time_opacity.value() == 65

    page._joint_domain.setCurrentText("Depth")
    assert not page._joint_time_selector.isEnabled()

    state = page.collect_joint_analysis_state()
    assert (
        state.orthogonal_inline_index,
        state.orthogonal_crossline_index,
        [(item.time_ms, item.visible) for item in state.time_slices],
        state.active_time_slice_ms,
        state.time_slice_opacity,
    ) == (
        1,
        2,
        [(40.0, True), (160.0, False)],
        160.0,
        65,
    )


def test_orthogonal_slice_card_adds_and_activates_snapped_time(
    qtbot, tmp_path, monkeypatch
):
    import numpy as np

    from geoviz_well_seismic_3d import InMemoryVolumeAccess
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )
    from paleo_workbench.viz import joint_host as host_mod

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.set_project(ProjectDocument.new("slice-add"))
    page._joint_host.scene.set_survey_from_corners(
        (0, 0, 0.0, 0.0),
        (0, 4, 40.0, 0.0),
        (4, 4, 40.0, 40.0),
        n_samples=101,
        dt_ms=2.0,
    )
    page._joint_host.scene.set_volume_access(
        InMemoryVolumeAccess(np.zeros((5, 7, 11), dtype=np.float32))
    )
    page._refresh_joint_slice_card()

    page._joint_new_time.setValue(147.0)
    page._joint_add_time_slice.click()

    assert [
        item.time_ms
        for item in page._joint_host.scene.orthogonal_slice_state.time_slices
    ] == [100.0, 140.0]
    assert (
        page._joint_host.scene.orthogonal_slice_state.active_time_ms
        == 140.0
    )
    assert page._joint_time_selector.count() == 2
    assert page._joint_time_selector.currentData() == 140.0

    page._joint_new_time.setValue(141.0)
    page._joint_add_time_slice.click()
    assert page._joint_time_selector.count() == 2
    assert "已有" in page._joint_status.text()


def test_geomodel_restores_known_well_visibility_and_drops_stale_ids(
    qtbot, tmp_path, monkeypatch
):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("visibility")
    project.joint_analysis = JointAnalysisState(
        well_visibility={"source:a1": False, "REMOVED": False}
    )
    page.set_project(project)
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")),
            WellHead("NEW", 10, 10, 10, 10, 100, id=JointWellId("source:new")),
        ]
    )

    page._joint_host.scene_updated.emit()

    assert (
        [(well.id, well.visible) for well in page._joint_host.scene.well_presentations()],
        page.collect_joint_analysis_state().well_visibility,
    ) == (
        [("source:a1", False), ("source:new", True)],
        {"source:a1": False, "source:new": True},
    )


def test_geomodel_migrates_legacy_all_wells_hidden_state(qtbot, tmp_path, monkeypatch):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("legacy-visibility")
    project.joint_analysis = JointAnalysisState(
        tree_checks={"联合井轨迹 (geoviz)": False}
    )
    page.set_project(project)
    page._apply_joint_tree_checks_from_project()
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")),
            WellHead("B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")),
        ]
    )

    page._joint_host.scene_updated.emit()

    assert [
        well.visible for well in page._joint_host.scene.well_presentations()
    ] == [False, False]


def test_fill_joint_combos_preserves_saved_fence_pair(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
    from paleo_workbench.project.models import JointAnalysisState, ProjectDocument

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    doc = ProjectDocument.new("fence-pair")
    doc.joint_analysis = JointAnalysisState(active_fence_wells=["W2", "W0"])
    page.set_project(doc)

    # Simulate host well list order different from saved pair
    page._joint_host.well_names = lambda: ["W0", "W1", "W2"]  # type: ignore[method-assign]
    page._fill_joint_well_combos()
    assert page._joint_well_a.currentText() == "W2"
    assert page._joint_well_b.currentText() == "W0"
    state = page.collect_joint_analysis_state()
    assert state.active_fence_wells == ["W2", "W0"]


def test_collect_path_hints_includes_td_tops(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
    from paleo_workbench.project.models import ProjectDocument

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.set_project(ProjectDocument.new("hints"))
    td = tmp_path / "td"
    td.mkdir()
    tops = tmp_path / "tops.dat"
    tops.write_text("x")
    page._joint_host._paths = JointAssetPaths(
        segy=tmp_path / "a.sgy",
        well_head=tmp_path / "w.dat",
        td_dir=td,
        tops=tops,
        horizons=[tmp_path / "h.dat"],
    )
    (tmp_path / "a.sgy").write_bytes(b"x")
    (tmp_path / "w.dat").write_text("x")
    (tmp_path / "h.dat").write_text("x")
    state = page.collect_joint_analysis_state()
    assert "td_dir" in state.path_hints
    assert "tops" in state.path_hints
    assert "horizons" in state.path_hints


def test_project_controller_flushes_joint_on_save(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.viz.joint_well_identity import WellIdentityRegistry

    win = PaleoWorkbenchWindow()
    qtbot.addWidget(win)
    doc = ProjectDocument.new("save-test")
    win.project = doc
    win.project_path = tmp_path / "save-test.json"
    page = win.app_shell.geomodel_page
    doc.joint_analysis.well_identity_asset_id = "res:wells"
    doc.joint_analysis.well_identity_map = {
        "stale:a": "source:a",
        "stale:removed": "source:removed",
    }
    page.set_project(doc)
    page._joint_host._well_identity_registry = WellIdentityRegistry(
        asset_id="res:wells",
        entries={"current:a": "source:a"},
    )
    page._joint_loaded_once = True  # simulate visited 三维建模 hybrid
    page._joint_domain.setCurrentText("Depth")
    # Avoid mapping topology flush issues
    monkeypatch.setattr(win, "_flush_mapping_draft", lambda: True)
    path = win.project_controller.save_project()
    assert path is not None
    assert win.project.joint_analysis.vertical_domain == "Depth"
    assert win.project.joint_analysis.well_identity_asset_id == "res:wells"
    assert win.project.joint_analysis.well_identity_map == {
        "current:a": "source:a"
    }


def test_project_controller_skips_joint_flush_until_page_loaded(qtbot, tmp_path, monkeypatch):
    """Saving from another page must not clobber saved joint domain with UI defaults."""
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.project.models import JointAnalysisState, ProjectDocument

    win = PaleoWorkbenchWindow()
    qtbot.addWidget(win)
    doc = ProjectDocument.new("preserve-joint")
    doc.joint_analysis = JointAnalysisState(
        vertical_domain="Depth",
        active_fence_wells=["A1", "A2"],
        tree_checks={"地震预览体 (geoviz)": False},
    )
    win.project = doc
    win.project_path = tmp_path / "preserve-joint.json"
    page = win.app_shell.geomodel_page
    page.set_project(doc)
    assert page._joint_loaded_once is False
    # Pristine domain combo is Time — must not overwrite project
    assert page._joint_domain.currentText() == "Time"
    monkeypatch.setattr(win, "_flush_mapping_draft", lambda: True)
    path = win.project_controller.save_project()
    assert path is not None
    assert win.project.joint_analysis.vertical_domain == "Depth"
    assert win.project.joint_analysis.active_fence_wells == ["A1", "A2"]
    assert win.project.joint_analysis.tree_checks.get("地震预览体 (geoviz)") is False
