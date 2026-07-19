from paleo_workbench.ui.pages.home_page import HomePage


def test_home_page_assembles_sub_widgets(qtbot):
    from PySide6.QtWidgets import QApplication
    page = HomePage()
    qtbot.addWidget(page)
    page.show()
    QApplication.processEvents()
    assert page.workflow_progress is not None
    assert page.activity_card is not None
    assert page.completeness_card is not None


def test_home_page_update_state_delegates(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
    steps = [
        type("S", (), {"step_type": "data_check", "status": "complete"}),
        type("S", (), {"step_type": "factor_map", "status": "pending"}),
        type("S", (), {"step_type": "prediction", "status": "pending"}),
        type("S", (), {"step_type": "map_compile", "status": "pending"}),
        type("S", (), {"step_type": "qc", "status": "pending"}),
        type("S", (), {"step_type": "export", "status": "pending"}),
    ]
    state = {"resource_readiness": {"ready": True, "missing_types": []}}
    page.update_state(state, steps)
    assert "完成" in page.workflow_progress.step_widgets[0]["status"].text()
    assert page.activity_card.entry_count() == 1
    assert "数据完整" in page.completeness_card.summary_label.text()


def test_home_page_object_name(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
    assert page.objectName() == "HomePage"


def test_home_page_relationship_widget_emits_navigation(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
    
    assert page.relationship_widget is not None
    assert page.legend is not None
    
    navigated_pages = []
    page.navigation_requested.connect(navigated_pages.append)
    
    page.relationship_widget.card_sequence.clicked.emit(4)
    assert navigated_pages == [4]
