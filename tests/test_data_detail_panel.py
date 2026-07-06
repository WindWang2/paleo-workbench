from PySide6.QtWidgets import QLabel

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_detail_panel import DataDetailPanel


def _labels(panel):
    return [label.text() for label in panel.findChildren(QLabel)]


def test_detail_panel_empty_state(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)

    assert "请选择数据项" in _labels(panel)


def test_detail_panel_resource_metadata(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="well.las",
        path="/tmp/well.las",
        type="well_log",
        format="las",
        checksum="abc",
    )

    panel.update_asset(resource)

    texts = "\n".join(_labels(panel))
    assert "well.las" in texts
    assert "abc" in texts
    assert "测井" in texts or "well_log" in texts


def test_detail_panel_artifact_metadata(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    artifact = ExportArtifact(
        linked_id="map_1",
        format="PDF",
        output_path="/tmp/map.pdf",
    )

    panel.update_asset(artifact)

    assert "map.pdf" in "\n".join(_labels(panel))
