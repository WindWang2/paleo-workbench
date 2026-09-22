"""Tests for PdfPreviewPanel zoom (feat/pdf-aux-preview-zoom part 2)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Qt, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QScrollArea

from paleo_workbench.ui.pages.data_detail_panel import PdfPreviewPanel


class FakeDocument(QObject):
    """Stub QPdfDocument: records render size, returns valid QImage."""

    def __init__(self, pages: int = 2, parent=None):
        super().__init__(parent)
        self._pages = pages
        self.last_render_size: QSize | None = None
        self.last_render_page: int | None = None
        self.render_calls: list[tuple[int, QSize]] = []

    def pageCount(self) -> int:
        return self._pages

    def render(self, page: int, size: QSize) -> QImage:
        self.last_render_page = page
        self.last_render_size = QSize(size)
        self.render_calls.append((page, QSize(size)))
        # non-null image
        img = QImage(max(1, size.width()), max(1, size.height()), QImage.Format.Format_RGB32)
        img.fill(0x336699)
        return img


def _make_panel(qtbot, pages=2) -> tuple[PdfPreviewPanel, FakeDocument]:
    doc = FakeDocument(pages=pages)
    panel = PdfPreviewPanel(doc)
    qtbot.addWidget(panel)
    return panel, doc


def test_pdf_preview_panel_scroll_area_contains_image_label(qtbot):
    panel, _ = _make_panel(qtbot)
    area = panel.findChild(QScrollArea, "DataPreviewPdfScrollArea")
    assert area is not None
    # Exposed attribute
    assert hasattr(panel, "scroll_area")
    assert panel.scroll_area is area
    assert area.widget() is panel.image_label
    # widgetResizable False so zoomed pixmap shows scrollbars
    assert area.widgetResizable() is False


def test_pdf_preview_zoom_controls_exist(qtbot):
    panel, _ = _make_panel(qtbot)
    assert hasattr(panel, "zoom_in_button")
    assert hasattr(panel, "zoom_out_button")
    assert hasattr(panel, "zoom_label")
    # style spec: objectName SecondaryButton
    assert panel.zoom_in_button.objectName() == "SecondaryButton"
    assert panel.zoom_out_button.objectName() == "SecondaryButton"
    assert panel.zoom_label.objectName() == "DataPreviewPdfZoomLabel"
    assert panel.zoom_label.text() == "100%"


def test_zoom_in_changes_render_size(qtbot):
    panel, doc = _make_panel(qtbot)
    initial = doc.last_render_size
    assert initial is not None
    assert initial.width() == 420
    assert initial.height() == 560

    panel.zoom_in()
    assert doc.last_render_size is not None
    # 420 * 1.25 = 525, 560 * 1.25 = 700
    assert doc.last_render_size.width() == 525
    assert doc.last_render_size.height() == 700
    assert panel.zoom_label.text() == "125%"
    assert panel._zoom_factor == pytest.approx(1.25)


def test_zoom_out_changes_render_size(qtbot):
    panel, doc = _make_panel(qtbot)
    panel.zoom_out()
    assert doc.last_render_size is not None
    assert doc.last_render_size.width() == int(round(420 / 1.25))
    assert doc.last_render_size.height() == int(round(560 / 1.25))
    # 80%
    assert panel.zoom_label.text() == "80%"


def test_zoom_clamps_to_range(qtbot):
    panel, doc = _make_panel(qtbot)
    # zoom out repeatedly until clamp at 10%
    for _ in range(20):
        panel.zoom_out()
    assert panel._zoom_factor == pytest.approx(0.10)
    assert panel.zoom_label.text() == "10%"
    w = int(round(420 * 0.10))
    h = int(round(560 * 0.10))
    assert doc.last_render_size.width() == w
    assert doc.last_render_size.height() == h
    # further zoom_out should not change size nor crash
    prev_calls = len(doc.render_calls)
    panel.zoom_out()
    assert panel._zoom_factor == pytest.approx(0.10)
    # clamped path returns early without render
    assert len(doc.render_calls) == prev_calls

    # zoom in repeatedly until clamp at 800%
    for _ in range(40):
        panel.zoom_in()
    assert panel._zoom_factor == pytest.approx(8.00)
    assert panel.zoom_label.text() == "800%"
    w2 = int(round(420 * 8.0))
    h2 = int(round(560 * 8.0))
    assert doc.last_render_size.width() == w2
    assert doc.last_render_size.height() == h2
    prev_calls = len(doc.render_calls)
    panel.zoom_in()
    assert panel._zoom_factor == pytest.approx(8.00)
    assert len(doc.render_calls) == prev_calls


def test_zoom_step_is_1_25(qtbot):
    panel, _ = _make_panel(qtbot)
    panel._zoom_factor = 1.0
    panel.zoom_in()
    assert panel._zoom_factor == pytest.approx(1.25)
    panel.zoom_in()
    assert panel._zoom_factor == pytest.approx(1.5625)
    panel.zoom_out()
    panel.zoom_out()
    assert panel._zoom_factor == pytest.approx(1.0)


def test_paging_keeps_zoom_factor(qtbot):
    panel, doc = _make_panel(qtbot, pages=3)
    panel.zoom_in()
    panel.zoom_in()  # ~1.5625
    factor = panel._zoom_factor
    expected_w = int(round(420 * factor))
    expected_h = int(round(560 * factor))
    # go to next page
    panel.next_page()
    assert panel._page_index == 1
    assert panel._zoom_factor == pytest.approx(factor)
    assert doc.last_render_size.width() == expected_w
    assert doc.last_render_size.height() == expected_h
    assert doc.last_render_page == 1

    # zoom then previous page
    panel.previous_page()
    assert panel._page_index == 0
    assert panel._zoom_factor == pytest.approx(factor)
    assert doc.last_render_size.width() == expected_w


def test_zoom_buttons_click_integration(qtbot):
    panel, doc = _make_panel(qtbot)
    panel.zoom_in_button.click()
    assert panel._zoom_factor == pytest.approx(1.25)
    assert doc.last_render_size.width() == 525
    panel.zoom_out_button.click()
    assert panel._zoom_factor == pytest.approx(1.0)


def test_render_robust_when_document_none(qtbot):
    panel = PdfPreviewPanel(None)  # type: ignore[arg-type]
    qtbot.addWidget(panel)
    # should not crash, zoom should still update label
    panel.zoom_in()
    assert panel._zoom_factor == pytest.approx(1.25)
    assert panel.zoom_label.text() == "125%"


def test_scroll_area_viewport_has_event_filter(qtbot):
    # basic smoke: Ctrl+wheel should zoom via eventFilter/wheelEvent without crash
    panel, _ = _make_panel(qtbot)
    # Simulate wheel event via direct method call (eventFilter path needs QWheelEvent)
    # Instead test public API zoom_in/out covers Ctrl+wheel contract_doc; just ensure no crash on wheelEvent with no modifier
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint, QPointF

    # non-Ctrl wheel should propagate, not zoom
    before = panel._zoom_factor
    event = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 120), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False
    )
    panel.wheelEvent(event)
    assert panel._zoom_factor == pytest.approx(before)

    # Ctrl+wheel up => zoom_in
    event2 = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 120), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False
    )
    panel.wheelEvent(event2)
    assert panel._zoom_factor == pytest.approx(before * 1.25)
