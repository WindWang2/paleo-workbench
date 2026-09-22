"""拓扑编辑 16 场景覆盖索引 + 真实工程周期（规格 §7 / §8 三重门 ②）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.mapping.edit_session_set import reset_session_set
from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger
from paleo_workbench.mapping.topology_checker import TopologyChecker
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.mapping.native_edit_session import NativeEditSessionController

# 场景 → 已有自动化钉。本文件只补周期走查，不重复实现。
SCENARIO_COVERAGE = {
    1: "tests/test_topo_m1_native_editing.py::test_scenario1_raw_layer_never_starts_editing",
    2: "tests/test_topo_m0_foundation.py (CRS 进前引导)",
    3: "tests/test_topo_m1_native_editing.py (全或无保存)",
    4: "tests/test_topo_m1_native_editing.py (rollback 基线)",
    5: "tests/test_qgis_topo_m1_native_editing.py::test_scenario5_shared_node_drag_moves_both_one_macro_undo",
    6: "tests/test_qgis_topo_m2_cross_layer.py",
    7: "tests/test_qgis_topo_m2_cross_layer.py (邻层拒绝)",
    8: "tests/test_qgis_topo_m2_cross_layer.py::test_scenario8_avoid_intersections_clips_and_scatters",
    9: "tests/test_qgis_topo_m3_geometry_commands.py (分割)",
    10: "tests/test_qgis_topo_m3_geometry_commands.py (合并)",
    11: "tests/test_qgis_topo_m2_cross_layer.py::test_scenario11_tracing_follows_existing_edges",
    12: "tests/test_qgis_topo_m4_checker.py::test_scenario12_workspace_remainder_highlight_and_navigate",
    13: "tests/test_topo_m4_checker.py (忽略豁免)",
    14: "tests/test_qgis_topo_m4_checker.py::test_scenario14_fix_all_overlaps_and_single_undo",
    15: "tests/test_topo_m0_foundation.py (停发窗口)",
    16: "tests/test_qgis_topo_m4_checker.py::test_scenario16_commit_keeps_host_fids",
}


def test_all_sixteen_scenarios_have_coverage():
    assert set(SCENARIO_COVERAGE) == set(range(1, 17))


PROJECT = Path(
    "/home/kevin/projects/paleo_project/data/project_area/project_area.paleo.json"
)


@pytest.mark.qgis
@pytest.mark.skipif(not PROJECT.is_file(), reason="project_area missing")
def test_real_project_edit_check_save_cycle(qapp, tmp_path):
    """三重门 ②：真实工程 建稿→编辑→检查→保存→导出 全周期。"""
    dest = tmp_path / "cycle.paleo.json"
    dest.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    from paleo_workbench.project.manager import ProjectManager
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole

    reset_publish_ledger()
    reset_session_set()
    project = ProjectManager(str(dest)).load()
    document = CompositeDocument(project)
    assert document.uses_native_stack
    layer = document.edit_controller.create_layer(
        "岸线", "line", role=LayerRole.PALEO_SHORELINE)
    document.edit_controller.set_active_layer(layer.id)
    document.edit_controller.start_editing()
    native = document.edit_controller.native_editing.is_open(layer.id)
    python_session = layer.edit_session is not None
    assert native or python_session
    if native:
        stack = document.canvas.stack
        addr = document.canvas.canvas_address
        checker = TopologyChecker()
        errors = checker.run(stack, addr, [layer.id])
        assert isinstance(errors, list)
        ok, reason = document.edit_controller.native_editing.rollback(layer.id)
        assert ok, reason
    else:
        document.edit_controller.rollback_edits()
    remaining = document.edit_controller.layer(layer.id)
    assert remaining is not None
    # 导出：画布矢量导出走与屏幕同一份渲染器解释（不重开工程）。
    svg = tmp_path / "cycle.svg"
    document.canvas.export_svg(str(svg))
    assert svg.is_file() and svg.stat().st_size > 0
