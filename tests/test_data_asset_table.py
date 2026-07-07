from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable


def test_asset_table_columns(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    headers = [
        table.table.horizontalHeaderItem(i).text()
        for i in range(table.table.columnCount())
    ]
    assert headers == ["文件名", "类型", "格式", "状态", "角色", "大小", "来源", "路径"]


def test_asset_table_renders_resources_and_artifacts(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
            parsed_summary={"size_bytes": 10},
        )
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    table.update_assets(resources, artifacts)

    assert table.table.rowCount() == 2
    assert table.table.item(0, 0).text() == "well.las"
    assert table.table.item(1, 4).text() == "成果"


def test_asset_table_filters_by_category(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        ),
        ResourceItem(
            name="cube.sgy",
            path="/tmp/cube.sgy",
            type="seismic",
            format="sgy",
        ),
    ]
    table.update_assets(resources, [])
    table.set_category("测井")

    assert table.table.rowCount() == 1
    assert table.table.item(0, 0).text() == "well.las"


def test_asset_table_filters_by_search(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        ),
        ResourceItem(
            name="cube.sgy",
            path="/tmp/cube.sgy",
            type="seismic",
            format="sgy",
        ),
    ]
    table.update_assets(resources, [])
    table.set_search_text("cube")

    assert table.table.rowCount() == 1
    assert table.table.item(0, 0).text() == "cube.sgy"


def test_data_asset_table_visible_asset_count_after_search(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="alpha.txt",
            path="/tmp/alpha.txt",
            type="document",
            format="txt",
        ),
        ResourceItem(
            name="beta.txt",
            path="/tmp/beta.txt",
            type="document",
            format="txt",
        ),
    ]

    table.update_assets(resources, [])
    table.set_search_text("alpha")

    assert table.visible_asset_count() == 1


def test_asset_table_clears_selection_when_search_hides_selected_row(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="alpha.txt",
            path="/tmp/alpha.txt",
            type="document",
            format="txt",
        ),
        ResourceItem(
            name="beta.txt",
            path="/tmp/beta.txt",
            type="document",
            format="txt",
        ),
    ]
    received = []
    table.selected_asset_changed.connect(received.append)

    table.update_assets(resources, [])
    table.table.selectRow(0)
    table.set_search_text("beta")

    assert table.table.rowCount() == 1
    assert table.table.selectionModel().selectedRows() == []
    assert received[-1] is None
