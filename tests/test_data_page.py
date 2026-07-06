from paleo_workbench.ui.pages.data_page import DataPage


def test_data_page_assembles_sub_widgets(qtbot):
    from paleo_workbench.ui.pages.action_panel import ActionPanel

    page = DataPage()
    qtbot.addWidget(page)
    assert page.summary_bar is not None
    assert page.resource_table is not None
    assert isinstance(page.action_panel, ActionPanel)


def test_data_page_update_state_delegates(qtbot):
    page = DataPage()
    qtbot.addWidget(page)
    state = {
        "resource_readiness": {
            "available_counts": {"well_log": 5, "seismic": 2, "horizon": 1},
            "missing_types": [],
            "ready": True,
        }
    }
    resources = [
        type("R", (), {"name": "test.xlsx", "type": "well_log", "format": "xlsx", "status": "indexed", "path": "/tmp/test.xlsx"}),
    ]
    page.update_state(state, resources)
    assert page.resource_table.table.rowCount() == 1
    assert "5" in page.summary_bar.type_labels["well_log"].text()


def test_data_page_has_action_buttons(qtbot):
    page = DataPage()
    qtbot.addWidget(page)
    assert page.import_btn is not None
    assert page.convert_btn is not None
    assert page.import_btn.text() == "导入资源"
    assert page.convert_btn.text() == "数据转换"


def test_action_panel_exports_buttons(qtbot):
    from paleo_workbench.ui.pages.action_panel import ActionPanel

    panel = ActionPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "ActionPanel"
    assert panel.import_btn.text() == "导入资源"
    assert panel.convert_btn.text() == "数据转换"


def test_data_page_object_name(qtbot):
    page = DataPage()
    qtbot.addWidget(page)
    assert page.objectName() == "DataPage"
