from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable


def table_text(table_widget, row: int, column: int) -> str:
    model = table_widget.table.model()
    return model.data(model.index(row, column)) or ""


def table_row_count(table_widget) -> int:
    return table_widget.table.model().rowCount()


def table_headers(table_widget) -> list[str]:
    model = table_widget.table.model()
    return [
        model.headerData(i, Qt.Orientation.Horizontal)
        for i in range(model.columnCount())
    ]


def test_asset_table_uses_table_view(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    assert isinstance(table.table, QTableView)
    assert table.table.model() is not None


def test_asset_table_columns(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    assert table_headers(table) == ["文件名", "类型", "格式", "状态", "角色", "大小", "来源", "路径"]


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

    assert table_row_count(table) == 2
    assert table_text(table, 0, 0) == "well.las"
    assert table_text(table, 1, 4) == "成果"


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

    assert table_row_count(table) == 1
    assert table_text(table, 0, 0) == "well.las"


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

    assert table_row_count(table) == 1
    assert table_text(table, 0, 0) == "cube.sgy"


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

    assert table_row_count(table) == 1
    assert table.table.selectionModel().selectedRows() == []
    assert received[-1] is None


def test_asset_table_can_show_selected_columns(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="alpha.txt",
            path="/tmp/alpha.txt",
            type="document",
            format="txt",
        )
    ]

    table.update_assets(resources, [])
    table.set_visible_columns(["name", "format", "path"])

    assert table_headers(table) == ["文件名", "格式", "路径"]
    assert table_text(table, 0, 0) == "alpha.txt"
    assert table_text(table, 0, 1) == "txt"
    assert table_text(table, 0, 2) == "/tmp/alpha.txt"
    assert table.visible_column_keys() == ["name", "format", "path"]


def test_asset_table_keeps_required_name_column(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)

    table.set_visible_columns(["format"])

    assert table.visible_column_keys() == ["name", "format"]
    assert table_headers(table)[0] == "文件名"


def test_asset_table_ignores_unknown_column_keys(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)

    table.set_visible_columns(["name", "bad", "source"])

    assert table.visible_column_keys() == ["name", "source"]


def test_asset_table_reset_columns_restores_defaults(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)

    table.set_visible_columns(["name", "format"])
    table.reset_columns()

    assert table_headers(table) == ["文件名", "类型", "格式", "状态", "角色", "大小", "来源", "路径"]


def test_asset_table_search_matches_hidden_columns(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="alpha.txt",
            path="/tmp/alpha.txt",
            type="document",
            format="txt",
            source="survey",
        )
    ]

    table.update_assets(resources, [])
    table.set_visible_columns(["name"])
    table.set_search_text("survey")

    assert table_row_count(table) == 1
    assert table.table.model().columnCount() == 1
    assert table_text(table, 0, 0) == "alpha.txt"


def test_asset_table_preserves_selection_after_column_change(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="alpha.txt",
            path="/tmp/alpha.txt",
            type="document",
            format="txt",
        )
    ]
    received = []
    table.selected_asset_changed.connect(received.append)

    table.update_assets(resources, [])
    table.table.selectRow(0)
    table.set_visible_columns(["name", "format"])

    assert table.table.selectionModel().selectedRows()[0].row() == 0
    assert received[-1] == resources[0]


def test_asset_table_handles_2000_assets(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name=f"well_{i}.las",
            path=f"/tmp/well_{i}.las",
            type="well_log",
            format="las",
        )
        for i in range(2000)
    ]
    table.update_assets(resources, [])
    assert table_row_count(table) == 2000
    assert table_text(table, 0, 0) == "well_0.las"
    assert table_text(table, 1999, 0) == "well_1999.las"
    # Virtual QTableView has no per-cell QTableWidgetItem API.
    assert not hasattr(table.table, "item") or not callable(getattr(table.table, "item", None))


def test_asset_table_filter_scale_search_without_preview(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name=f"well_{i}.las",
            path=f"/tmp/well_{i}.las",
            type="well_log",
            format="las",
        )
        for i in range(2000)
    ]
    table.update_assets(resources, [])
    # Direct API stays immediate (debounce is only on toolbar textChanged).
    table.set_search_text("well_1999")

    assert table_row_count(table) == 1
    assert table.visible_asset_count() == 1
    assert table_text(table, 0, 0) == "well_1999.las"
