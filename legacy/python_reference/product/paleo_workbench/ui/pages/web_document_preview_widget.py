from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout, QWidget


class _LocalOnlyRequestInterceptor:
    """Block WebEngine resource requests outside the local document sandbox.

    Lazily inherits from QWebEngineUrlRequestInterceptor at import time to
    avoid forcing WebEngine initialization when preview_widgets is imported.
    """

    _ALLOWED_SCHEMES = {"file", "data", "about", "blob"}

    def interceptRequest(self, info) -> None:
        if info.requestUrl().scheme() not in self._ALLOWED_SCHEMES:
            info.block(True)


class _LocalOnlyPage:
    """Reject user-initiated navigation away from local document content.

    Lazily inherits from QWebEnginePage at construction time.
    """

    _ALLOWED_SCHEMES = {"file", "data", "about", "blob"}

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        del navigation_type, is_main_frame
        return url.scheme() in self._ALLOWED_SCHEMES


class WebDocumentPreviewWidget(QWidget):
    """Render local HTML or bounded Markdown output without network access.

    Inherits from QWidget (no WebEngine dependency at import time). The
    QWebEngineView is created lazily in __init__, so importing
    preview_widgets does not trigger WebEngine subprocess initialization.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWebEngineCore import (
            QWebEnginePage,
            QWebEngineProfile,
            QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class _Interceptor(QWebEngineUrlRequestInterceptor, _LocalOnlyRequestInterceptor):
            pass

        class _Page(QWebEnginePage, _LocalOnlyPage):
            pass

        self._engine_view = QWebEngineView(self)
        self._profile = QWebEngineProfile(self)
        self._interceptor = _Interceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self._page = _Page(self._profile, self._engine_view)
        self._engine_view.setPage(self._page)
        self._engine_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._engine_view)

    def load_document(self, path: str, html: str = "") -> None:
        base_url = QUrl.fromLocalFile(str(Path(path).parent) + "/")
        if html:
            self._engine_view.setHtml(html, base_url)
        else:
            self._engine_view.load(QUrl.fromLocalFile(path))

    def apply_settings(self, settings) -> None:
        self._engine_view.setZoomFactor(settings.font_size / 12.0)
