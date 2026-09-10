"""V10 视觉 QA 状态：专业 QGIS Authoring UX 的呈现一致性（状态条/工具面/菜单）。

沿用 V6–V9 模式（续篇，非替代）：每状态 = 驱动函数（构造业务事实）+
语义检查（``run_state_checks``，呈现与 canonical evaluator 结论一致）。
门禁断言在 ``tests/test_visual_qa_v10.py``；截图 harness 经
``v10_shot_table`` 挂载（pixel diff 非门禁，V5 D8 政策）。

V10 状态覆盖 Goal §28 的关键面：

* RAW / 冻结 / 缺失图层的只读呈现（状态 chip + 编辑禁用原因同源）；
* 捕获工具 preferred 提示 + tooltip 当前编辑目标（§13）；
* 捕捉配置详情与拓扑错误 chip（§15）；
* CRS 未声明 / 不一致警示（§16）；
* 编辑会话 dirty chip（§14）；
* 画布右键菜单与工具条零漂移（§20）；
* 1366 紧凑宽度下工具面身份保全（§24）。
"""
from __future__ import annotations

from collections.abc import Callable

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.ui.visual_qa_v6 import CheckResult, _check, _settle
from paleo_workbench.ui.visual_qa_v7 import _add_layer, _workstation

V10_STATES: tuple[str, ...] = (
    "raw_layer_readonly_surface",
    "capture_preferred_line_role",
    "editing_dirty_chip",
    "snapping_detail_surface",
    "topology_error_chip",
    "crs_undeclared_surface",
    "crs_mismatch_warning",
    "frozen_layer_surface",
    "canvas_context_menu_surface",
    "compact_1366_toolbar_identity",
)


# -- 驱动函数 ------------------------------------------------------------------


def _enter_stage(window, stage: MappingStage) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.composite.stage_controller.set_stage(stage.value)


def drive_raw_layer_readonly_surface(window) -> None:
    """阶段① + RAW 相图选中：编辑全线禁用 + 状态 chip RAW · 只读。"""
    _enter_stage(window, MappingStage.FACIES_CALIBRATION)
    _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_SOURCE, "初始沉积相（RAW）")
    _settle(150)


def drive_capture_preferred_line_role(window) -> None:
    """阶段② + 相带边界线层 + 会话中：add_line 为 preferred 且 tooltip 带编辑目标。"""
    _enter_stage(window, MappingStage.CONSTRAINT_FACTOR)
    _add_layer(window, "line", LayerRole.FACIES_BOUNDARY, "相带边界")
    _workstation(window).composite._on_command_requested("toggle_editing")
    _settle(150)


def drive_editing_dirty_chip(window) -> None:
    """编辑会话含未保存修改：状态 chip「Edit … ● 未保存」。"""
    _enter_stage(window, MappingStage.FACIES_CALIBRATION)
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT, "解释草稿")
    _workstation(window).composite._on_command_requested("toggle_editing")
    from paleo_workbench.mapping.vector_layer import VectorFeature

    session = getattr(layer, "edit_session", None)
    if session is not None:
        with session.edit_source("visual_qa"):
            session.add_feature(VectorFeature(
                "dirty_1",
                {"type": "Polygon",
                 "coordinates": [[[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]]},
                {"name": "相带A"},
            ))
    _workstation(window).composite._sync_action_state()
    _settle(150)


def drive_snapping_detail_surface(window) -> None:
    """捕捉开启 + 角色推荐应用：状态条开/关读数 + tooltip 配置详情。"""
    _enter_stage(window, MappingStage.CONSTRAINT_FACTOR)
    composite = _workstation(window).composite
    _add_layer(window, "line", LayerRole.FACIES_BOUNDARY, "相带边界")
    composite._on_command_requested("snapping")
    composite._sync_action_state()
    _settle(150)


def drive_topology_error_chip(window) -> None:
    """会话拓扑错误计数 > 0：状态条问题 chip 可见且计数正确。"""
    _enter_stage(window, MappingStage.FACIES_CALIBRATION)
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT, "草稿")
    composite = _workstation(window).composite
    composite._on_command_requested("toggle_editing")
    composite._on_command_requested("topology")  # 开启拓扑（计数的语义前提）
    composite.edit_controller._topology.record_validation(layer, 3)
    composite._sync_action_state()
    _settle(150)


def drive_crs_undeclared_surface(window) -> None:
    """工程 CRS 未声明：状态条诚实「CRS: 未声明」（不伪造 4326）。"""
    _enter_stage(window, MappingStage.FACIES_CALIBRATION)
    composite = _workstation(window).composite
    composite.edit_controller.project_crs = ""
    composite._sync_action_state()
    _settle(150)


def drive_crs_mismatch_warning(window) -> None:
    """图层 CRS 与工程 CRS 可证不一致：状态条 ⚠ 警示。"""
    _enter_stage(window, MappingStage.FACIES_CALIBRATION)
    composite = _workstation(window).composite
    layer = _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT, "草稿")
    composite.edit_controller.project_crs = "EPSG:4490"
    object.__setattr__(layer, "crs", "EPSG:32650") if hasattr(layer, "__dataclass_fields__") else setattr(layer, "crs", "EPSG:32650")
    composite._sync_action_state()
    _settle(150)


def drive_frozen_layer_surface(window) -> None:
    """冻结成果选中：编辑禁用 + chip「已冻结」。"""
    _enter_stage(window, MappingStage.INTEGRATED_COMPILATION)
    layer = _add_layer(window, "polygon", LayerRole.INTEGRATED_FACIES, "综合相图")
    _workstation(window).composite.stage_controller.state.set_maturity(
        f"integrated:{layer.id}", "frozen")
    _workstation(window).composite._sync_composition_now()
    _workstation(window).composite._sync_action_state()
    _settle(150)


def drive_canvas_context_menu_surface(window) -> None:
    """画布右键菜单：组合已求值 QAction（不 exec；检查项与工具条一致）。"""
    _enter_stage(window, MappingStage.CONSTRAINT_FACTOR)
    _add_layer(window, "line", LayerRole.FACIES_BOUNDARY, "相带边界")
    window._v10_canvas_menu = _workstation(window).composite._build_canvas_menu()
    _settle(120)


def drive_compact_1366_toolbar_identity(window) -> None:
    """1366×768：工具条溢出收纳后动作身份保全（QAction 仍在、可用性结论不漂移）。"""
    window.show()
    _settle(250)
    window.resize(1366, 768)
    _settle(400)
    _enter_stage(window, MappingStage.CONSTRAINT_FACTOR)
    _add_layer(window, "line", LayerRole.FACIES_BOUNDARY, "相带边界")
    _settle(200)


def v10_shot_table(make_project: Callable, *, no_project_factory: Callable | None = None):
    """(状态 → (工程工厂, 驱动)) 表——与 v6–v9 注册形态一致。"""
    return {state: (make_project, drive) for state, drive in (
        ("raw_layer_readonly_surface", drive_raw_layer_readonly_surface),
        ("capture_preferred_line_role", drive_capture_preferred_line_role),
        ("editing_dirty_chip", drive_editing_dirty_chip),
        ("snapping_detail_surface", drive_snapping_detail_surface),
        ("topology_error_chip", drive_topology_error_chip),
        ("crs_undeclared_surface", drive_crs_undeclared_surface),
        ("crs_mismatch_warning", drive_crs_mismatch_warning),
        ("frozen_layer_surface", drive_frozen_layer_surface),
        ("canvas_context_menu_surface", drive_canvas_context_menu_surface),
        ("compact_1366_toolbar_identity", drive_compact_1366_toolbar_identity),
    )}


# -- 语义检查（非门禁；门禁在 tests/test_visual_qa_v10.py） ----------------------


def _composite(window):
    return _workstation(window).composite


def _raw_surface_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    availability = composite.tool_availability()
    return [
        _check("raw_toggle_disabled",
               not availability["toggle_editing"].enabled),
        _check("raw_reason_from_gate",
               "RAW" in availability["toggle_editing"].disabled_reason,
               availability["toggle_editing"].disabled_reason),
        _check("raw_status_chip_text",
               composite.status_bar.edit.text() == "RAW · 只读",
               composite.status_bar.edit.text()),
        _check("raw_capture_disabled",
               not availability["add_polygon"].enabled),
        _check("raw_view_tools_enabled",
               availability["layer_properties"].enabled),
    ]


def _capture_preferred_checks(window) -> None:
    composite = _composite(window)
    availability = composite.tool_availability()
    action = composite.action_controller.actions["add_line"]
    button = composite._map_toolbar_top.widgetForAction(action)
    tooltip = action.toolTip()
    return [
        _check("line_role_add_line_preferred",
               availability["add_line"].enabled
               and availability["add_line"].preferred),
        _check("line_role_add_polygon_role_blocked",
               not availability["add_polygon"].enabled,
               availability["add_polygon"].disabled_reason),
        _check("preferred_button_property",
               bool(button and button.property("preferred")),
               str(getattr(button, "property", lambda *_: None)("preferred"))),
        _check("capture_tooltip_target_block",
               "当前编辑目标" in tooltip, tooltip[-120:]),
    ]


def _dirty_chip_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    chip = composite.status_bar.edit
    availability = composite.tool_availability()
    return [
        _check("dirty_chip_modified_text", "未保存" in chip.text(), chip.text()),
        _check("dirty_chip_not_color_only",
               "Edit" in chip.text() and "●" in chip.text(), chip.text()),
        _check("dirty_save_enabled", availability["save_edits"].enabled),
    ]


def _snapping_detail_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    bar = composite.status_bar
    availability = composite.tool_availability()
    return [
        _check("snapping_readout_on",
               bar.snapping.text() == "捕捉: 开", bar.snapping.text()),
        _check("snapping_tooltip_detail",
               "容差" in bar.snapping.toolTip(), bar.snapping.toolTip()[:120]),
        _check("snapping_evaluator_checked",
               availability["snapping"].enabled
               and availability["snapping"].checked),
        _check("snapping_tool_tooltip_config",
               "捕捉设置" in composite.action_controller.actions["snapping"].toolTip(),
               composite.action_controller.actions["snapping"].toolTip()[-120:]),
    ]


def _topology_error_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    chip = composite.status_bar.topology_issue
    availability = composite.tool_availability()
    return [
        _check("topology_chip_visible", not chip.isHidden()),
        _check("topology_chip_count",
               "3" in chip.text() and "拓扑" in chip.text(), chip.text()),
        _check("topology_chip_not_color_only", "⚠" in chip.text(), chip.text()),
        _check("topology_merge_blocked",
               not availability["merge"].enabled
               and "拓扑" in availability["merge"].disabled_reason,
               availability["merge"].disabled_reason),
    ]


def _crs_undeclared_checks(window) -> list[CheckResult]:
    bar = _composite(window).status_bar
    availability = _composite(window).tool_availability()
    return [
        _check("crs_honest_undeclared",
               bar.crs.text() == "CRS: 未声明", bar.crs.text()),
        _check("crs_topology_gated",
               not availability["topology"].enabled,
               availability["topology"].disabled_reason),
    ]


def _crs_mismatch_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    bar = composite.status_bar
    return [
        _check("crs_mismatch_warn_glyph",
               bar.crs.text().startswith("⚠"), bar.crs.text()),
        _check("crs_mismatch_tooltip_explains",
               "不一致" in bar.crs.toolTip(), bar.crs.toolTip()[:160]),
        _check("crs_mismatch_no_fake_crs",
               "4326" not in bar.crs.text().replace("EPSG:32650", ""),
               bar.crs.text()),
    ]


def _frozen_surface_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    availability = composite.tool_availability()
    return [
        _check("frozen_chip_text",
               composite.status_bar.edit.text() == "已冻结",
               composite.status_bar.edit.text()),
        _check("frozen_toggle_disabled",
               not availability["toggle_editing"].enabled),
        _check("frozen_reason_authoritative",
               "冻结" in availability["toggle_editing"].disabled_reason,
               availability["toggle_editing"].disabled_reason),
    ]


def _canvas_menu_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    menu = getattr(window, "_v10_canvas_menu", None)
    if menu is None:
        return [_check("canvas_menu_built", False, "menu missing")]
    texts = [action.text() for action in menu.actions() if action.text()]
    mapped = {
        action.objectName().split(":", 1)[1]: action
        for action in menu.actions()
        if action.objectName().startswith("MapAction:")
    }
    availability = composite.tool_availability()
    consistent = all(
        mapped[tool_id].isEnabled() == availability[tool_id].enabled
        for tool_id in mapped
    )
    return [
        _check("canvas_menu_has_view_group", any("全图" in t for t in texts)),
        _check("canvas_menu_has_capture_config", any("捕捉设置" in t for t in texts)),
        _check("canvas_menu_evaluator_consistent", consistent,
               str(sorted(mapped))),
        _check("canvas_menu_add_line_enabled",
               bool(mapped.get("add_line")) and mapped["add_line"].isEnabled()
               or "add_line" not in mapped),
    ]


def _compact_1366_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    actions = composite.action_controller.actions
    availability = composite.tool_availability()
    identity = all(tool_id in actions for tool_id in ("pan", "add_line", "save_edits"))
    # 溢出收纳是 Qt 呈现行为；动作身份/结论不得漂移。
    consistent = all(
        (not actions[tool_id].isVisible())
        or (actions[tool_id].isEnabled() == availability[tool_id].enabled)
        for tool_id in ("pan", "add_line", "toggle_editing", "snapping")
    )
    return [
        _check("compact_actions_identity_kept", identity),
        _check("compact_verdict_consistency", consistent),
        _check("compact_window_size",
               window.width() <= 1366 + 1, f"{window.width()}x{window.height()}"),
        _check("compact_canvas_present", composite.canvas.width() > 0),
    ]


def run_state_checks(state: str, window) -> list[CheckResult]:
    checks = {
        "raw_layer_readonly_surface": _raw_surface_checks,
        "capture_preferred_line_role": _capture_preferred_checks,
        "editing_dirty_chip": _dirty_chip_checks,
        "snapping_detail_surface": _snapping_detail_checks,
        "topology_error_chip": _topology_error_checks,
        "crs_undeclared_surface": _crs_undeclared_checks,
        "crs_mismatch_warning": _crs_mismatch_checks,
        "frozen_layer_surface": _frozen_surface_checks,
        "canvas_context_menu_surface": _canvas_menu_checks,
        "compact_1366_toolbar_identity": _compact_1366_checks,
    }
    runner = checks.get(state)
    return runner(window) if runner else []
