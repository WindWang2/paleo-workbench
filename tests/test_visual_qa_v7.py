"""V7 视觉 QA：8 个新状态的语义检查门禁（D8：结构断言 hard-gate）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import visual_qa_v7
from paleo_workbench.ui.visual_qa_v7 import V7_STATES

pytestmark = pytest.mark.usefixtures("qapp")


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _driven_window(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    window.show()
    return window


def _assert_all_checks_pass(state: str, window) -> None:
    results = visual_qa_v7.run_state_checks(state, window)
    assert results, f"{state}: 无语义检查注册"
    failed = [r for r in results if not r.ok]
    assert not failed, (
        f"{state}: 语义检查失败 → {[r.name for r in failed]}: "
        f"{[r.detail for r in failed]}"
    )


@pytest.mark.parametrize("state", V7_STATES)
def test_semantic_checks_v7_states(qtbot, tmp_path, state):
    window = _driven_window(qtbot, tmp_path)
    drive = visual_qa_v7.v7_shot_table(lambda: None)[state][1]
    drive(window)
    _assert_all_checks_pass(state, window)


def test_v7_states_registered_shape():
    assert len(V7_STATES) == 8
    table = visual_qa_v7.v7_shot_table(lambda: None)
    assert set(table) == set(V7_STATES)
