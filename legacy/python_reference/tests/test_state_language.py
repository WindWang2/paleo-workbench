"""V6 §5：统一状态语言（state_language）。

一处定义全域状态 → (glyph, 文案, tone) 的映射：成熟度（RAW/DERIVED/…）、
新鲜度（current/stale/missing）、可编辑性、任务态、后端能力、权限态。
消费者（状态条 / 徽标 / 检查器 / 任务中心）不再各自发明 emoji 或色块——
glyph+文字双信号，绝不只靠颜色。未知值诚实返回「未知」，不编造。
"""
from __future__ import annotations

import pytest

from paleo_workbench.ui.workstation.state_language import (
    StateToken,
    state_token,
    workbench_context_text,
)
from paleo_workbench.ui.workstation.ui_context import UIContextSnapshot

pytestmark = pytest.mark.usefixtures("qapp")


# --- 词汇映射 ---------------------------------------------------------------


def test_maturity_raw_carries_lock_semantics():
    token = state_token("maturity", "raw")
    assert isinstance(token, StateToken)
    assert "RAW" in token.label or "原始" in token.label
    assert token.tone == "locked"
    assert token.glyph  # 非 color-only：必有 glyph


def test_unknown_value_is_honest_not_invented():
    token = state_token("maturity", "weird-future-value")
    assert "未知" in token.label
    assert token.tone == "muted"


def test_unknown_category_raises():
    with pytest.raises(KeyError):
        state_token("no-such-category", "x")


def test_all_categories_cover_core_values():
    assert state_token("freshness", "stale").tone == "warn"
    assert state_token("freshness", "missing").tone == "error"
    assert state_token("task", "cancelling").tone != state_token("task", "cancelled").tone
    assert "取消中" in state_token("task", "cancelling").label
    assert "已取消" in state_token("task", "cancelled").label
    assert state_token("backend", "fallback").tone == "warn"
    assert state_token("backend", "native").tone == "ok"
    assert state_token("permission", "read_only").tone == "muted"


# --- 工作台上下文状态条文案 -----------------------------------------------------


def test_workbench_context_text_full():
    snap = UIContextSnapshot(
        project_open=True,
        project_name="HZ26",
        mapping_stage="phase2",
        mapping_stage_label="约束与单因素",
        active_layer_id="L1",
        active_layer_role="物源线",
        active_layer_editable=True,
        editing_active=True,
        qgis_bridge_available=True,
        running_task_count=2,
    )
    text = workbench_context_text(snap, layer_name=lambda _id: "物源线-草稿A")
    assert "约束与单因素" in text
    assert "物源线-草稿A" in text
    assert "原生" in text  # QGIS 桥可用
    assert "2" in text  # 运行中任务数


def test_workbench_context_text_blocked_target_shows_reason():
    snap = UIContextSnapshot(
        project_open=True,
        mapping_stage="phase2",
        mapping_stage_label="约束与单因素",
        active_layer_id="L1",
        active_layer_editable=False,
        active_layer_block_reason="RAW 证据不可编辑",
    )
    text = workbench_context_text(snap, layer_name=lambda _id: "初始相图")
    assert "RAW 证据不可编辑" in text  # 原因可见，不静默


def test_workbench_context_text_hides_absent_segments():
    snap = UIContextSnapshot(project_open=True, running_task_count=0)
    text = workbench_context_text(snap, layer_name=lambda _id: "x")
    assert "任务" not in text
    assert text.strip()  # 但不是空文案（工程在开 = 有可说的）


def test_workbench_context_text_fallback_backend_visible():
    snap = UIContextSnapshot(project_open=True, qgis_bridge_available=False)
    text = workbench_context_text(snap, layer_name=lambda _id: "x")
    assert "回退" in text  # 降级路径必须可见


# --- 集成：AppShell 状态条工作台段 --------------------------------------------


def test_app_shell_status_bar_shows_workbench_context(qtbot, tmp_path):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.app_shell import AppShell

    project = ProjectDocument.new("HZ26")
    project.meta.project_root = str(tmp_path)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    label = shell.status_bar.workbench_label
    assert not label.isHidden()
    assert label.text().strip()
