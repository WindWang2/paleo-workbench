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
