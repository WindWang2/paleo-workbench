"""V9 视觉 QA：自适应布局状态的语义检查门禁。"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import visual_qa_v9
from paleo_workbench.ui.visual_qa_v9 import V9_STATES

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _hermetic_global_layout_settings():
    """清空工作站全局布局 QSettings（R3 P1-1 测试面）。

    QA 窗口 restore 全局 window_state；同会话早先文件残留的布局会把
    中央画布钉在地板、帧 resizeEvent 不发，compact 断言假失败。
    """
    from PySide6.QtCore import QSettings

    settings = QSettings("PaleoWorkbench", "Workstation")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _driven_window(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    return window


def _assert_all_checks_pass(state: str, window) -> None:
    results = visual_qa_v9.run_state_checks(state, window)
    assert results, f"{state}: 无语义检查注册"
    failed = [r for r in results if not r.ok]
    assert not failed, (
        f"{state}: 语义检查失败 → {[r.name for r in failed]}: "
        f"{[r.detail for r in failed]}"
    )


@pytest.mark.parametrize("state", V9_STATES)
def test_semantic_checks_v9_states(qtbot, tmp_path, state):
    window = _driven_window(qtbot, tmp_path)
    drive = visual_qa_v9.v9_shot_table(lambda: None)[state][1]
    drive(window)
    _assert_all_checks_pass(state, window)


def test_v9_states_registered_shape():
    assert len(V9_STATES) == 6
    table = visual_qa_v9.v9_shot_table(lambda: None)
    assert set(table) == set(V9_STATES)
