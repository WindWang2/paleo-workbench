from PySide6.QtGui import QImage, QPainter, QPdfWriter
from PySide6.QtWidgets import QLabel, QPushButton

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_detail_panel import DataDetailPanel


def _labels(panel):
    return [label.text() for label in panel.findChildren(QLabel)]


def _write_two_page_pdf(path):
    writer = QPdfWriter(path.as_posix())
    painter = QPainter(writer)
    painter.drawText(100, 100, "Page 1")
    writer.newPage()
    painter.drawText(100, 100, "Page 2")
    painter.end()


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


def test_detail_panel_renders_pdf_view(qtbot, tmp_path):
    pdf_path = tmp_path / "report.pdf"
    _write_two_page_pdf(pdf_path)
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="report.pdf",
        path=pdf_path.as_posix(),
        type="document",
        format="pdf",
    )

    panel.update_asset(resource)

    pixmap_labels = [
        label for label in panel.findChildren(QLabel)
        if label.objectName() == "DataPreviewPdf"
        and label.pixmap() is not None
        and not label.pixmap().isNull()
    ]
    assert pixmap_labels


def test_detail_panel_pdf_preview_can_page_up_and_down(qtbot, tmp_path):
    pdf_path = tmp_path / "report.pdf"
    _write_two_page_pdf(pdf_path)
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="report.pdf",
        path=pdf_path.as_posix(),
        type="document",
        format="pdf",
    )

    panel.update_asset(resource)

    page_label = panel.findChild(QLabel, "DataPreviewPdfPageLabel")
    next_button = panel.findChild(QPushButton, "DataPreviewPdfNext")
    prev_button = panel.findChild(QPushButton, "DataPreviewPdfPrevious")
    assert page_label is not None
    assert next_button is not None
    assert prev_button is not None
    assert page_label.text() == "1 / 2"

    next_button.click()
    assert page_label.text() == "2 / 2"

    prev_button.click()
    assert page_label.text() == "1 / 2"


def test_detail_panel_invalid_pdf_shows_warning(qtbot, tmp_path):
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_text("not a pdf", encoding="utf-8")
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(
        name="bad.pdf",
        path=pdf_path.as_posix(),
        type="document",
        format="pdf",
    )

    panel.update_asset(resource)

    assert "PDF预览加载失败" in "\n".join(_labels(panel))
