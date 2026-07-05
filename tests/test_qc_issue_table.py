from paleo_workbench.ui import tokens
from paleo_workbench.project.models import QualityReport
from paleo_workbench.ui.pages.qc_issue_table import QCIssueTable


def _make_report(rules, issues=None):
    return QualityReport(
        linked_map_document_id="m1",
        rules=rules,
        issues=issues or [],
    )


def test_table_object_name(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    assert widget.objectName() == "QCIssueTable"


def test_table_three_columns(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    assert widget.table.columnCount() == 3
    headers = [widget.table.horizontalHeaderItem(i).text() for i in range(3)]
    assert headers == ["检查项目", "检查说明", "结果说明"]


def test_table_pass_result(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    report = _make_report(rules=["层级一致性"])
    widget.update_state([report])
    assert widget.table.rowCount() == 1
    # col 0 rule, col 1 description, col 2 result
    assert widget.table.item(0, 0).text() == "层级一致性"
    assert widget.table.item(0, 1).text() == tokens.RULE_DESCRIPTIONS["层级一致性"]
    result_item = widget.table.item(0, 2)
    assert result_item.text() == "✓通过"
    assert result_item.foreground().color().name() == tokens.SUCCESS


def test_table_warning_result(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    report = _make_report(
        rules=["未分类区域"],
        issues=[{"rule": "未分类区域", "severity": "warning", "message": "1处"}],
    )
    widget.update_state([report])
    result_item = widget.table.item(0, 2)
    assert "!警告" in result_item.text()
    assert "1处" in result_item.text()
    assert result_item.foreground().color().name() == tokens.WARNING


def test_table_error_result(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    report = _make_report(
        rules=["低可信区"],
        issues=[{"rule": "低可信区", "severity": "error", "message": "需复核"}],
    )
    widget.update_state([report])
    result_item = widget.table.item(0, 2)
    assert "!待处理" in result_item.text()
    assert "需复核" in result_item.text()
    assert result_item.foreground().color().name() == tokens.ERROR_RED


def test_table_empty_state(qtbot):
    widget = QCIssueTable()
    qtbot.addWidget(widget)
    widget.update_state([])
    assert widget.table.rowCount() == 0
