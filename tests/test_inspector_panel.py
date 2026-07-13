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
    texts = [panel.metadata_table.item(r, 0).text() for r in range(panel.metadata_table.rowCount())]
    assert "名称" in texts
    assert "路径" in texts
    assert "CRS" in texts


def test_inspector_tags_joined(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(name="x", path="/x", type="well_log", format="LAS", status="ok", tags=["a", "b"])
    panel.update_asset(res)
    # find the 标签 row value
    for r in range(panel.metadata_table.rowCount()):
        if panel.metadata_table.item(r, 0).text() == "标签":
            assert "a, b" == panel.metadata_table.item(r, 1).text()
            return
    assert False, "标签 row not found"


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
    texts = [panel.metadata_table.item(r, 0).text() for r in range(panel.metadata_table.rowCount())]
    assert "格式" in texts
    assert "输出路径" in texts
