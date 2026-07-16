from paleo_workbench.project.models import StratigraphicFramework
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable


def test_sequence_boundary_table_empty_state(qtbot):
    table = SequenceBoundaryTable()
    qtbot.addWidget(table)

    table.update_state(StratigraphicFramework())

    assert table.table.rowCount() == 0
    assert not table.empty_label.isHidden()
    assert "未配置层序界面" in table.empty_label.text()


def test_sequence_boundary_table_lists_boundaries(qtbot):
    widget = SequenceBoundaryTable()
    qtbot.addWidget(widget)
    stratigraphy = StratigraphicFramework(
        target_horizon="ZJ2",
        sequence_boundaries=["SB1", "SB2", "MFS1"],
    )

    widget.update_state(stratigraphy)

    assert widget.table.rowCount() == 3
    assert widget.empty_label.isHidden()
    assert widget.table.item(0, 0).text() == "SB1"
    assert widget.table.item(0, 1).text() == "ZJ2"
    assert widget.table.item(2, 2).text() == "第 3 层序界面"
