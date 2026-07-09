from pathlib import Path

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QTableWidget

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def test_reader_panel_empty_state(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    assert panel.current_mode == "empty"
    assert panel.title_label.text() == "请选择数据项"


def test_reader_panel_renders_text_resource(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("line 1\nline 2", encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.update_asset(resource)

    assert panel.current_mode == "text"
    assert "line 1" in panel.text_preview.toPlainText()


def test_reader_panel_renders_table_resource(qtbot, tmp_path: Path):
    path = tmp_path / "table.csv"
    path.write_text("a,b\n1,2", encoding="utf-8")
    resource = ResourceItem(name="table.csv", path=str(path), type="tabular", format="csv")
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.update_asset(resource)

    assert panel.current_mode == "table"
    table = panel.table_preview
    assert isinstance(table, QTableWidget)
    assert table.rowCount() == 1
    assert table.columnCount() == 2


def test_reader_panel_renders_missing_message(qtbot, tmp_path: Path):
    resource = ResourceItem(
        name="missing.txt",
        path=str(tmp_path / "missing.txt"),
        type="document",
        format="txt",
    )
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.update_asset(resource)

    assert panel.current_mode == "message"
    labels = panel.findChildren(QLabel)
    assert any("文件不存在" in label.text() for label in labels)


def test_reader_panel_uses_pdf_preview_widget(qtbot, tmp_path: Path):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
        )
    )

    assert panel.current_mode == "pdf"
    assert panel.pdf_preview_widget is panel.pdf_widget
    assert hasattr(panel.pdf_preview_widget, "pdf_view")


def test_reader_panel_rerenders_image_preview_on_resize(qtbot, monkeypatch, tmp_path: Path):
    path = tmp_path / "map.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    image.save(path.as_posix())
    resource = ResourceItem(name="map.png", path=str(path), type="image_reference", format="png")
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    calls = []
    original = panel.image_preview_widget.render_current

    def tracking_render() -> None:
        calls.append(panel.image_preview_widget._path)
        original()

    monkeypatch.setattr(panel.image_preview_widget, "render_current", tracking_render)

    panel.update_asset(resource)
    initial = panel.image_label.pixmap().size()
    panel.resize(760, 520)
    qtbot.wait(50)

    assert len(calls) >= 2
    assert calls[-1] == str(path)
    assert panel.image_label.pixmap().size().width() >= initial.width()


def test_reader_panel_rerenders_pdf_preview_on_resize_without_reloading_document(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", None)
    renders = []
    loads = []

    class FakePdfDocument:
        class Error:
            None_ = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def load(self, path: str) -> int:
            loads.append(path)
            return self.Error.None_

        def pageCount(self) -> int:
            return 1

        def render(self, page: int, size) -> QImage:
            renders.append((page, size.width(), size.height()))
            return QImage(size.width(), size.height(), QImage.Format.Format_RGB32)

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
        )
    )

    assert loads == [str(pdf_path)]
    assert renders
    assert panel.pdf_preview_widget is panel.pdf_widget

    panel.resize(780, 600)
    qtbot.wait(50)

    assert loads == [str(pdf_path)]
    assert len(renders) >= 2
    assert renders[-1][1] > renders[0][1]


def test_reader_panel_uses_qpdfview_branch_for_successful_pdf_load(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    class FakeNavigator:
        def __init__(self) -> None:
            self.jumps = []

        def currentZoom(self) -> float:
            return 1.5

        def jump(self, page: int, location, zoom: float) -> None:
            self.jumps.append((page, location, zoom))

    class FakePdfView(QLabel):
        class PageMode:
            SinglePage = "single-page"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.document = None
            self.page_mode = None
            self.navigator = FakeNavigator()

        def setDocument(self, document) -> None:
            self.document = document

        def setPageMode(self, mode) -> None:
            self.page_mode = mode

        def pageNavigator(self) -> FakeNavigator:
            return self.navigator

    class FakePdfDocument:
        class Error:
            None_ = 0

        def __init__(self, *_args, **_kwargs):
            self.loaded_paths = []

        def load(self, path: str) -> int:
            self.loaded_paths.append(path)
            return self.Error.None_

        def pageCount(self) -> int:
            return 3

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", FakePdfView)
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
        )
    )

    assert panel.current_mode == "pdf"
    assert panel.pdf_preview_widget.pdf_view is panel.pdf_widget.pdf_view
    assert panel.pdf_widget.pdf_view.document is panel.pdf_widget.document
    assert panel.pdf_widget.document.loaded_paths == [str(pdf_path)]
    assert panel.pdf_widget.pdf_view.page_mode == FakePdfView.PageMode.SinglePage
    assert panel.pdf_widget.pdf_view.navigator.jumps
    assert panel.pdf_widget.pdf_view.isVisible()
    assert not panel.pdf_widget.fallback_image.isVisible()


def test_reader_panel_shows_failure_message_when_qpdfview_load_fails(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    class FakeNavigator:
        def currentZoom(self) -> float:
            return 1.0

        def jump(self, *_args) -> None:
            raise AssertionError("jump should not be called for failed loads")

    class FakePdfView(QLabel):
        class PageMode:
            SinglePage = "single-page"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.navigator = FakeNavigator()

        def setDocument(self, document) -> None:
            self.document = document

        def setPageMode(self, mode) -> None:
            self.page_mode = mode

        def pageNavigator(self) -> FakeNavigator:
            return self.navigator

    class FakePdfDocument:
        class Error:
            None_ = 0
            DataNotYetAvailable = 1

        def __init__(self, *_args, **_kwargs):
            pass

        def load(self, _path: str) -> int:
            return self.Error.DataNotYetAvailable

        def pageCount(self) -> int:
            return 0

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", FakePdfView)
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    panel.render(
        PreviewResult(
            mode="pdf",
            title="broken.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
        )
    )

    assert panel.current_mode == "pdf"
    assert panel.pdf_widget.fallback_image.isVisible()
    assert "PDF 预览加载失败" in panel.pdf_widget.fallback_image.text()
    assert not panel.pdf_widget.pdf_view.isVisible()
    assert panel.pdf_page_label.text() == "0 / 0"
    assert not panel.pdf_prev_btn.isEnabled()
    assert not panel.pdf_next_btn.isEnabled()


def test_reader_panel_keeps_failed_qpdfview_state_for_same_path_and_revision(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    class FakeNavigator:
        def __init__(self) -> None:
            self.jump_calls = []

        def currentZoom(self) -> float:
            return 1.0

        def jump(self, *args) -> None:
            self.jump_calls.append(args)

    class FakePdfView(QLabel):
        class PageMode:
            SinglePage = "single-page"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.navigator = FakeNavigator()

        def setDocument(self, document) -> None:
            self.document = document

        def setPageMode(self, mode) -> None:
            self.page_mode = mode

        def pageNavigator(self) -> FakeNavigator:
            return self.navigator

    class FakePdfDocument:
        class Error:
            None_ = 0
            DataNotYetAvailable = 1

        def __init__(self, *_args, **_kwargs):
            self.load_calls = []

        def load(self, path: str) -> int:
            self.load_calls.append(path)
            return self.Error.DataNotYetAvailable

        def pageCount(self) -> int:
            return 0

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", FakePdfView)
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = PreviewResult(
        mode="pdf",
        title="broken.pdf",
        path=str(pdf_path),
        format="pdf",
        status="indexed",
        type_label="document",
        revision=(12, 100),
    )

    panel.render(result)
    panel.render(result)

    assert panel.current_mode == "pdf"
    assert panel.pdf_widget.document.load_calls == [str(pdf_path)]
    assert panel.pdf_widget.fallback_image.isVisible()
    assert "PDF 预览加载失败" in panel.pdf_widget.fallback_image.text()
    assert not panel.pdf_widget.pdf_view.isVisible()
    assert panel.pdf_page_label.text() == "0 / 0"
    assert not panel.pdf_prev_btn.isEnabled()
    assert not panel.pdf_next_btn.isEnabled()
    assert panel.pdf_widget.pdf_view.navigator.jump_calls == []


def test_reader_panel_reload_image_preview_when_same_path_stat_stays_constant_but_checksum_changes(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    path = tmp_path / "map.png"
    first = QImage(16, 16, QImage.Format.Format_RGB32)
    first.fill(0xCC3300)
    first.save(path.as_posix())
    resource = ResourceItem(
        name="map.png",
        path=str(path),
        type="image_reference",
        format="png",
        checksum="checksum-1",
    )
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    monkeypatch.setattr(panel.provider, "_safe_stat", lambda _path: (12, 100))

    panel.update_asset(resource)
    initial_color = panel.image_label.pixmap().toImage().pixelColor(8, 8).rgb()

    updated = QImage(16, 16, QImage.Format.Format_RGB32)
    updated.fill(0x0066CC)
    updated.save(path.as_posix())
    resource.checksum = "checksum-2"

    panel.update_asset(resource)
    refreshed_color = panel.image_label.pixmap().toImage().pixelColor(8, 8).rgb()

    assert refreshed_color != initial_color


def test_reader_panel_reload_pdf_when_same_path_revision_changes_but_not_on_resize(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", None)
    loads = []

    class FakePdfDocument:
        class Error:
            None_ = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def load(self, path: str) -> int:
            loads.append(path)
            return self.Error.None_

        def pageCount(self) -> int:
            return 1

        def render(self, page: int, size) -> QImage:
            return QImage(size.width(), size.height(), QImage.Format.Format_RGB32)

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
            revision=(12, 100),
        )
    )
    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
            revision=(12, 200),
        )
    )

    assert loads == [str(pdf_path), str(pdf_path)]

    panel.resize(780, 600)
    qtbot.wait(50)

    assert loads == [str(pdf_path), str(pdf_path)]


def test_reader_panel_clears_old_pdf_fallback_pixmap_after_render_failure(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", None)

    class FakePdfDocument:
        class Error:
            None_ = 0

        def __init__(self, *_args, **_kwargs):
            self.render_calls = 0

        def load(self, _path: str) -> int:
            return self.Error.None_

        def pageCount(self) -> int:
            return 1

        def render(self, _page: int, size) -> QImage:
            self.render_calls += 1
            return QImage()

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.resize(420, 320)
    panel.show()
    qtbot.waitExposed(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    stale_pixmap = QPixmap(12, 12)
    stale_pixmap.fill(0x224466)
    panel.pdf_widget.fallback_image.setPixmap(stale_pixmap)

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
            revision=(12, 200),
        )
    )

    pixmap = panel.pdf_widget.fallback_image.pixmap()
    assert pixmap is None or pixmap.isNull()
    assert "PDF 页面渲染失败" in panel.pdf_widget.fallback_image.text()
