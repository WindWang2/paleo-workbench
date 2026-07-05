from paleo_workbench.ui.pages.home_page import HomePage


def test_home_page_assembles_sub_widgets(qtbot):
    page = HomePage()
    qtbot.addWidget(page)
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
