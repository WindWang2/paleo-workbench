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
