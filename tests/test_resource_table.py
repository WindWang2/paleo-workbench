from paleo_workbench.ui.pages.resource_table import ResourceTable


def test_table_has_five_columns(qtbot):
    widget = ResourceTable()
    qtbot.addWidget(widget)
    assert widget.table.columnCount() == 5
    headers = [widget.table.horizontalHeaderItem(i).text() for i in range(5)]
    assert headers == ["文件名", "类型", "格式", "状态", "路径"]


def test_table_update_resources(qtbot):
    widget = ResourceTable()
    qtbot.addWidget(widget)
    resources = [
        type("R", (), {"name": "well1.xlsx", "type": "well_log", "format": "xlsx", "status": "indexed", "path": "/data/well1.xlsx"}),
        type("R", (), {"name": "seismic.sgy", "type": "seismic", "format": "segy", "status": "parsed", "path": "/data/seismic.sgy"}),
    ]
    widget.update_resources(resources)
    assert widget.table.rowCount() == 2
    assert widget.table.item(0, 0).text() == "well1.xlsx"
    assert widget.table.item(0, 1).text() == "测井数据"
    assert widget.table.item(1, 1).text() == "地震数据"


def test_table_empty_state(qtbot):
    widget = ResourceTable()
    qtbot.addWidget(widget)
    widget.update_resources([])
    assert widget.table.rowCount() == 0


def test_table_object_name(qtbot):
    widget = ResourceTable()
    qtbot.addWidget(widget)
    assert widget.objectName() == "ResourceTable"
