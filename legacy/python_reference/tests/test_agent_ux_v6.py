"""V6 §11：Agent/任务 UX——诚实结果渲染 + 专业 WRITE 授权 + 重算入口。

* F-P0-1：DEGRADED 结果此前一律渲染「校验通过」，warnings 被丢弃；
* F-P1-1：WRITE 授权是通用 Yes/No 弹窗，无动作卡/范围/会话粒度；
* F-P1-2：「更新受影响成果」重算流无发射方（孤儿代码）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.harness.executor import ActionResult
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.agent_panel import AgentPlan, AgentWorkspace

pytestmark = pytest.mark.usefixtures("qapp")


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _panel(qtbot, tmp_path) -> AgentWorkspace:
    panel = AgentWorkspace(_project(tmp_path))
    qtbot.addWidget(panel)
    return panel


def _result(status: str = "success", warnings=None, error=None) -> ActionResult:
    return ActionResult(
        action_id="well.list", status=status,
        warnings=list(warnings or []), error=error,
    )


def _payload(results, cancelled=False, failed=None):
    return {
        "cancelled": cancelled,
        "failed_exception": failed,
        "plan": AgentPlan(
            action_id="well.list", parameters={}, gui_action="",
            summary="列出井"),
        "results": list(results),
    }


# --- F-P0-1: 诚实结果渲染 ------------------------------------------------------


def test_degraded_result_shows_warnings_not_fake_pass(qtbot, tmp_path):
    panel = _panel(qtbot, tmp_path)
    panel._on_completed(_payload([_result("degraded", warnings=["部分井缺轨迹，已跳过 3 口"])]))
    html = panel.history.toHtml()
    assert "降级" in html
    assert "部分井缺轨迹" in html
    assert "校验通过" not in html


def test_clean_success_keeps_pass_rendering(qtbot, tmp_path):
    panel = _panel(qtbot, tmp_path)
    panel._on_completed(_payload([_result("success")]))
    html = panel.history.toHtml()
    assert "校验通过" in html


def test_rejected_result_shows_guard_reason(qtbot, tmp_path):
    panel = _panel(qtbot, tmp_path)
    panel._on_completed(_payload([_result("rejected", error="写入未授权：当前会话只读")]))
    html = panel.history.toHtml()
    assert "写入未授权" in html


# --- F-P1-1: 专业 WRITE 授权对话框 ---------------------------------------------


def test_write_grant_dialog_lists_actions_with_spec_info(qtbot, tmp_path):
    panel = _panel(qtbot, tmp_path)
    dialog = panel._build_write_grant_dialog(["workflow.run"])
    qtbot.addWidget(dialog)
    text = _dialog_text(dialog)
    assert "workflow.run" in text
    assert "写入" in text
    # 安全默认：「拒绝」按钮持有 default（回车=拒绝，不是授权）。
    from PySide6.QtWidgets import QPushButton

    deny = next(
        (b for b in dialog.findChildren(QPushButton) if b.text() == "拒绝"), None
    )
    assert deny is not None and deny.isDefault()


def test_write_grant_session_scope_skips_second_confirm(qtbot, tmp_path):
    panel = _panel(qtbot, tmp_path)
    # 会话内首次授权（直接调内部状态，验证粒度语义而非弹窗交互）。
    panel._grant_write_session({"workflow.run"})
    assert panel._write_granted_for({"workflow.run"}) is True
    assert panel._write_granted_for({"workflow.run", "mapping.export"}) is False


def _dialog_text(dialog) -> str:
    chunks: list[str] = []

    def _walk(widget):
        from PySide6.QtWidgets import QLabel

        if isinstance(widget, QLabel):
            chunks.append(widget.text())
        for child in widget.findChildren(type(widget)) or []:
            pass
        from PySide6.QtCore import QObject

        for child in widget.findChildren(QObject):
            from PySide6.QtWidgets import QLabel as _L

            if isinstance(child, _L):
                chunks.append(child.text())

    _walk(dialog)
    return "\n".join(chunks)


# --- F-P1-2: 重算命令可发现 -----------------------------------------------------


def test_recompute_command_registered_by_window(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui.command_registry import command_registry

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    spec = command_registry.get("workflow:recompute")
    assert spec is not None
    assert spec.callback is not None
    assert "workflow" in spec.context_tags
