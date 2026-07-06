from PySide6.QtGui import QImage
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


def test_detail_panel_renders_image_thumbnail(qtbot, tmp_path):
    image_path = tmp_path / "map.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    image.save(image_path.as_posix())
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="map.png",
        path=image_path.as_posix(),
        type="image_reference",
        format="png",
    )

    panel.update_asset(resource)

    pixmap_labels = [
        label for label in panel.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert pixmap_labels


def test_detail_panel_invalid_image_shows_warning(qtbot, tmp_path):
    image_path = tmp_path / "bad.png"
    image_path.write_text("not an image", encoding="utf-8")
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="bad.png",
        path=image_path.as_posix(),
        type="image_reference",
        format="png",
    )

    panel.update_asset(resource)

    assert "图片预览加载失败" in "\n".join(_labels(panel))


def test_detail_panel_renders_text_preview_lines(qtbot, tmp_path):
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="notes.txt",
        path=text_path.as_posix(),
        type="document",
        format="txt",
    )

    panel.update_asset(resource)

    texts = "\n".join(_labels(panel))
    assert "alpha" in texts
    assert "beta" in texts
