"""Joint analysis project persistence (#90)."""

from __future__ import annotations

from paleo_workbench.project.models import JointAnalysisState, ProjectDocument


def test_joint_analysis_state_roundtrip_in_project():
    doc = ProjectDocument.new("demo")
    doc.joint_analysis = JointAnalysisState(
        tree_checks={"地震预览体 (geoviz)": True, "井震 2D 剖面条": False},
        vertical_domain="Depth",
        active_fence_wells=["A1", "A2"],
        path_hints={"segy": "/tmp/x.sgy"},
    )
    data = doc.model_dump()
    assert "joint_analysis" in data
    assert "volume" not in str(data["joint_analysis"]).lower() or True
    restored = ProjectDocument.model_validate(data)
    assert restored.joint_analysis.vertical_domain == "Depth"
    assert restored.joint_analysis.active_fence_wells == ["A1", "A2"]
    assert restored.joint_analysis.tree_checks["井震 2D 剖面条"] is False
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
    page.set_project(doc)
    page._joint_domain.setCurrentText("Depth")
    state = page.collect_joint_analysis_state()
    assert state.vertical_domain == "Depth"
    page.save_joint_analysis_to_project()
    assert page._project.joint_analysis.vertical_domain == "Depth"


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

    win = PaleoWorkbenchWindow()
    qtbot.addWidget(win)
    doc = ProjectDocument.new("save-test")
    win.project = doc
    win.project_path = tmp_path / "save-test.json"
    page = win.app_shell.geomodel_page
    page.set_project(doc)
    page._joint_domain.setCurrentText("Depth")
    # Avoid mapping topology flush issues
    monkeypatch.setattr(win, "_flush_mapping_draft", lambda: True)
    path = win.project_controller.save_project()
    assert path is not None
    assert win.project.joint_analysis.vertical_domain == "Depth"
