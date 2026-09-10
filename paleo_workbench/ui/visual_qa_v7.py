"""V7 视觉 QA 状态：工具可用性/树装饰/任务取消/溢出/Inspector 的扩展。

沿用 V6 模式（``visual_qa_v6`` 的姊妹篇，非替代）：

* **8 个新捕获状态**（``V7_STATES``）：RAW 阻断（禁用原因可见）、
  phase1 编辑会话、phase2 约束线主捕获、phase2 因子栅格（矢量工具禁
  而查看工具可用）、图层树状态装饰、任务取消中、窄画布工具条溢出、
  单因素 Inspector。
* **语义检查**（``run_state_checks``）：widget 级不变量；harness 内非
  门禁（D8 政策），门禁断言在 ``tests/test_visual_qa_v7.py``。
* 全部离屏可构造：合成工程、无 QGIS 桥（composite 回退画布是本套件
  环境的诚实现实）。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, QTimer

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.ui.visual_qa_v6 import CheckResult, _check, _settle

V7_STATES: tuple[str, ...] = (
    "phase1_raw_blocked",
    "phase1_editing_session",
    "phase2_constraint_line",
    "phase2_factor_raster",
    "layer_tree_decorations",
    "task_cancelling",
    "toolbar_overflow_narrow",
    "inspector_factor",
)


def _workstation(window):
    return window.app_shell.workstation


def _add_layer(window, kind: str, role: LayerRole, name: str = "", **extra):
    composite = _workstation(window).composite
    layer = composite.edit_controller.create_layer(name or role.label, kind)
    composite.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=role, **extra
    ))
    composite.edit_controller.set_active_layer(str(layer.id))
    composite._sync_action_state()
    return layer


# -- 驱动函数 ------------------------------------------------------------------


def drive_phase1_raw_blocked(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value)
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_SOURCE,
                       "初始沉积相（RAW）")
    ws.composite.layer_manager.select_layer(str(layer.id))
    _settle(200)


def drive_phase1_editing_session(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value)
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT,
                       "沉积相解释草稿")
    ws.composite._on_command_requested("toggle_editing")
    from paleo_workbench.mapping.vector_layer import VectorFeature

    session = getattr(layer, "edit_session", None)
    if session is not None:
        session.add_feature(
            VectorFeature(
                "draft_1",
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
                    ],
                },
                {"name": "相带1"},
            )
        )
        ws.composite._sync_action_state()
    _settle(200)


def drive_phase2_constraint_line(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.composite.stage_controller.set_stage(
        MappingStage.CONSTRAINT_FACTOR.value)
    layer = _add_layer(window, "line", LayerRole.PROVENANCE_LINE, "物源线")
    ws.composite._on_command_requested("toggle_editing")
    ws.composite.layer_manager.select_layer(str(layer.id))
    _settle(200)


def drive_phase2_factor_raster(window) -> None:
    ws = _workstation(window)
    ws.composite.stage_controller.set_stage(
        MappingStage.CONSTRAINT_FACTOR.value)
    layer = _add_layer(window, "polygon", LayerRole.FACTOR_GRID,
                       "厚度因子栅格", factor_task_id="factor-qa-1")
    ws.composite.layer_manager.select_layer(str(layer.id))
    _settle(200)


def drive_layer_tree_decorations(window) -> None:
    ws = _workstation(window)
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT,
                       "冻结成果层")
    ws.composite.stage_controller.state.set_maturity(
        f"phase1_draft:{layer.id}", "frozen")
    ws.composite._sync_composition_now()
    ws.composite._sync_action_state()
    ws.composite_layer_dock.show()
    ws.composite_layer_dock.raise_()
    _settle(200)


def drive_task_cancelling(window) -> None:
    """提交可中断长任务并请求取消 → 任务中心呈「取消中」。"""
    from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler

    def _long_task(context):
        # 不可中断段（plain sleep）+ 段间取消点：取消请求后任务保持
        # RUNNING+cancel_requested 一段时间——「取消中」呈现窗口。
        for _ in range(50):
            time.sleep(2.0)
            context.check_cancelled()

    scheduler = get_scheduler()
    handle = scheduler.submit(TaskSpec(
        title="视觉 QA 长任务（取消中演示）",
        callable=_long_task,
    ))
    _settle(300)
    scheduler.cancel(handle.task_id)
    ws = _workstation(window)
    ws.task_dock.show()
    ws.task_dock.raise_()
    _settle(150)


def drive_toolbar_overflow_narrow(window) -> None:
    """溢出态驱动：直接以窄预算触发（不 resize 主窗——harness 的尺寸
    守卫要求实际窗口 == 请求尺寸；窄画布状态由预算参数表达）。"""
    composite = window.app_shell.workstation.composite
    composite._update_toolbar_overflow(700)
    _settle(120)


def drive_inspector_factor(window) -> None:
    ws = _workstation(window)
    ws.composite.stage_controller.set_stage(
        MappingStage.CONSTRAINT_FACTOR.value)
    layer = _add_layer(window, "line", LayerRole.FACTOR_CONTOUR,
                       "厚度等值线", factor_task_id="factor-qa-2")
    # 合成 fixture 里角色赋值与选择信号存在固有竞态（生产流程中角色在
    # 用户选择前已落位）；settle 后显式驱动 Inspector 槽保证最终态。
    _settle(400)
    window.app_shell.workstation._inspect_layer_selection(str(layer.id))
    ws.inspector_dock.show()
    ws.inspector_dock.raise_()
    _settle(150)


def v7_shot_table(make_project: Callable):
    """(状态 → (工程工厂, 驱动)) 表——与 v6_shot_table 同注册形态。"""
    return {
        "phase1_raw_blocked": (make_project, drive_phase1_raw_blocked),
        "phase1_editing_session": (make_project, drive_phase1_editing_session),
        "phase2_constraint_line": (make_project, drive_phase2_constraint_line),
        "phase2_factor_raster": (make_project, drive_phase2_factor_raster),
        "layer_tree_decorations": (make_project, drive_layer_tree_decorations),
        "task_cancelling": (make_project, drive_task_cancelling),
        "toolbar_overflow_narrow": (make_project, drive_toolbar_overflow_narrow),
        "inspector_factor": (make_project, drive_inspector_factor),
    }


# -- 语义检查（非门禁；门禁在 tests/test_visual_qa_v7.py） ----------------------


def _actions(window):
    return _workstation(window).composite.action_controller.actions


def _phase1_raw_blocked_checks(window) -> list[CheckResult]:
    actions = _actions(window)
    toggle = actions["toggle_editing"]
    availability = _workstation(window).composite.tool_availability()
    # 查看类工具可能被窄画布溢出收纳（Qt 对隐藏 QAction 自动置
    # disabled）——使能断言以统一求值结果为准。
    return [
        _check("raw_toggle_editing_disabled", not toggle.isEnabled()),
        _check("raw_reason_in_status_tip", "RAW" in toggle.statusTip(),
               toggle.statusTip()),
        _check("raw_capture_disabled", not actions["add_polygon"].isEnabled()),
        _check("raw_view_tools_enabled",
               availability["layer_properties"].enabled),
    ]


def _phase1_editing_checks(window) -> list[CheckResult]:
    actions = _actions(window)
    ws = _workstation(window)
    return [
        _check("editing_toggle_checked", actions["toggle_editing"].isChecked()),
        _check("editing_save_enabled", actions["save_edits"].isEnabled()),
        _check("editing_capture_enabled", actions["add_polygon"].isEnabled()),
        _check("editing_tree_shows_session",
               any(t in _tree_status_texts(ws) for t in ("编辑中", "未保存"))),
    ]


def _phase2_constraint_line_checks(window) -> list[CheckResult]:
    actions = _actions(window)
    return [
        _check("line_add_line_enabled", actions["add_line"].isEnabled()),
        _check("line_add_polygon_disabled",
               not actions["add_polygon"].isEnabled()),
        _check("line_kind_reason",
               "线" in actions["add_polygon"].statusTip()
               or "面" in actions["add_polygon"].statusTip(),
               actions["add_polygon"].statusTip()),
    ]


def _phase2_factor_raster_checks(window) -> list[CheckResult]:
    actions = _actions(window)
    availability = _workstation(window).composite.tool_availability()
    return [
        _check("factor_vector_edit_disabled",
               not actions["toggle_editing"].isEnabled()),
        _check("factor_raw_reason",
               "RAW" in actions["toggle_editing"].statusTip()),
        _check("factor_view_tools_enabled",
               availability["layer_properties"].enabled
               and availability["symbology"].enabled
               and availability["layer_export"].enabled),
    ]


def _tree_status_texts(ws) -> str:
    tree = ws.composite.layer_manager.tree
    from PySide6.QtCore import Qt

    parts = []
    for row in range(tree.topLevelItemCount()):
        parts.append(tree.topLevelItem(row).text(1))
    return " | ".join(parts)


def _layer_tree_decoration_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    texts = _tree_status_texts(ws)
    return [
        _check("tree_status_column_has_frozen", "冻结" in texts, texts),
        _check("tree_status_column_has_glyph", "❄" in texts, texts),
    ]


def _task_cancelling_checks(window) -> list[CheckResult]:
    from paleo_workbench.runtime.task_scheduler import TaskState, get_scheduler

    handles = get_scheduler().statuses()
    cancelling = [
        h for h in handles
        # V9 状态词汇：取消中 = CANCELLING（显式态）或 RUNNING+cancel_requested
        #（claim 窗口竞态，态尚未落定）——两者都是诚实的"取消等待期"呈现。
        if h.cancel_requested and h.state in (
            TaskState.RUNNING, TaskState.CANCELLING)
    ]
    return [
        _check("task_cancel_pending", bool(cancelling),
               f"{len(handles)} tasks"),
        _check("task_dock_visible",
               not _workstation(window).task_dock.isHidden()),
    ]


def _toolbar_overflow_checks(window) -> list[CheckResult]:
    composite = _workstation(window).composite
    actions = composite.action_controller.actions
    return [
        _check("overflow_hidden_set_nonempty",
               bool(composite._toolbar_overflow_hidden)),
        _check("overflow_menu_entries",
               len(composite._overflow_menu.actions()) >= 1),
        _check("overflow_core_visible", actions["add_polygon"].isVisible()
               and actions["toggle_editing"].isVisible()),
    ]


def _inspector_factor_checks(window) -> list[CheckResult]:
    header = _workstation(window).inspector.header.text()
    return [
        _check("inspector_shows_factor_section", "单因素" in header, header),
    ]


_CHECK_TABLE: dict[str, Callable[[object], list[CheckResult]]] = {
    "phase1_raw_blocked": _phase1_raw_blocked_checks,
    "phase1_editing_session": _phase1_editing_checks,
    "phase2_constraint_line": _phase2_constraint_line_checks,
    "phase2_factor_raster": _phase2_factor_raster_checks,
    "layer_tree_decorations": _layer_tree_decoration_checks,
    "task_cancelling": _task_cancelling_checks,
    "toolbar_overflow_narrow": _toolbar_overflow_checks,
    "inspector_factor": _inspector_factor_checks,
}


def run_state_checks(state: str, window) -> list[CheckResult]:
    handler = _CHECK_TABLE.get(state)
    if handler is None:
        return []
    return handler(window)
