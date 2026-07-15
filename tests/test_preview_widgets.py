import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtGui import QPainter, QPdfWriter

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider
from paleo_workbench.ui.pages.preview_widgets import (
    GeoTiffPreviewWidget,
    JsonTreePreviewWidget,
    PdfPreviewWidget,
    RichTextPreviewWidget,
    WebDocumentPreviewWidget,
    _LocalOnlyPage,
    _LocalOnlyRequestInterceptor,
)


def test_rich_text_widget_loads_html(qtbot):
    w = RichTextPreviewWidget()
    qtbot.addWidget(w)
    w.load_html("<h1>Title</h1><p>Body</p>")
    # QTextBrowser exposes its content via toHtml()
    assert "<h1" in w.toHtml().lower() or "title" in w.toHtml().lower()


def test_web_document_widget_loads_local_file(tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<h1>Page</h1>", encoding="utf-8")

    class FakeEngineView:
        def load(self, url) -> None:
            self.loaded_url = url

        def setHtml(self, html, base_url) -> None:
            self.html = html
            self.base_url = base_url

    # WebDocumentPreviewWidget delegates to self._engine_view
    widget = SimpleNamespace(_engine_view=FakeEngineView())

    WebDocumentPreviewWidget.load_document(widget, path.as_posix())

    assert widget._engine_view.loaded_url.isLocalFile()
    assert widget._engine_view.loaded_url.toLocalFile() == path.as_posix()


def test_web_document_widget_loads_html_with_source_directory_base_url(tmp_path):
    path = tmp_path / "documents" / "page.md"

    class FakeEngineView:
        def load(self, url) -> None:
            self.loaded_url = url

        def setHtml(self, html, base_url) -> None:
            self.html = html
            self.base_url = base_url

    widget = SimpleNamespace(_engine_view=FakeEngineView())

    WebDocumentPreviewWidget.load_document(widget, path.as_posix(), "<h1>Page</h1>")

    assert widget._engine_view.html == "<h1>Page</h1>"
    assert widget._engine_view.base_url.isLocalFile()
    assert widget._engine_view.base_url.toLocalFile() == f"{path.parent.as_posix()}/"


def test_local_only_request_interceptor_blocks_non_local_schemes():
    class FakeRequestInfo:
        def __init__(self, url):
            self._url = url
            self.blocked = False

        def requestUrl(self):
            return self._url

        def block(self, blocked):
            self.blocked = blocked

    allowed_urls = (
        "file:///tmp/page.html",
        "data:text/html,Page",
        "about:blank",
        "blob:file:///tmp/bundled-asset",
    )
    blocked_urls = (
        "http://example.com",
        "https://example.com",
        "ftp://example.com",
        "mailto:x@example.com",
        "javascript:alert(1)",
        "qrc:/resource.html",
        "custom-scheme:value",
        "relative/path.html",
    )
    interceptor = SimpleNamespace(
        _ALLOWED_SCHEMES=_LocalOnlyRequestInterceptor._ALLOWED_SCHEMES,
    )

    for url in allowed_urls:
        info = FakeRequestInfo(QUrl(url))
        _LocalOnlyRequestInterceptor.interceptRequest(interceptor, info)
        assert info.blocked is False

    for url in blocked_urls:
        info = FakeRequestInfo(QUrl(url))
        _LocalOnlyRequestInterceptor.interceptRequest(interceptor, info)
        assert info.blocked is True


def test_local_only_page_rejects_remote_navigation():
    allowed_urls = (
        "file:///tmp/page.html",
        "data:text/html,Page",
        "about:blank",
        "blob:file:///tmp/bundled-asset",
    )
    remote_urls = (
        "http://example.com",
        "https://example.com",
        "ftp://example.com",
        "mailto:x@example.com",
        "javascript:alert(1)",
        "qrc:/resource.html",
        "custom-scheme:value",
        "relative/path.html",
    )
    page = SimpleNamespace(_ALLOWED_SCHEMES=_LocalOnlyPage._ALLOWED_SCHEMES)

    for url in allowed_urls:
        assert _LocalOnlyPage.acceptNavigationRequest(page, QUrl(url), object(), True) is True

    for url in remote_urls:
        assert _LocalOnlyPage.acceptNavigationRequest(page, QUrl(url), object(), True) is False


def test_web_document_widget_configures_local_only_security_without_chromium():
    script = textwrap.dedent(
        """
        import importlib
        import sys
        import types

        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])

        class FakeProfile:
            def __init__(self, parent=None):
                self.parent = parent
                self.interceptor = None

            def setUrlRequestInterceptor(self, interceptor):
                self.interceptor = interceptor

        class FakeInterceptor:
            def __init__(self, parent=None):
                self.parent = parent

        class FakePage:
            def __init__(self, profile, parent=None):
                self.profile = profile
                self.parent = parent

        class FakeSettings:
            def __init__(self):
                self.attributes = {}

            def setAttribute(self, attribute, value):
                self.attributes[attribute] = value

        class FakeWebView(QWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.page = None
                self._settings = FakeSettings()

            def setPage(self, page):
                self.page = page

            def settings(self):
                return self._settings

        webengine_core = types.ModuleType("PySide6.QtWebEngineCore")
        webengine_core.QWebEnginePage = FakePage
        webengine_core.QWebEngineProfile = FakeProfile
        webengine_core.QWebEngineUrlRequestInterceptor = FakeInterceptor
        webengine_core.QWebEngineSettings = type(
            "FakeWebEngineSettings",
            (),
            {"WebAttribute": type("WebAttribute", (), {"LocalContentCanAccessRemoteUrls": "local-remote"})},
        )
        webengine_widgets = types.ModuleType("PySide6.QtWebEngineWidgets")
        webengine_widgets.QWebEngineView = FakeWebView
        sys.modules[webengine_core.__name__] = webengine_core
        sys.modules[webengine_widgets.__name__] = webengine_widgets

        module = importlib.import_module("paleo_workbench.ui.pages.preview_widgets")
        widget = module.WebDocumentPreviewWidget()

        assert widget._profile.parent is widget
        assert widget._interceptor.parent is widget._profile
        assert widget._profile.interceptor is widget._interceptor
        assert widget._page.profile is widget._profile
        assert widget._engine_view.page is widget._page
        assert widget._engine_view.settings().attributes["local-remote"] is False
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


def test_json_tree_builds_from_payload(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.load_payload({"name": "well", "curves": ["GR", "SP"], "meta": {"unit": "m"}}, truncated=False)
    model = w.model()
    assert model.rowCount() == 3  # name, curves, meta


def test_json_tree_collapses_large_array(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    big = list(range(150))
    w.load_payload({"items": big}, truncated=False)
    model = w.model()
    # Row 0 is the "items" key (column 0) and its value item (column 1).
    key_node = model.item(0, 0)
    val_node = model.item(0, 1)
    # Collapsed node shows "[150 items]" in the value column and has 0 children.
    assert val_node.text() == "[150 items]"
    assert key_node.rowCount() == 0


def test_json_tree_lazy_expansion_populates_children(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    big = list(range(150))
    w.load_payload({"items": big}, truncated=False)
    model = w.model()
    key_node = model.item(0, 0)
    assert key_node.rowCount() == 0  # not yet expanded

    # Simulate the user expanding the node.
    w._on_expanded(key_node.index())

    assert key_node.rowCount() == 150
    # First child should be index 0 of the stored list.
    assert key_node.child(0, 0).text() == "0"
    assert key_node.child(0, 1).text() == "0"


def test_json_tree_small_array_expands_inline(qtbot):
    """Arrays under the threshold render children eagerly (no UserRole storage)."""
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.load_payload({"curves": ["GR", "SP", "RHOB"]}, truncated=False)
    model = w.model()
    key_node = model.item(0, 0)
    assert key_node.rowCount() == 3
    assert key_node.child(0, 0).text() == "0"
    assert key_node.child(0, 1).text() == "GR"


def test_geotiff_widget_loads_metadata(qtbot):
    # Build a 4x4 PNG so image_bytes is valid.
    from PIL import Image
    import io
    import numpy as np
    buf = io.BytesIO()
    Image.fromarray(np.zeros((4, 4, 3), dtype="uint8")).save(buf, format="PNG")
    w = GeoTiffPreviewWidget()
    qtbot.addWidget(w)
    w.load(
        "x.tif",
        None,
        buf.getvalue(),
        (("CRS", "EPSG:32649"), ("尺寸", "10 × 10 × 1")),
    )
    assert w.summary_table.rowCount() == 2
    # Thumbnail QLabel should now hold a pixmap (decoded from PNG bytes).
    assert w.pixmap() is not None


def test_pdf_widget_loads_relative_path_from_reopened_project(qtbot, tmp_path):
    project_path = tmp_path / "demo.paleo.json"
    pdf_path = tmp_path / "documents" / "report.pdf"
    pdf_path.parent.mkdir()
    writer = QPdfWriter(pdf_path.as_posix())
    painter = QPainter(writer)
    painter.drawText(100, 100, "Preview")
    painter.end()
    project = ProjectDocument.new("Demo")
    project.resources.append(
        ResourceItem(
            name="report.pdf",
            path=pdf_path.as_posix(),
            type="document",
            format="pdf",
        )
    )
    manager = ProjectManager(project_path)
    manager.save(project)
    resource = manager.load().resources[0]
    result = PreviewProvider().preview(resource)

    widget = PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.load(result.path, result.revision)

    assert result.mode == "pdf"
    assert widget.page_label.text() == "1 / 1"
    assert widget.fallback_image.text() != "PDF 预览加载失败"


def test_media_widget_constructs(qtbot):
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    w.set_media_path("")  # no crash on empty path
    assert w.play_btn.text() == "播放"


def test_media_widget_loads_path_sets_ready(qtbot):
    """A real path sets status to 就绪 and enables the play button.

    Only asserts construction + label text; QMediaPlayer playback state is
    unreliable under offscreen/no-backend so we never assert on it.
    """
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    w.set_media_path("/tmp/clip.wav")
    assert w.status_label.text() == "就绪"
    assert w.play_btn.isEnabled()
    assert w.play_btn.text() == "播放"
