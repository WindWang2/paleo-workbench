from pathlib import Path
import os
import subprocess
import sys
import textwrap

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QTableWidget

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_widgets import RichTextPreviewWidget


def _prepared_well_preview():
    from geoviz import PreparedPreview, PreviewKind

    return PreparedPreview(
        kind=PreviewKind.WELL_LOG,
        title="Professional well",
        payload={"depth": (0.0, 1.0)},
        estimated_bytes=64,
    )


def test_reader_panel_empty_state(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    assert panel.current_mode == "empty"
    assert panel.title_label.text() == "请选择数据项"


def test_reader_panel_defaults_to_local_visualization_provider(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    assert isinstance(panel.provider, LocalVisualizationProvider)


def test_reader_panel_dispatches_prepared_geoviz_preview(qtbot, monkeypatch):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    prepared = _prepared_well_preview()
    rendered = []
    monkeypatch.setattr(panel.geoviz_host, "render", rendered.append)

    panel.render(
        PreviewResult(
            mode="geoviz",
            title="well.las",
            engine_preview=prepared,
            estimated_bytes=prepared.estimated_bytes,
        )
    )

    assert rendered == [prepared]
    assert panel.stack.currentWidget() is panel.geoviz_host


def test_reader_panel_clears_stale_geoviz_before_non_geoviz_states(qtbot, monkeypatch):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    clears = []
    monkeypatch.setattr(panel.geoviz_host, "clear", lambda: clears.append("clear"))

    panel.show_loading()
    panel.render(PreviewResult(mode="message", title="failure", message="failed"))
    panel.render(PreviewResult(mode="empty", title="empty"))
    panel.render(PreviewResult(mode="text", title="fallback", text="ordinary"))

    assert clears == ["clear", "clear", "clear", "clear"]


def test_reader_panel_rejects_non_prepared_geoviz_payload_and_clears_stale_widget(
    qtbot, monkeypatch
):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    clears = []
    modes = []
    panel.reader_mode_changed.connect(modes.append)
    monkeypatch.setattr(panel.geoviz_host, "clear", lambda: clears.append("clear"))

    panel.render(
        PreviewResult(mode="geoviz", title="bad", engine_preview={"widget": object()})
    )

    assert clears == ["clear"]
    assert panel.stack.currentWidget() is panel.message_label
    assert panel.current_mode == "message"
    assert modes == ["message"]
    assert "预览不可用" in panel.message_label.text()


def test_reader_panel_releases_all_engine_widgets(qtbot, monkeypatch):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    releases = []
    monkeypatch.setattr(panel.geoviz_host, "release_all", lambda: releases.append("all"))

    panel.release_engine_widgets()

    assert releases == ["all"]


def test_reader_panel_dispatches_web_document(tmp_path):
    path = tmp_path / "page.html"
    script = textwrap.dedent(
        f"""
        import sys
        import types
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

        class FakeWidget(QWidget):
            def set_message(self, text):
                self.message = text

        class FakePdfWidget(FakeWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.fallback_image = QLabel(self)
                self.prev_btn = QPushButton(self)
                self.next_btn = QPushButton(self)
                self.page_label = QLabel(self)

        class FakeWebDocumentWidget(FakeWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.path = ""
                self.html = ""

            def load_document(self, path, html=""):
                self.path = path
                self.html = html

        widgets = types.ModuleType("paleo_workbench.ui.pages.preview_widgets")
        for name in (
            "GeoTiffPreviewWidget", "ImagePreviewWidget", "JsonTreePreviewWidget",
            "MediaPreviewWidget", "MessagePreviewWidget", "RichTextPreviewWidget",
            "SummaryTablePreviewWidget", "TablePreviewWidget", "TextPreviewWidget",
        ):
            setattr(widgets, name, FakeWidget)
        widgets.PdfPreviewWidget = FakePdfWidget
        widgets.WebDocumentPreviewWidget = FakeWebDocumentWidget
        sys.modules[widgets.__name__] = widgets

        from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
        from paleo_workbench.ui.pages.preview_provider import PreviewResult

        app = QApplication([])
        panel = DataReaderPanel()
        panel.render(PreviewResult(
            mode="web_document",
            title="page.html",
            path={path.as_posix()!r},
            rich_html="<h1>Rendered document</h1>",
        ))
        assert panel.stack.currentWidget() is panel.web_document_preview
        assert panel.web_document_preview.path == {path.as_posix()!r}
        assert panel.web_document_preview.html == "<h1>Rendered document</h1>"
        app.quit()
        """
    )
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr


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


def test_reader_panel_renders_well_log_summary(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="well_log",
            title="well.las",
            summary_rows=(("井名", "A1"), ("曲线数", "2")),
            table_headers=("曲线", "单位"),
            table_rows=(("GR", "API"), ("RHOB", "G/C3")),
        )
    )

    assert panel.current_mode == "well_log"
    assert panel.well_log_preview.summary_table.item(0, 1).text() == "A1"
    assert panel.well_log_preview.detail_table.item(0, 0).text() == "GR"


def test_reader_panel_renders_seismic_summary_message(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="seismic",
            title="cube.sgy",
            message="地震数据预览需要 SEG-Y 支持库或地震工作流打开",
            summary_rows=(("文件", "cube.sgy"), ("格式", "sgy")),
        )
    )

    assert panel.current_mode == "seismic"
    assert "SEG-Y" in panel.seismic_preview.message_label.text()


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


def test_reader_panel_pdf_prefers_preloaded_bytes(qtbot, monkeypatch, tmp_path: Path):
    """When pdf_bytes are present, load from buffer instead of reopening the path."""
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfView", None)
    loads: list[object] = []

    class FakePdfDocument:
        class Error:
            None_ = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def load(self, source) -> int:
            loads.append(source)
            return self.Error.None_

        def pageCount(self) -> int:
            return 1

        def render(self, page: int, size) -> QImage:
            return QImage(size.width(), size.height(), QImage.Format.Format_RGB32)

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.preview_widgets.QPdfDocument", FakePdfDocument
    )
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    pdf_path = tmp_path / "report.pdf"
    payload = b"%PDF-1.4\n%%EOF\n"
    pdf_path.write_bytes(payload)

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            pdf_bytes=payload,
        )
    )

    assert len(loads) == 1
    assert not isinstance(loads[0], str)


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


def test_reader_panel_degrades_when_qpdfdocument_is_unavailable(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", None)
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
    assert panel.pdf_widget.fallback_image.isVisible()
    assert "PDF 预览不可用" in panel.pdf_widget.fallback_image.text()
    assert panel.pdf_page_label.text() == "0 / 0"
    assert not panel.pdf_prev_btn.isEnabled()
    assert not panel.pdf_next_btn.isEnabled()
    assert panel.pdf_widget.pdf_view is None


def test_reader_panel_pdf_page_controls_noop_when_qpdfdocument_is_unavailable(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr("paleo_workbench.ui.pages.preview_widgets.QPdfDocument", None)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.next_pdf_page()
    panel.previous_pdf_page()

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


def test_reader_panel_rich_text_dispatch(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="rich_text", title="t", rich_html="<p>hi</p>"))
    assert isinstance(panel.stack.currentWidget(), RichTextPreviewWidget)


def test_reader_panel_json_tree_dispatch(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="json_tree", title="t", json_payload={"a": 1}))
    current = panel.stack.currentWidget()
    from paleo_workbench.ui.pages.preview_widgets import JsonTreePreviewWidget

    assert isinstance(current, JsonTreePreviewWidget)
    # Payload should have been loaded into the model.
    assert current.model().rowCount() == 1
    assert current.model().item(0, 0).text() == "a"
    assert current.model().item(0, 1).text() == "1"


def test_reader_panel_geotiff_dispatch(qtbot):
    """geotiff mode routes to GeoTiffPreviewWidget with bytes + metadata."""
    from PIL import Image
    import io
    import numpy as np
    buf = io.BytesIO()
    Image.fromarray(np.zeros((4, 4, 3), dtype="uint8")).save(buf, format="PNG")
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="geotiff",
            title="dem.tif",
            path="dem.tif",
            format="tif",
            image_bytes=buf.getvalue(),
            geo_metadata=(("CRS", "EPSG:32649"), ("尺寸", "10 × 10 × 1")),
        )
    )

    assert panel.current_mode == "geotiff"
    current = panel.stack.currentWidget()
    from paleo_workbench.ui.pages.preview_widgets import GeoTiffPreviewWidget

    assert isinstance(current, GeoTiffPreviewWidget)
    assert current.summary_table.rowCount() == 2
    assert current.summary_table.item(0, 0).text() == "CRS"
    assert current.summary_table.item(0, 1).text() == "EPSG:32649"
    assert current.pixmap() is not None and not current.pixmap().isNull()


def test_reader_panel_media_dispatch(qtbot, tmp_path: Path):
    """media mode routes to MediaPreviewWidget and forwards media_path.

    QMediaPlayer playback state is unreliable under offscreen/no-backend, so we
    assert only that the stack switched and the path was forwarded (NOT that
    playback started or the player reached a particular state).
    """
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"\x00" * 64)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="media",
            title="clip.wav",
            path=str(clip),
            format="wav",
            media_path=str(clip),
        )
    )

    assert panel.current_mode == "media"
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    current = panel.stack.currentWidget()
    assert isinstance(current, MediaPreviewWidget)
    # The path was forwarded to the widget. We do NOT assert on playback state —
    # QMediaPlayer may emit errorOccurred under offscreen and disable play.
    assert panel.media_preview is current


def test_reader_panel_media_dispatch_via_provider(qtbot, tmp_path: Path):
    """An audio resource flows through the provider into the media widget."""
    clip = tmp_path / "note.mp3"
    clip.write_bytes(b"\x00" * 64)
    resource = ResourceItem(
        name="note.mp3", path=str(clip), type="unknown", format="mp3", status="parsed"
    )
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.update_asset(resource)

    assert panel.current_mode == "media"
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    assert isinstance(panel.stack.currentWidget(), MediaPreviewWidget)
