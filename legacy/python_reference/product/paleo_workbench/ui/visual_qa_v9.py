"""V9 视觉 QA 状态：自适应工作站布局（viewport 策略 + dock 调整正确性）。

沿用 V6/V7/V8 模式（续篇，非替代）：

* **6 个新捕获状态**（``V9_STATES``）：紧凑视口、宽视口、超宽视口、
  窄窗功能页（滚动降级）、预设只切可见性（用户尺寸保留）、Agent
  面板 grow-only 展开；
* **语义检查**（``run_state_checks``）：布局不变量（检查器折叠策略、
  命令输入下限、中央画布保留区、dock 手柄可调整性），harness 内非
  门禁，门禁断言在 ``tests/test_visual_qa_v9.py``；
* 全部离屏可构造；真实顶层窗口（PaleoWorkbenchWindow）驱动 resize。
"""

from __future__ import annotations

from collections.abc import Callable

from paleo_workbench.ui.visual_qa_v6 import CheckResult, _check, _settle
from paleo_workbench.ui.visual_qa_v7 import _workstation

V9_STATES: tuple[str, ...] = (
    "compact_viewport",
    "wide_viewport",
    "ultrawide_viewport",
    "narrow_hub_page",
    "preset_visibility_only",
    "agent_grow_only",
)

#: 目标窗口尺寸（逻辑像素；离屏平台不缩放）。
_COMPACT_SIZE = (1000, 700)
_WIDE_SIZE = (1920, 1080)
_ULTRAWIDE_SIZE = (2560, 1440)
_NARROW_SIZE = (960, 600)


def _resize_and_settle(window, size, ms: int = 400) -> None:
    window.resize(*size)
    _settle(ms)  # ≥ 180ms 去抖窗 + 布局安定


# -- 驱动函数 ------------------------------------------------------------------


def _prime_window(window) -> None:
    """show 后等 restore 完成（50ms 补投的 restoreGeometry 会覆盖 resize）。"""
    window.show()
    _settle(250)


def drive_compact_viewport(window) -> None:
    """1000x700（紧凑类）：检查器响应式折叠 + 顶栏压缩。"""
    _prime_window(window)
    _resize_and_settle(window, (1600, 900))
    _resize_and_settle(window, _COMPACT_SIZE)


def drive_wide_viewport(window) -> None:
    """1920x1080（宽类）：核心 dock 全可见。"""
    _prime_window(window)
    _resize_and_settle(window, _WIDE_SIZE)


def drive_ultrawide_viewport(window) -> None:
    """2560x1440（超宽类）：无面板被策略折叠。"""
    _prime_window(window)
    _resize_and_settle(window, _ULTRAWIDE_SIZE)


def drive_narrow_hub_page(window) -> None:
    """960x600 窄窗打开功能页 dock：页面滚动降级，中央画布不被挤没。"""
    _prime_window(window)
    _resize_and_settle(window, (1600, 900))
    ws = _workstation(window)
    ws.show_hub_page("数据管理")
    _resize_and_settle(window, _NARROW_SIZE)


def drive_preset_visibility_only(window) -> None:
    """用户手调 nav 宽度后应用具名预设：dock 几何必须保留（B-3）。"""
    _prime_window(window)
    _resize_and_settle(window, _WIDE_SIZE)
    ws = _workstation(window)
    from PySide6.QtCore import Qt

    host = ws._dock_host
    host.resizeDocks([ws.nav_dock], [430], Qt.Orientation.Horizontal)
    _settle(300)
    window._v9_nav_width_before = ws.nav_dock.width()
    ws.apply_layout_preset("review")
    _settle(300)


def drive_agent_grow_only(window) -> None:
    """用户调高 Agent 底行后打开 Agent：高度不得被压回 245（B-3）。"""
    _prime_window(window)
    _resize_and_settle(window, _WIDE_SIZE)
    ws = _workstation(window)
    ws.agent_dock.show()
    ws.agent_dock.resize(ws.agent_dock.width(), 420)
    _settle(200)
    window._v9_agent_height_before = ws.agent_dock.height()
    ws.show_agent()
    _settle(200)


def v9_shot_table(make_project: Callable, *, no_project_factory: Callable | None = None):
    """(状态 → (工程工厂, 驱动)) 表——与 v6/v7/v8 注册形态一致。"""
    none_factory = no_project_factory or (lambda: None)
    return {
        "compact_viewport": (make_project, drive_compact_viewport),
        "wide_viewport": (make_project, drive_wide_viewport),
        "ultrawide_viewport": (make_project, drive_ultrawide_viewport),
        "narrow_hub_page": (make_project, drive_narrow_hub_page),
        "preset_visibility_only": (make_project, drive_preset_visibility_only),
        "agent_grow_only": (make_project, drive_agent_grow_only),
    }


# -- 语义检查（非门禁；门禁在 tests/test_visual_qa_v9.py） ----------------------


def _compact_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    return [
        _check("compact_inspector_folded", ws.inspector_dock.isHidden()),
        _check("compact_inspector_flagged_responsive",
               ws._responsive_hid_inspector and not ws._user_hid_inspector),
        _check("compact_command_floor_220",
               ws.app_bar.command_input.minimumWidth() <= 220),
        _check("compact_stage_label_hidden",
               not ws.stage_bar.horizon_label.isVisibleTo(ws.stage_bar)),
        _check("compact_nav_visible", not ws.nav_dock.isHidden()),
        _check("compact_canvas_floor_kept",
               ws.composite.width() >= 300,
               f"canvas={ws.composite.width()}"),
    ]


def _wide_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    return [
        _check("wide_inspector_visible", not ws.inspector_dock.isHidden()),
        _check("wide_command_floor_300",
               ws.app_bar.command_input.minimumWidth() >= 300),
        _check("wide_stage_label_visible",
               ws.stage_bar.horizon_label.isVisibleTo(ws.stage_bar)),
        _check("wide_canvas_roomy", ws.composite.width() >= 800,
               f"canvas={ws.composite.width()}"),
    ]


def _ultrawide_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    visible = all(
        not dock.isHidden()
        for dock in (ws.nav_dock, ws.inspector_dock, ws.composite_layer_dock)
    )
    return [
        _check("ultrawide_core_docks_visible", visible),
        _check("ultrawide_no_responsive_fold",
               not ws._responsive_hid_inspector),
        _check("ultrawide_canvas_roomy", ws.composite.width() >= 1400,
               f"canvas={ws.composite.width()}"),
    ]


def _narrow_hub_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    hub_scroll = ws.hub_scroll
    return [
        _check("narrow_hub_dock_open", not ws.hub_dock.isHidden()),
        _check("narrow_hub_scroll_host_small_min",
               hub_scroll.minimumSizeHint().width() <= 80,
               f"min={hub_scroll.minimumSizeHint().width()}"),
        _check("narrow_hub_dock_resizable_below_page_min",
               ws.hub_dock.minimumSizeHint().width() <= 80,
               f"min={ws.hub_dock.minimumSizeHint().width()}"),
        _check("narrow_canvas_floor_kept",
               ws.composite.width() >= 300,
               f"canvas={ws.composite.width()}"),
        _check("narrow_window_min_960", window.minimumWidth() <= 960),
    ]


def _preset_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    before = int(getattr(window, "_v9_nav_width_before", 0))
    after = ws.nav_dock.width()
    # resizeDocks 尽力而为：只要求不被回卷到默认 280（用户值必须存活）。
    preserved = before > 0 and abs(after - before) <= 40
    return [
        _check("preset_kept_user_nav_width", preserved,
               f"before={before} after={after}"),
        _check("preset_applied_flag", ws.current_preset_id == "review",
               str(ws.current_preset_id)),
    ]


def _agent_checks(window) -> list[CheckResult]:
    ws = _workstation(window)
    before = int(getattr(window, "_v9_agent_height_before", 0))
    after = ws.agent_dock.height()
    kept = before > 0 and after >= min(before, 380)
    return [
        _check("agent_row_not_snapped_back", kept,
               f"before={before} after={after}"),
        _check("agent_dock_visible", not ws.agent_dock.isHidden()),
    ]


_CHECK_TABLE: dict[str, Callable[[object], list[CheckResult]]] = {
    "compact_viewport": _compact_checks,
    "wide_viewport": _wide_checks,
    "ultrawide_viewport": _ultrawide_checks,
    "narrow_hub_page": _narrow_hub_checks,
    "preset_visibility_only": _preset_checks,
    "agent_grow_only": _agent_checks,
}


def run_state_checks(state: str, window) -> list[CheckResult]:
    handler = _CHECK_TABLE.get(state)
    if handler is None:
        return []
    return handler(window)
