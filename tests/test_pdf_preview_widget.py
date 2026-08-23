import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from paleo_workbench.ui.pages import preview_widgets


class FakeSelection:
    def __init__(self, txt: str):
        self._txt = txt

    def text(self):
        return self._txt


class FakePdfDocument(QObject):
    statusChanged = Signal(object)

    class Error:
        None_ = 0

    class Status:
        Null = "null"
        Loading = "loading"
        Ready = "ready"
        Error = "error"

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self._status = self.Status.Ready
        self._pages = 2
        self._texts = {0: "page0", 1: "page1"}

    def load(self, _source):
        self._status = self.Status.Ready
        return self.Error.None_

    def status(self):
        return self._status

    def error(self):
        return self.Error.None_

    def pageCount(self):
        return self._pages

    def render(self, _page, size):
        return QImage(size.width(), size.height(), QImage.Format.Format_RGB32)

    def getAllText(self, index):
        return FakeSelection(self._texts.get(index, ""))


def test_pdf_copy_all_button_exists(qtbot, monkeypatch):
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    assert hasattr(widget, "copy_all_btn")
    assert widget.copy_all_btn.text() == "复制全部文本"


def test_pdf_copy_all_joins_pages_and_copies_to_clipboard(qtbot, monkeypatch):
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    # ensure clipboard cleared
    QApplication.clipboard().clear()
    widget.copy_all_btn.click()
    # process events for clipboard
    QApplication.processEvents()
    assert QApplication.clipboard().text() == "page0\npage1"
    # feedback
    assert widget.copy_all_btn.text() == "已复制"


def test_pdf_copy_all_truncates_at_1M(qtbot, monkeypatch):
    class BigFakeDoc(FakePdfDocument):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pages = 2
            self._texts = {0: "a" * 600000, 1: "b" * 600000}

    monkeypatch.setattr(preview_widgets, "QPdfDocument", BigFakeDoc)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    QApplication.clipboard().clear()
    widget.copy_all_btn.click()
    QApplication.processEvents()
    txt = QApplication.clipboard().text()
    assert len(txt) == 1000000
    assert widget.copy_all_btn.text() == "已复制（已截断）"


def test_pdf_copy_all_fallback_hidden_or_disabled(qtbot, monkeypatch):
    monkeypatch.setattr(preview_widgets, "QPdfDocument", None)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    btn = getattr(widget, "copy_all_btn", None)
    assert btn is not None
    assert (not btn.isVisible()) or (not btn.isEnabled())


def test_pdf_copy_all_handles_text_property_string(qtbot, monkeypatch):
    """getAllText returning object with .text as plain string (not callable)."""
    class StringTextDoc(FakePdfDocument):
        def getAllText(self, index):
            # return object whose .text is a string attribute
            class S:
                def __init__(self, t):
                    self.text = t
            return S(self._texts.get(index, ""))

    monkeypatch.setattr(preview_widgets, "QPdfDocument", StringTextDoc)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    QApplication.clipboard().clear()
    widget.copy_all_btn.click()
    QApplication.processEvents()
    assert QApplication.clipboard().text() == "page0\npage1"


# -- 连续页面 / 宽度适应 --


def test_pdf_default_fit_mode_is_width(qtbot, monkeypatch):
    """默认以宽度为主拉伸页面。"""
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    assert widget.fit_mode == "width"
    assert widget.fit_width_btn.isChecked()
    assert not widget.fit_page_btn.isChecked()


def test_pdf_fallback_renders_all_pages_continuous(qtbot, monkeypatch):
    """无 QPdfView 时所有页连续渲染进滚动区。"""
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(500, 700)
    widget.load("dummy.pdf", ("v1",))
    assert widget._content_stack.currentWidget() is widget._fallback_scroll
    assert len(widget._fallback_page_labels) == 2
    for label in widget._fallback_page_labels:
        assert label.pixmap() is not None and not label.pixmap().isNull()
    assert widget.page_label.text() == "1 / 2"


def test_pdf_fallback_next_page_updates_label(qtbot, monkeypatch):
    """连续模式翻页定位滚动而非重新渲染。"""
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(500, 700)
    widget.load("dummy.pdf", ("v1",))
    widget.next_btn.click()
    assert widget._page == 1
    assert widget.page_label.text() == "2 / 2"
    assert not widget.next_btn.isEnabled()
    assert widget.prev_btn.isEnabled()
    widget.prev_btn.click()
    assert widget._page == 0
    assert widget.page_label.text() == "1 / 2"


def test_pdf_fallback_scroll_updates_page_label(qtbot, monkeypatch):
    """fallback 滚动时按可视区位置同步页码。"""
    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(500, 700)
    widget.load("dummy.pdf", ("v1",))
    # 强制完成布局，拿到各页 label 的真实纵坐标
    widget._fallback_pages.adjustSize()
    second_y = widget._fallback_page_labels[1].y()
    assert second_y > 0
    widget._on_fallback_scroll(second_y + 10)
    assert widget._page == 1
    assert widget.page_label.text() == "2 / 2"


def test_pdf_fallback_zoom_scales_render_size(qtbot, monkeypatch):
    """fallback 连续模式下缩放按倍率改变渲染宽度。"""
    renders = []

    class TrackingDoc(FakePdfDocument):
        def render(self, page, size):
            renders.append((page, size.width()))
            return super().render(page, size)

    monkeypatch.setattr(preview_widgets, "QPdfDocument", TrackingDoc)
    monkeypatch.setattr(preview_widgets, "QPdfView", None)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(500, 700)
    widget.load("dummy.pdf", ("v1",))
    base_width = renders[-1][1]
    widget.zoom_in_btn.click()
    assert widget.fit_mode == "custom"
    assert renders[-1][1] > base_width


def test_pdf_qpdfview_uses_multipage_mode(qtbot, monkeypatch):
    """QPdfView 路径设置为 MultiPage 连续滚动。"""
    from PySide6.QtWidgets import QLabel as _QLabel

    jumps = []

    class FakeNavigator(QObject):
        def currentZoom(self):
            return 1.0

        def jump(self, page, location, zoom):
            jumps.append(page)

    class FakeView(_QLabel):
        class PageMode:
            SinglePage = "single"
            MultiPage = "multi"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.page_mode = None
            self.navigator = FakeNavigator()

        def setDocument(self, _doc):
            pass

        def setPageMode(self, mode):
            self.page_mode = mode

        def pageNavigator(self):
            return self.navigator

    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", FakeView)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.load("dummy.pdf", ("v1",))
    assert widget.pdf_view.page_mode == FakeView.PageMode.MultiPage
    assert jumps == [0]
    assert widget._content_stack.currentWidget() is widget.pdf_view


def test_pdf_current_page_changed_signal_updates_label(qtbot, monkeypatch):
    """连续滚动时 QPdfView 的 currentPageChanged 同步页码标签。"""
    from PySide6.QtCore import Signal as _Signal

    class FakeNavigator(QObject):
        currentPageChanged = _Signal(int)

        def currentZoom(self):
            return 1.0

        def jump(self, *_args):
            pass

    from PySide6.QtWidgets import QLabel as _QLabel

    class FakeView(_QLabel):
        class PageMode:
            MultiPage = "multi"

        def __init__(self, parent=None):
            super().__init__(parent)
            self.navigator = FakeNavigator()

        def setDocument(self, _doc):
            pass

        def setPageMode(self, _mode):
            pass

        def pageNavigator(self):
            return self.navigator

    monkeypatch.setattr(preview_widgets, "QPdfDocument", FakePdfDocument)
    monkeypatch.setattr(preview_widgets, "QPdfView", FakeView)
    widget = preview_widgets.PdfPreviewWidget()
    qtbot.addWidget(widget)
    widget.load("dummy.pdf", ("v1",))
    widget.pdf_view.navigator.currentPageChanged.emit(1)
    assert widget._page == 1
    assert widget.page_label.text() == "2 / 2"
