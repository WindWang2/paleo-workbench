"""V8 视觉 QA：6 个新状态的语义检查门禁（D8：结构断言 hard-gate）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import visual_qa_v8
from paleo_workbench.ui.visual_qa_v8 import V8_STATES

pytestmark = pytest.mark.usefixtures("qapp")


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _driven_window(qtbot, tmp_path, *, project=None):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(
        project=project if project is not None else _project(tmp_path))
    qtbot.addWidget(window)
    window.show()
    return window


def _assert_all_checks_pass(state: str, window) -> None:
    results = visual_qa_v8.run_state_checks(state, window)
    assert results, f"{state}: 无语义检查注册"
    failed = [r for r in results if not r.ok]
    assert not failed, (
        f"{state}: 语义检查失败 → {[r.name for r in failed]}: "
        f"{[r.detail for r in failed]}"
    )


@pytest.mark.parametrize("state", V8_STATES)
def test_semantic_checks_v8_states(qtbot, tmp_path, state):
    if state == "empty_project_tool_surface":
        window = _driven_window(qtbot, tmp_path, project=None)
    else:
        window = _driven_window(qtbot, tmp_path)
    drive = visual_qa_v8.v8_shot_table(lambda: None)[state][1]
    drive(window)
    _assert_all_checks_pass(state, window)


def test_v8_states_registered_shape():
    assert len(V8_STATES) == 6
    table = visual_qa_v8.v8_shot_table(lambda: None)
    assert set(table) == set(V8_STATES)


def test_no_project_state_uses_explicit_factory():
    """无工程状态的工厂必须是显式 none 工厂（不与有工程状态共享）。"""
    table = visual_qa_v8.v8_shot_table(lambda: "project")
    factory = table["empty_project_tool_surface"][0]
    assert factory() is None
    assert table["frozen_map_product"][0]() == "project"
