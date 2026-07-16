from paleo_workbench.project.models import PaleoMapDocument, QualityReport
from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.tokens import DEFAULT_QC_RULES


def _make_doc_and_report():
    doc = PaleoMapDocument(name="ZJ-2 图", linked_target_horizon="ZJ-2")
    report = QualityReport(
        linked_map_document_id=doc.id, rules=["层级一致性", "未分类区域"]
    )
    return doc, report


def test_header_object_name(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    assert header.objectName() == "PanelCard"


def test_header_has_action_buttons(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    assert header.run_btn is not None
    assert header.run_btn.objectName() == "PrimaryButton"
    assert header.config_btn is not None
    assert header.config_btn.objectName() == "SecondaryButton"
    assert header.export_btn is not None
    assert header.export_btn.objectName() == "PrimaryButton"
    assert header.finalize_btn is not None
    assert header.finalize_btn.text() == "专家定稿"


def test_header_update_title_horizon(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    doc, report = _make_doc_and_report()
    header.update_state([report], [doc])
    assert "ZJ-2" in header.title_label.text()


def test_header_empty_state(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    header.update_state([], [])
    assert "—" in header.title_label.text()


def test_header_rules_chips(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    doc, report = _make_doc_and_report()
    header.update_state([report], [doc])
    assert "层级一致性" in header.rules_label.text()
    assert "未分类区域" in header.rules_label.text()
    # default rules present before update
    header2 = ActionHeader()
    qtbot.addWidget(header2)
    assert " · ".join(DEFAULT_QC_RULES) in header2.rules_label.text()
