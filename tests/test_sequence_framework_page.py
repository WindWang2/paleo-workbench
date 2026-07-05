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
