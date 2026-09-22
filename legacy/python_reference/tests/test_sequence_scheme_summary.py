from paleo_workbench.project.models import StratigraphicFramework
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary


def test_sequence_scheme_summary_defaults(qtbot):
    summary = SequenceSchemeSummary()
    qtbot.addWidget(summary)

    assert summary.objectName() == "PanelCard"
    assert summary.scheme_value.text() == "LST/TST/HST"
    assert summary.boundary_count_value.text() == "0 个"
    assert summary.save_btn.text() == "保存层序方案"


def test_sequence_scheme_summary_update_state(qtbot):
    summary = SequenceSchemeSummary()
    qtbot.addWidget(summary)
    stratigraphy = StratigraphicFramework(
        systems_tract_scheme="三级层序格架",
        sequence_boundaries=["SB1", "SB2"],
    )

    summary.update_state(stratigraphy)

    assert summary.scheme_value.text() == "三级层序格架"
    assert summary.boundary_count_value.text() == "2 个"
    assert summary.systems_tract_value.text() == "LST / TST / HST"
