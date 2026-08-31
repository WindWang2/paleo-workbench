from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paleo_workbench.ui import navigation
from paleo_workbench.ui.sidebar import ContextSidebar, TextSidebar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_context_sidebar_initialization(qapp):
    sidebar = ContextSidebar()
    assert sidebar.objectName() == "ContextSidebar"
    assert hasattr(sidebar, "subpage_selected")
    assert hasattr(sidebar, "collapsed_changed")
    assert sidebar.is_collapsed is False


def test_context_sidebar_set_stage(qapp):
    sidebar = ContextSidebar()
    # Stage 0: 数据与预处理 opens on 首页 -> [HOME, DATA, PREPARATION]
    sidebar.set_stage(0, active_page_index=navigation.PAGE_INDEX_DATA)
    assert len(sidebar.subpage_buttons) == 3
    assert sidebar.subpage_buttons[0].property("active") is False
    assert sidebar.subpage_buttons[1].property("active") is True
    assert sidebar.subpage_buttons[2].property("active") is False
    assert sidebar.stage_caption.text() == "阶段 1 · 数据与预处理"

    # Stage 1: Interpretation -> 4 subpages (joint absorbed into 三维建模)
    sidebar.set_stage(1, active_page_index=navigation.PAGE_INDEX_WELL_LOG)
    assert len(sidebar.subpage_buttons) == 4
    assert sidebar.stage_caption.text() == "阶段 2 · 综合解释"


def test_context_sidebar_subpage_click(qapp):
    sidebar = ContextSidebar()
    sidebar.set_stage(0, active_page_index=navigation.PAGE_INDEX_DATA)

    emitted = []
    sidebar.subpage_selected.connect(lambda page_idx: emitted.append(page_idx))

    # Click third subpage button (PAGE_INDEX_PREPARATION)
    sidebar.subpage_buttons[2].click()
    assert emitted == [navigation.PAGE_INDEX_PREPARATION]


def test_context_sidebar_collapse_toggle(qapp):
    sidebar = ContextSidebar()
    assert sidebar.is_collapsed is False

    emitted = []
    sidebar.collapsed_changed.connect(lambda collapsed: emitted.append(collapsed))

    sidebar.toggle_collapse()
    assert sidebar.is_collapsed is True
    assert emitted == [True]

    sidebar.toggle_collapse()
    assert sidebar.is_collapsed is False
    assert emitted == [True, False]


def test_text_sidebar_backward_compatibility(qapp):
    sidebar = TextSidebar()
    assert isinstance(sidebar, ContextSidebar)
    sidebar.update_data_context(resource_count=5, artifact_count=2)
    assert sidebar.context_label.text() == "数据"
