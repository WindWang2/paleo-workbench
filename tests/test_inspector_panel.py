from paleo_workbench.project.models import ResourceItem, ExportArtifact
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel


def test_inspector_object_name(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "InspectorPanel"


def test_inspector_resource_rows(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed", crs="EPSG:32649", tags=["ZJ-2", "sand"],
    )
    panel.update_asset(res)
    # Data Manager UI 2.0: identity/location fields live on the 概要 tab.
    texts = [panel.overview_table.item(r, 0).text() for r in range(panel.overview_table.rowCount())]
    assert "逻辑名称" in texts
    assert "路径" in texts
    assert "CRS" in texts


def test_inspector_tags_joined(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(name="x", path="/x", type="well_log", format="LAS", status="ok", tags=["a", "b"])
    panel.update_asset(res)
    # Data Manager UI 2.0: tags render in the dedicated 标签 tab.
    assert panel.tag_container.tags() == ["a", "b"]


def test_inspector_empty_state(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert panel.metadata_table.rowCount() == 0


def test_inspector_artifact_rows(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    art = ExportArtifact(linked_id="m1", format="GeoTIFF", output_path="/out/map.tif")
    panel.update_asset(art)
    # Data Manager UI 2.0: format/output path live on the 概要 tab.
    texts = [panel.overview_table.item(r, 0).text() for r in range(panel.overview_table.rowCount())]
    assert "格式" in texts
    assert "路径" in texts


def test_inspector_key_value_tables_keep_metadata_keys_compact(qtbot):
    """元数据键列有上限，值列获得剩余宽度；表格高度仍按行数收拢。"""
    from PySide6.QtWidgets import QHeaderView

    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed",
    )
    panel.update_asset(res)
    assert panel.overview_table.horizontalHeader().sectionResizeMode(0) == (
        QHeaderView.ResizeMode.ResizeToContents
    )
    for table in (
        panel.governance_table,
        panel.catalog_metadata_table,
        panel.metadata_table,
    ):
        assert table.horizontalHeader().sectionResizeMode(0) == (
            QHeaderView.ResizeMode.Interactive
        )
        assert table.horizontalHeader().sectionResizeMode(1) == (
            QHeaderView.ResizeMode.Stretch
        )
        assert table.columnWidth(0) <= 156
    assert panel.metadata_table.maximumHeight() <= 340
    # 高度必须足够显示 表头 + 全部行（水平滚动条空间已预留）
    rows = panel.metadata_table.rowCount()
    min_needed = (
        panel.metadata_table.horizontalHeader().sizeHint().height() + rows * 28
    )
    assert panel.metadata_table.maximumHeight() >= min_needed
    assert panel.overview_table.maximumHeight() >= 1_000_000  # 概要页不限高


def test_inspector_localizes_geojson_facies_product_metadata(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="result_microfacies.geojson",
        path="/data/result_microfacies.geojson",
        type="geojson",
        format="geojson",
        status="indexed",
        parsed_summary={
            "geojson_valid": True,
            "feature_count": 12,
            "geometry_types": ["Polygon", "MultiPolygon"],
            "geojson_layer_role": "microfacies",
            "geojson_layer_label": "微相",
            "geojson_layer_level": 3,
            "facies_product_group_id": "facies_product_1234",
            "facies_product_complete": True,
            "facies_product_layer_count": 3,
        },
    )

    panel.update_asset(resource)

    rows = {
        panel.metadata_table.item(row, 0).text(): panel.metadata_table.item(row, 1).text()
        for row in range(panel.metadata_table.rowCount())
    }
    assert rows["图层层级"] == "微相"
    assert rows["层级序号"] == "3"
    assert rows["三层成果完整"] == "是"
    assert rows["成果图层数"] == "3"


def test_governance_edit_action_shares_the_governance_header_row(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)

    assert panel.governance_header_layout.indexOf(panel.governance_header_label) == 0
    assert panel.governance_header_layout.indexOf(panel.governance_edit_btn) == 1
    assert panel.governance_edit_btn.text() == "编辑"
    assert panel.governance_edit_btn.accessibleName() == "编辑治理信息"
    assert panel.governance_edit_btn.height() == 18


def test_menu_bar_buttons_hide_dropdown_indicator():
    """顶部菜单条隐藏下拉箭头（箭头与文字重叠回归）。"""
    from paleo_workbench.ui import tokens

    assert "ProjectMenuButton::menu-indicator" in tokens.QSS_TEMPLATE


def test_format_size():
    from paleo_workbench.ui.tokens import format_size
    assert format_size(None) == "—"
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2 K"
    assert format_size(2560) == "2.5 K"
    assert format_size(1048576) == "1 M"
    assert format_size(1572864) == "1.5 M"
