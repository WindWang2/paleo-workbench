"""V6 Phase 8 视觉 QA 状态：合成驱动 + 语义检查（均非门禁）。

本模块是 V5 截图 harness（``scripts/capture_workstation_screens.py``，
12 状态 + 主题×密度×尺寸矩阵）的**扩展**，不是替代：

* **6 个新捕获状态**（``V6_STATES``）：编图阶段 1/2/3（阶段条 + 阶段
  面板 + 工具条阶段过滤）、带上下文的命令面板（阶段限定禁用命令 +
  原因）、WRITE 授权对话框、状态条工作台段。全部离屏可构造，合成
  工程、无 QGIS 桥（composite 回退画布——本套件运行环境的诚实现实）。
* **语义检查**（``run_state_checks``）：超越像素 diff 的 widget 级
  不变量断言。与 PIL 像素 diff 同为**非门禁**（decisions.md D8）：
  harness 只记录（``_checks/<state>.json`` 旁车文件 + 控制台
  PASS/FAIL 行），门禁断言在 ``tests/test_visual_qa_v6.py``。

驱动函数只编排 UI 状态（阶段切换/面板显隐/对话框构造），不注入假
数据；截图抓的是 offscreen 平台实际渲染的结果。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QDialogButtonBox

from paleo_workbench.mapping_workspace.stages import (
    STAGE_ORDER,
    MappingStage,
)

#: 新捕获状态（注册进 capture_workstation_screens.shots；文件名即状态名）。
V6_STATES: tuple[str, ...] = (
    "mapping_stage_phase1",
    "mapping_stage_phase2",
    "mapping_stage_phase3",
    "command_palette_context",
    "write_grant_dialog",
    "status_workbench_segment",
)

#: WRITE 授权对话框 fixture 用的真实 harness WRITE 动作（注册表有
#: ActionSpec 描述——卡片不出现「未知动作」降级路径）。
WRITE_GRANT_ACTION_IDS: tuple[str, ...] = ("map.add_layer", "map.export")

#: 命令面板上下文态的过滤词：命中阶段 2 专属命令（当前在阶段 1 → 禁用
#: + 原因可见）。
PALETTE_CONTEXT_FILTER = "单因素"


def _settle(ms: int) -> None:
    """事件循环内等待（与截图 harness 的 _settle 同语义）。"""
    from PySide6.QtWidgets import QApplication

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QApplication.processEvents()


def _workstation(window):
    return window.app_shell.workstation


# -- 驱动函数（harness --shot 子进程与测试共用） ------------------------------


def drive_mapping_stage_phase1(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.mapping_stage_dock.raise_()
    ws.composite.stage_controller.set_stage(MappingStage.FACIES_CALIBRATION.value)
    _settle(200)


def drive_mapping_stage_phase2(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.mapping_stage_dock.raise_()
    ws.composite.stage_controller.set_stage(MappingStage.CONSTRAINT_FACTOR.value)
    _settle(200)


def drive_mapping_stage_phase3(window) -> None:
    ws = _workstation(window)
    ws.mapping_stage_dock.show()
    ws.mapping_stage_dock.raise_()
    ws.composite.stage_controller.set_stage(MappingStage.INTEGRATED_COMPILATION.value)
    _settle(200)


def drive_command_palette_context(window) -> None:
    """阶段 1 + 面板打开 + 过滤命中阶段 2 专属命令 → 禁用原因可见。"""
    shell = window.app_shell
    shell.workstation.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value)
    _settle(150)
    palette = shell.command_palette
    palette.popup()
    palette.filter_input.setText(PALETTE_CONTEXT_FILTER)
    _settle(100)


def drive_write_grant_dialog(window) -> None:
    """WRITE 授权对话框：真实注册表动作卡 + 拒绝默认。非模态 show()
    （不 ``exec``——截图进程不能被模态循环卡住）。对话框是独立顶层，
    harness 经 ``window._v6_grab_widget`` 改抓对话框本体。"""
    agent = _workstation(window).agent_panel
    dialog = agent._build_write_grant_dialog(list(WRITE_GRANT_ACTION_IDS))
    dialog.resize(560, 480)
    dialog.show()
    window._v6_grab_widget = dialog
    _settle(150)


def drive_status_workbench_segment(window) -> None:
    """阶段 2 + 显式上下文重算 → 状态条工作台段显示
    「阶段 · 编辑目标 · 后端 · 任务」。"""
    shell = window.app_shell
    shell.workstation.composite.stage_controller.set_stage(
        MappingStage.CONSTRAINT_FACTOR.value)
    _settle(150)
    shell.ui_context_service.refresh()
    _settle(50)


def v6_shot_table(make_project: Callable):
    """按 V5 harness 的注册形态给出 ``(状态 → (工程工厂, 驱动))`` 表。

    ``make_project`` 由 harness 传入（合成工程构造器与其 12 状态共用），
    保证新状态的工程 fixture 与既有状态同源。
    """
    return {
        "mapping_stage_phase1": (make_project, drive_mapping_stage_phase1),
        "mapping_stage_phase2": (make_project, drive_mapping_stage_phase2),
        "mapping_stage_phase3": (make_project, drive_mapping_stage_phase3),
        "command_palette_context": (make_project, drive_command_palette_context),
        "write_grant_dialog": (make_project, drive_write_grant_dialog),
        "status_workbench_segment": (make_project, drive_status_workbench_segment),
    }


# -- 语义检查（非门禁；门禁在 tests/test_visual_qa_v6.py） ----------------------


@dataclass(frozen=True)
class CheckResult:
    """一条语义检查结果（harness 落盘旁车 JSON；ok=False 仅告警）。"""

    name: str
    ok: bool
    detail: str = ""


def _check(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def _mapping_stage_checks(target: MappingStage):
    """阶段态共用不变量：阶段条当前标记 + 阶段面板页 + 工具条阶段过滤。"""

    def run(window) -> list[CheckResult]:
        from PySide6.QtGui import QAction

        ws = _workstation(window)
        results: list[CheckResult] = []
        # 1. 阶段条：目标阶段按钮 checked，其余不 checked。
        for stage in STAGE_ORDER:
            button = ws.stage_bar._buttons.get(stage)
            want = stage == target
            results.append(_check(
                f"stage_bar_marker[{stage.value}]",
                button is not None and button.isChecked() == want,
                f"checked={button.isChecked() if button else None} want={want}",
            ))
        # 2. 阶段面板：栈当前页是目标阶段页。
        page = ws.mapping_stage_panel._pages.get(target)
        results.append(_check(
            "stage_panel_current_page",
            page is not None
            and ws.mapping_stage_panel.stack.currentWidget() is page,
            f"current={ws.mapping_stage_panel.stack.currentWidget()}",
        ))
        # 3. 工具条阶段过滤（V6 §4）：add_line 仅阶段 2/3 可见，阶段 1 隐藏；
        #    add_polygon 三阶段都可见（基础数字化不被阶段误伤）。
        actions: dict[str, QAction] = ws.composite.action_controller.actions
        add_line = actions.get("add_line")
        add_polygon = actions.get("add_polygon")
        line_want = target in (
            MappingStage.CONSTRAINT_FACTOR, MappingStage.INTEGRATED_COMPILATION)
        results.append(_check(
            "toolbar_add_line_stage_visibility",
            add_line is not None and add_line.isVisible() == line_want,
            f"visible={add_line.isVisible() if add_line else None} want={line_want}",
        ))
        results.append(_check(
            "toolbar_add_polygon_always_visible",
            add_polygon is not None and add_polygon.isVisible(),
            f"visible={add_polygon.isVisible() if add_polygon else None}",
        ))
        # 4. 阶段面板 dock 可见（截图主体在画面里）。
        results.append(_check(
            "stage_dock_visible",
            not ws.mapping_stage_dock.isHidden(),
            "",
        ))
        return results

    return run


def _command_palette_checks(window) -> list[CheckResult]:
    from PySide6.QtCore import Qt

    palette = window.app_shell.command_palette
    results = [
        _check("palette_open", not palette.isHidden(), ""),
    ]
    disabled_specs = []
    for row in range(palette.result_list.count()):
        item = palette.result_list.item(row)
        spec = item.data(Qt.ItemDataRole.UserRole)
        enabled = bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)
        if not enabled:
            disabled_specs.append((item.text(), spec))
    # 1. 至少一条禁用命令：阶段限定命令在错误阶段保留可发现性。
    results.append(_check(
        "palette_has_disabled_stage_command",
        bool(disabled_specs),
        f"disabled={len(disabled_specs)}",
    ))
    # 2. 禁用项文本包含人类可读原因，且 spec 确为阶段限定。
    reason_ok = any("不可用" in text for text, _ in disabled_specs)
    results.append(_check("disabled_item_shows_reason", reason_ok, ""))
    stage_scoped = any(
        getattr(spec, "stages", ()) for _, spec in disabled_specs)
    results.append(_check(
        "disabled_item_is_stage_scoped", stage_scoped, ""))
    # 3. 过滤词确实命中（结果列表非空且含过滤词的子串序列）。
    texts = [
        palette.result_list.item(row).text()
        for row in range(palette.result_list.count())
    ]
    results.append(_check(
        "palette_filter_matched",
        any("单因素" in text for text in texts),
        f"rows={len(texts)}",
    ))
    return results


def _write_grant_checks(window) -> list[CheckResult]:
    from PySide6.QtWidgets import QDialog, QLabel

    dialog: QDialog | None = getattr(window, "_v6_grab_widget", None)
    if dialog is None:
        return [_check("dialog_constructed", False, "no _v6_grab_widget")]
    results = [_check(
        "dialog_constructed",
        dialog.objectName() == "WriteGrantDialog" and not dialog.isHidden(),
        dialog.objectName(),
    )]
    buttons = dialog.findChild(QDialogButtonBox)
    deny = buttons.button(QDialogButtonBox.StandardButton.No) if buttons else None
    grant = buttons.button(QDialogButtonBox.StandardButton.Yes) if buttons else None
    # 安全默认：拒绝按钮是 default 且持有焦点语义（V6 §11）。
    results.append(_check(
        "deny_button_is_default",
        deny is not None and deny.isDefault(),
        f"default={deny.isDefault() if deny else None}",
    ))
    results.append(_check(
        "deny_button_labelled",
        deny is not None and deny.text() == "拒绝",
        deny.text() if deny else "",
    ))
    results.append(_check(
        "grant_button_labelled",
        grant is not None and grant.text() == "授权",
        grant.text() if grant else "",
    ))
    # 未交互前 granted 必须为 False（不预授权）。
    results.append(_check(
        "dialog_not_pre_granted",
        getattr(dialog, "granted", None) is False,
        repr(getattr(dialog, "granted", None)),
    ))
    # 动作卡：每个 WRITE 动作 id 可见（真实注册表 spec，非未知降级）。
    labels = [l.text() for l in dialog.findChildren(QLabel)]
    for action_id in WRITE_GRANT_ACTION_IDS:
        results.append(_check(
            f"action_card[{action_id}]",
            any(action_id in text for text in labels),
            "",
        ))
    results.append(_check(
        "no_unknown_action_fallback",
        not any("注册表中无此动作" in text for text in labels),
        "",
    ))
    return results


def _status_segment_checks(window) -> list[CheckResult]:
    label = window.app_shell.status_bar.workbench_label
    text = label.text()
    results = [
        _check("segment_label_non_empty", bool(text.strip()), repr(text)),
        # 后端态必须出现（QGIS 原生 / 画布回退——两种都诚实）。
        _check("segment_shows_backend_state", "QGIS" in text, repr(text)),
        # 阶段 2 上下文已反映到状态段。
        _check(
            "segment_shows_mapping_stage",
            MappingStage.CONSTRAINT_FACTOR.label in text
            or MappingStage.CONSTRAINT_FACTOR.short_label in text,
            repr(text),
        ),
        _check("segment_visible", not label.isHidden(), ""),
    ]
    return results


_CHECK_TABLE: dict[str, Callable[[object], list[CheckResult]]] = {
    "mapping_stage_phase1": _mapping_stage_checks(MappingStage.FACIES_CALIBRATION),
    "mapping_stage_phase2": _mapping_stage_checks(MappingStage.CONSTRAINT_FACTOR),
    "mapping_stage_phase3": _mapping_stage_checks(MappingStage.INTEGRATED_COMPILATION),
    "command_palette_context": _command_palette_checks,
    "write_grant_dialog": _write_grant_checks,
    "status_workbench_segment": _status_segment_checks,
}


def run_state_checks(state: str, window) -> list[CheckResult]:
    """对已驱动的 ``window`` 跑该状态的语义检查（未知状态 → 空表）。

    返回值仅供记录/测试断言；harness 不据此失败（非门禁，同 PIL diff）。
    """
    handler = _CHECK_TABLE.get(state)
    if handler is None:
        return []
    return handler(window)


def checks_payload(results: list[CheckResult]) -> dict:
    """旁车 JSON 载荷（含汇总位，供人工复核与 evidence 页引用）。"""
    entries = [
        {"name": r.name, "ok": r.ok, "detail": r.detail} for r in results
    ]
    return {
        "state_ok": all(r.ok for r in results) if results else None,
        "checks": entries,
    }


__all__ = [
    "V6_STATES",
    "WRITE_GRANT_ACTION_IDS",
    "PALETTE_CONTEXT_FILTER",
    "CheckResult",
    "drive_command_palette_context",
    "drive_mapping_stage_phase1",
    "drive_mapping_stage_phase2",
    "drive_mapping_stage_phase3",
    "drive_status_workbench_segment",
    "drive_write_grant_dialog",
    "checks_payload",
    "run_state_checks",
    "v6_shot_table",
]
