"""Image preview decode bound, resize debounce and render cache (#530)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from paleo_workbench.ui.pages.image_preview_widget import ImagePreviewWidget


def _big_png_bytes(w: int = 5000, h: int = 3000) -> bytes:
    """A large but cheap-to-create PNG (solid color compresses well)."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0xFF3366AA)
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_load_decodes_bounded_to_preview_resolution(qtbot, tmp_path):
    """#530: a multi-megapixel source must not decode at full resolution —
    the preview decodes scaled (JPEG DCT scaling / reader-scaled decode),
    bounding both the GUI-thread decode cost and memory."""
    w = ImagePreviewWidget()
    qtbot.addWidget(w)
    w.resize(800, 600)

    w.load(str(tmp_path / "big.png"), revision=(1,), image_bytes=_big_png_bytes())
    pm = w.pixmap()
    assert pm is not None and not pm.isNull()
    assert max(pm.width(), pm.height()) <= 2048


def test_resize_events_coalesce_into_one_render(qtbot, tmp_path):
    """#530: interactive resizes stream dozens of events; the smooth
    rescale must run once after the debounce, not per event."""
    w = ImagePreviewWidget()
    qtbot.addWidget(w)
    w.resize(600, 400)
    w.load(str(tmp_path / "img.png"), revision=(1,), image_bytes=_big_png_bytes(300, 200))

    renders = []
    real = w.render_current

    def counting():
        renders.append(1)
        real()

    w.render_current = counting  # debounce timer calls this slot
    from PySide6.QtGui import QResizeEvent

    def deliver(width, height):
        # Offscreen resize() does not always deliver QResizeEvent; drive the
        # handler directly with distinct sizes like an interactive drag.
        w.resizeEvent(
            QResizeEvent(QSize(width, height), QSize(width - 7, height - 9))
        )

    deliver(601, 401)
    deliver(605, 410)
    deliver(640, 440)
    deliver(700, 500)
    assert renders == []  # nothing rendered synchronously per event

    qtbot.waitUntil(lambda: bool(renders), timeout=2_000)
    qtbot.wait(150)  # no further debounced renders accumulate
    assert len(renders) == 1, renders


def test_repeated_render_same_size_is_cached(qtbot, tmp_path):
    """#530: re-rendering at an unchanged size/mode must not rescale."""
    w = ImagePreviewWidget()
    qtbot.addWidget(w)
    w.resize(500, 400)
    w.load(str(tmp_path / "c.png"), revision=(1,), image_bytes=_big_png_bytes(200, 150))

    scaled_calls = []

    from paleo_workbench.ui.pages import image_preview_widget as mod

    real_scaled = mod.QPixmap.scaled

    def counting_scaled(self, *a, **k):
        scaled_calls.append(1)
        return real_scaled(self, *a, **k)

    mod.QPixmap.scaled = counting_scaled
    try:
        pm_before = w.pixmap().cacheKey()
        w.render_current()
        w.render_current()
        assert len(scaled_calls) == 0  # early-return on identical key
        assert w.pixmap().cacheKey() == pm_before  # same underlying pixmap
    finally:
        mod.QPixmap.scaled = real_scaled


def test_undecodable_source_shows_failure_text(qtbot):
    w = ImagePreviewWidget()
    qtbot.addWidget(w)
    w.load("nowhere.png", revision=(1,), image_bytes=b"not an image")
    assert w.text() == "图片预览加载失败"


def test_zoom_render_bounded_and_coalesced(qtbot):
    """#1135: 8x zoom caps the pixmap (~4k, not ~16k/1 GiB) and a wheel
    burst renders once after the debounce, not per notch."""
    w = ImagePreviewWidget()
    qtbot.addWidget(w)
    w.resize(800, 600)
    w.load("img.png", revision=(1,), image_bytes=_big_png_bytes(2048, 1536))
    renders = []
    real = w.render_current

    def counting():
        renders.append(1)
        real()

    w.render_current = counting
    for _ in range(12):  # wheel burst to 8x
        w.zoom_in()
    assert w._zoom_factor == 8.0
    assert len(renders) == 0  # nothing rendered synchronously per notch
    qtbot.waitUntil(lambda: len(renders) > 0, timeout=3000)
    assert len(renders) == 1  # one coalesced render
    pm = w.pixmap()
    assert pm is not None and not pm.isNull()
    assert max(pm.width(), pm.height()) <= 4096
