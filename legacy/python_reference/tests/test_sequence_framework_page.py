from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QSplitter

from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel


def test_sequence_framework_page_assembles_three_panels(qtbot):
    page = SequenceFrameworkPage()
    qtbot.addWidget(page)

    assert page.objectName() == "SequenceFrameworkPage"
    assert isinstance(page.target_panel, SequenceTargetPanel)
    assert isinstance(page.boundary_table, SequenceBoundaryTable)
    assert isinstance(page.scheme_summary, SequenceSchemeSummary)


def test_sequence_framework_page_uses_resizable_splitter(qtbot):
    page = SequenceFrameworkPage()
    qtbot.addWidget(page)

    splitter = page.content_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.objectName() == "SequenceFrameworkSplitter"
    assert splitter.count() == 3
    assert splitter.widget(0) is page.target_panel
    assert splitter.widget(1) is page.boundary_table
    assert splitter.widget(2) is page.scheme_summary
    # Side panels keep their design widths as resizable minimums.
    assert page.target_panel.minimumWidth() < page.target_panel.maximumWidth()
    assert page.scheme_summary.minimumWidth() < page.scheme_summary.maximumWidth()

    page.resize(1280, 800)
    page.show()
    before = splitter.sizes()
    page.resize(1680, 800)
    QApplication.processEvents()
    after = splitter.sizes()

    # 层序界面表 stays the stretchy center and absorbs the extra width.
    assert before[1] > before[0]
    assert before[1] > before[2]
    assert after[1] - before[1] > after[0] - before[0]
    assert after[1] - before[1] > after[2] - before[2]


def test_sequence_framework_page_side_panel_float_round_trip(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    page = SequenceFrameworkPage(persistence=LayoutPersistence(settings))
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()

    key = "sequence:target"
    assert page.float_controller.toggle(key) is True
    floating = page.float_controller.floating_panel(key)
    qtbot.addWidget(floating)
    assert page.target_panel.parentWidget() is floating.content_host
    # The boundary table never floats — no entry point exists for it.
    assert "sequence:boundary" not in page._floatable
    assert page.boundary_table.parentWidget() is page.content_splitter

    assert page.float_controller.toggle(key) is True
    assert page.content_splitter.widget(0) is page.target_panel


def test_sequence_framework_page_update_delegates(qtbot):
    page = SequenceFrameworkPage()
    qtbot.addWidget(page)
    calls = []

    def make_spy():
        return lambda stratigraphy: calls.append(stratigraphy)

    page.target_panel.update_state = make_spy()
    page.boundary_table.update_state = make_spy()
    page.scheme_summary.update_state = make_spy()

    stratigraphy = {"target_horizon": "ZJ2"}
    page.update_state(stratigraphy)

    assert calls == [stratigraphy, stratigraphy, stratigraphy]
