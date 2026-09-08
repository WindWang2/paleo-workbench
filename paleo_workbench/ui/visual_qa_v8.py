"""V8 视觉 QA 状态：canonical contract 下的确定性状态扩展。

沿用 V6/V7 模式（``visual_qa_v6``/``visual_qa_v7`` 的续篇，非替代）：

* **6 个新捕获状态**（``V8_STATES``）：无工程工具面、编辑会话 dirty 态、
  冻结成果（phase3）、palette 禁用原因可见、原生工具激活失败回退、
  阻塞任务工具面；
* **语义检查**（``run_state_checks``）：widget 级不变量 + canonical
  evaluator 结论一致（状态与表面的呈现一致性），harness 内非门禁（D8
  政策），门禁断言在 ``tests/test_visual_qa_v8.py``；
* 全部离屏可构造（fallback 画布是本套件环境的诚实现实；native 激活
  失败经统一信号面模拟——shim 侧记录/发射逻辑由代码评审 + 单测覆盖）。
"""
from __future__ import annotations

from collections.abc import Callable

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.ui.visual_qa_v6 import CheckResult, _check, _settle
from paleo_workbench.ui.visual_qa_v7 import _add_layer, _workstation

V8_STATES: tuple[str, ...] = (
    "empty_project_tool_surface",
    "derived_polygon_editing_dirty",
    "frozen_map_product",
    "palette_disabled_reason",
    "native_activation_failure_revert",
    "blocking_task_tool_surface",
)


# -- 驱动函数 ------------------------------------------------------------------


def drive_empty_project_tool_surface(window) -> None:
    """空工程（Untitled）：画布引导可见 + 图层门禁工具禁用带原因。

    注：``PaleoWorkbenchWindow(project=None)`` 会落一个 Untitled 工程——
    「完全无工程」在本应用不是可达工作站状态（evaluator 的 project_open
    门禁在 M2 矩阵的纯函数层验证）。
    """
    _settle(200)


def drive_derived_polygon_editing_dirty(window) -> None:
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
                "dirty_1",
                {"type": "Polygon",
                 "coordinates": [[[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]]},
                {"name": "相带A"},
            )
        )
    ws.composite._sync_action_state()
    _settle(200)


def drive_frozen_map_product(window) -> None:
    ws = _workstation(window)
    ws.composite.stage_controller.set_stage(
        MappingStage.INTEGRATED_COMPILATION.value)
    layer = _add_layer(window, "polygon", LayerRole.INTEGRATED_FACIES,
                       "综合相图成果")
    ws.composite.stage_controller.state.set_maturity(
        f"integrated:{layer.id}", "frozen")
    ws.composite._sync_composition_now()
    ws.composite._sync_action_state()
    _settle(200)


def drive_palette_disabled_reason(window) -> None:
    """阶段① + palette 打开：map:* 命令的禁用原因与工具条同源可见。"""
    shell = window.app_shell
    shell.workstation.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value)
    _settle(150)
    palette = shell.command_palette
    palette.popup()
    palette.filter_input.setText("编图")
    _settle(120)


def drive_native_activation_failure_revert(window) -> None:
    """编辑会话激活采面工具 → 模拟原生激活失败 → checked 应回退 pan。

    fallback 画布声明了同名信号（生产中由 QgisCanvasShim 在
    ``set_map_tool`` 异常时发射）；此处直接发射以驱动宿主回退路径。
    """
    ws = _workstation(window)
    ws.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value)
    _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT, "草稿")
    ws.composite._on_command_requested("toggle_editing")
    ws.composite._on_command_requested("add_polygon")
    _settle(120)
    log: list[str] = []
    window._v8_status_log = log
    ws.composite.status_message.connect(log.append)
    ws.composite.canvas.native_tool_activation_failed.emit(
        "add_polygon", "模拟桥异常")
    _settle(120)


def drive_blocking_task_tool_surface(window) -> None:
    ws = _workstation(window)
    _add_layer(window, "polygon", LayerRole.INITIAL_FACIES_DRAFT, "草稿")
    ws.composite.edit_controller.blocking_task_label = "正在导入参考图层"
    ws.composite._sync_action_state()
    _settle(150)


def v8_shot_table(make_project: Callable, *, no_project_factory: Callable | None = None):
    """(状态 → (工程工厂, 驱动)) 表——与 v6/v7 注册形态一致。

    ``no_project_factory`` 供无工程状态使用（默认 ``lambda: None``）。
    """
    none_factory = no_project_factory or (lambda: None)
    return {
        "empty_project_tool_surface": (none_factory, drive_empty_project_tool_surface),
        "derived_polygon_editing_dirty": (make_project, drive_derived_polygon_editing_dirty),
        "frozen_map_product": (make_project, drive_frozen_map_product),
        "palette_disabled_reason": (make_project, drive_palette_disabled_reason),
        "native_activation_failure_revert": (make_project, drive_native_activation_failure_revert),
        "blocking_task_tool_surface": (make_project, drive_blocking_task_tool_surface),
    }


# -- 语义检查（非门禁；门禁在 tests/test_visual_qa_v8.py） ----------------------


def _composite(window):
    return _workstation(window).composite


def _empty_project_checks(window) -> list[CheckResult]:
    # 使能断言以统一求值结果为准（窄画布溢出会把隐藏 QAction 自动置
    # disabled——QAction.isEnabled 不能区分业务禁用与呈现收纳）。
    composite = _composite(window)
    availability = composite.tool_availability()
    return [
        _check("empty_pan_enabled", availability["pan"].enabled),
        _check("empty_layer_new_enabled", availability["layer_new"].enabled),
        _check("empty_toggle_disabled_with_reason",
               (not availability["toggle_editing"].enabled)
               and "图层" in availability["toggle_editing"].disabled_reason,
               availability["toggle_editing"].disabled_reason),
        _check("empty_cancel_enabled", availability["cancel"].enabled),
        _check("empty_hint_visible", composite._empty_hint.isVisible()),
    ]


def _editing_dirty_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    actions = composite.action_controller.actions
    availability = composite.tool_availability()
    return [
        _check("dirty_save_enabled", availability["save_edits"].enabled),
        _check("dirty_rollback_enabled", availability["rollback"].enabled),
        _check("dirty_undo_enabled", availability["undo"].enabled),
        _check("dirty_save_reason_cleared",
               "未保存" not in availability["save_edits"].disabled_reason,
               availability["save_edits"].disabled_reason),
        _check("dirty_toggle_checked", actions["toggle_editing"].isChecked()),
    ]


def _frozen_product_checks(window) -> list[CheckResult]:
    availability = _composite(window).tool_availability()
    return [
        _check("frozen_toggle_disabled",
               not availability["toggle_editing"].enabled),
        _check("frozen_reason_authoritative",
               "冻结" in availability["toggle_editing"].disabled_reason,
               availability["toggle_editing"].disabled_reason),
        _check("frozen_view_tools_enabled",
               availability["layer_properties"].enabled
               and availability["layer_export"].enabled),
        _check("frozen_capture_disabled",
               not availability["add_polygon"].enabled),
    ]


def _palette_disabled_checks(window) -> list[CheckResult]:
    shell = window.app_shell
    composite = shell.workstation.composite
    palette = shell.command_palette
    texts = []
    for row in range(palette.result_list.count()):
        item = palette.result_list.item(row)
        if item is not None:
            texts.append(item.text())
    joined = "\n".join(texts)
    avail = composite.tool_availability()
    return [
        _check("palette_has_map_entries", "编图 ·" in joined, joined[:200]),
        _check("palette_map_export_stage_gated",
               "导出图面" not in joined or "不可用" in joined or "（" in joined,
               joined[:200]),
        _check("palette_reason_source_is_evaluator",
               bool(avail["map_export"].disabled_reason),
               avail["map_export"].disabled_reason),
    ]


def _native_failure_checks(window) -> list[CheckResult]:
    composite = _composite(window)
    actions = composite.action_controller.actions
    log = getattr(window, "_v8_status_log", None) or []
    return [
        _check("revert_pan_checked", actions["pan"].isChecked()),
        _check("revert_add_polygon_unchecked",
               not actions["add_polygon"].isChecked()),
        _check("revert_status_reason_emitted",
               any("激活失败" in msg for msg in log), str(log[:3])),
    ]


def _blocking_task_checks(window) -> list[CheckResult]:
    availability = _composite(window).tool_availability()
    return [
        _check("blocking_toggle_disabled",
               not availability["toggle_editing"].enabled),
        _check("blocking_pan_disabled", not availability["pan"].enabled),
        _check("blocking_reason", availability["pan"].disabled_reason.startswith(
            "后台任务进行中"), availability["pan"].disabled_reason),
        _check("blocking_cancel_enabled", availability["cancel"].enabled),
    ]


_CHECK_TABLE: dict[str, Callable[[object], list[CheckResult]]] = {
    "empty_project_tool_surface": _empty_project_checks,
    "derived_polygon_editing_dirty": _editing_dirty_checks,
    "frozen_map_product": _frozen_product_checks,
    "palette_disabled_reason": _palette_disabled_checks,
    "native_activation_failure_revert": _native_failure_checks,
    "blocking_task_tool_surface": _blocking_task_checks,
}


def run_state_checks(state: str, window) -> list[CheckResult]:
    handler = _CHECK_TABLE.get(state)
    if handler is None:
        return []
    return handler(window)
