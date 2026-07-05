from paleo_workbench.project.models import ExportArtifact, QualityReport
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.result_summary import ResultSummary


def _make_report(rules, issues=None):
    return QualityReport(
        linked_map_document_id="m1",
        rules=rules,
        issues=issues or [],
    )


def test_summary_object_name(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    assert widget.objectName() == "ResultSummary"


def test_summary_counts(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    report = _make_report(
        rules=["层级一致性", "未分类区域", "低可信区"],
        issues=[
            {"rule": "未分类区域", "severity": "warning", "message": "1处"},
            {"rule": "低可信区", "severity": "error", "message": "1处未复核"},
        ],
    )
    widget.update_state([report], [])
    assert widget.pass_label.text() == "通过项: 1"
    assert widget.warning_label.text() == "警告项: 1"
    assert widget.error_label.text() == "待处理项: 1"


def test_summary_advisory_with_errors(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    report = _make_report(
        rules=["低可信区"],
        issues=[{"rule": "低可信区", "severity": "error", "message": "需复核"}],
    )
    widget.update_state([report], [])
    assert "待处理项" in widget.advisory_label.text()
    assert widget.advisory_label.palette().color(
        widget.advisory_label.foregroundRole()
    ).name() == tokens.ERROR_RED


def test_summary_advisory_all_pass(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    report = _make_report(rules=["层级一致性", "未分类区域"])
    widget.update_state([report], [])
    assert widget.advisory_label.text() == "全部通过，可输出成果"
    assert widget.advisory_label.palette().color(
        widget.advisory_label.foregroundRole()
    ).name() == tokens.SUCCESS


def test_summary_export_list(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    artifacts = [
        ExportArtifact(linked_id="m1", format="GeoTIFF", output_path="/tmp/map.tif"),
        ExportArtifact(linked_id="m1", format="PDF", output_path="/tmp/map.pdf"),
    ]
    widget.update_state([], artifacts)
    labels = [
        self.text()
        for self in (
            widget.export_layout.itemAt(i).widget()
            for i in range(widget.export_layout.count())
        )
        if self is not None
    ]
    assert labels == [
        "• GeoTIFF — /tmp/map.tif",
        "• PDF — /tmp/map.pdf",
    ]


def test_summary_empty_export(qtbot):
    widget = ResultSummary()
    qtbot.addWidget(widget)
    widget.update_state([], [])
    labels = [
        w.text()
        for i in range(widget.export_layout.count())
        for w in [widget.export_layout.itemAt(i).widget()]
        if w is not None
    ]
    assert labels == ["暂无导出图件"]
