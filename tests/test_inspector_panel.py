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


def test_inspector_key_value_tables_fit_content(qtbot):
    """键/值表：键列贴合内容不拉伸；元数据页表格高度按行数收拢。"""
    from PySide6.QtWidgets import QHeaderView

    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed",
    )
    panel.update_asset(res)
    for table in (
        panel.overview_table,
        panel.governance_table,
        panel.catalog_metadata_table,
        panel.metadata_table,
    ):
        assert table.horizontalHeader().sectionResizeMode(0) == (
            QHeaderView.ResizeMode.ResizeToContents
        )
    assert panel.metadata_table.maximumHeight() <= 320
    assert panel.overview_table.maximumHeight() >= 1_000_000  # 概要页不限高


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

