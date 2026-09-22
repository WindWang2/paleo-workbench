"""V6 §4：编图工具条按 StageToolProfile 过滤数字化/编辑动作。

综合编修工具条此前静态展示全部动作（audit B-P1-2：StageToolProfile
零消费者）。过滤规则：

* 受治理全集 = 所有阶段 profile ``edit_actions`` 的并集；
* 不在并集内的动作（如 add_point）与基础导航/识别/选择动作不受阶段过滤；
* 过滤只改可见性（QGIS 惯例：工具条隐藏而非禁用）；palette 中同名命令
  走 disabled-with-reason 路径。
"""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def test_stage_tool_profile_filters_toolbar_digitize_actions(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    actions = document.action_controller.actions

    # 阶段1（相带标定）：无 add_line（线状约束是阶段2的入口）。
    document.apply_stage_tool_profile("phase1")
    assert actions["add_line"].isVisible() is False
    assert actions["add_polygon"].isVisible() is True

    # 阶段2（约束/单因素）：物源线等线状约束数字化开放。
    document.apply_stage_tool_profile("phase2")
    assert actions["add_line"].isVisible() is True

    # add_point 不在任何阶段 profile 的 edit_actions 并集内 → 不受阶段治理。
    assert actions["add_point"].isVisible() is True

    # 基础导航/识别永不隐藏。
    assert actions["pan"].isVisible() is True
    assert actions["identify"].isVisible() is True

    # 编辑会话动作在所有阶段 profile 中都在 → 永不因阶段隐藏。
    assert actions["undo"].isVisible() is True
    assert actions["delete_selected"].isVisible() is True


def test_stage_tool_profile_ignores_unknown_stage(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    document.apply_stage_tool_profile("phase2")
    assert document.action_controller.actions["add_line"].isVisible() is True
    # 未知阶段：保持现状（宽容但不静默——阶段条已校验过合法值）。
    document.apply_stage_tool_profile("nope")
    assert document.action_controller.actions["add_line"].isVisible() is True


# --- V6 §5: 活动编辑目标状态 seam（UIContext/状态条/检查器共用） ---------------


def test_active_editing_target_status_no_target(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    status = document.active_editing_target_status()
    assert status["active_layer_id"] is None
    assert status["editable"] is False
    assert status["block_reason"]  # 必须给出原因，不许静默


def test_active_editing_target_status_editable_layer(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = document.edit_controller.create_layer("用户草稿", "polygon")
    document.edit_controller.set_active_layer(layer.id)
    status = document.active_editing_target_status()
    assert status["active_layer_id"] == layer.id
    assert status["editable"] is True
    assert status["block_reason"] == ""


# --- V6 §4: 阶段切换驱动工具条过滤（shell 接线） -------------------------------


def test_stage_switch_updates_toolbar_via_shell_wiring(qtbot, tmp_path):
    from PySide6.QtWidgets import QStackedWidget

    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    composite = frame.composite
    # 初始阶段1（构造即应用 profile）：add_line 隐藏。
    assert composite.action_controller.actions["add_line"].isVisible() is False
    # 切到阶段2：接线层必须把 profile 应用到工具条。
    frame.stage_bar.stage_requested.emit("phase2")
    assert composite.action_controller.actions["add_line"].isVisible() is True
