"""Debounced slider, cached-resize and numpy colormap for the slice preview."""
from __future__ import annotations

import sys

import numpy as np

from paleo_workbench.ui.pages.seismic_slice_preview_widget import SeismicSlicePreviewWidget


def _make_widget(qtbot):
    w = SeismicSlicePreviewWidget()
    qtbot.addWidget(w)
    vol = np.random.default_rng(5).random((16, 20, 24)).astype(np.float32)
    # The widget's real volume-setting API is load_seismic(); it also sets the
    # slider range from the volume shape and performs the initial render.
    w.load_seismic("dummy.segy", volume=vol)
    # Show the widget so resize() actually delivers resizeEvents.
    w.show()
    return w


def test_slider_is_debounced(qtbot, monkeypatch):
    w = _make_widget(qtbot)
    calls = []
    monkeypatch.setattr(w, "_render_slice", lambda: calls.append(1))
    for v in range(5, 10):
        w.slider.setValue(v)
    assert len(calls) <= 1  # rapid changes coalesced (0 until timer fires)
    w._render_timer.stop()
    w._render_timer.timeout.emit()
    assert len(calls) == 1


def test_resize_does_not_rerender(qtbot, monkeypatch):
    w = _make_widget(qtbot)
    w.resize(400, 300)
    w.slider.setValue(3)
    if hasattr(w, "_render_timer"):
        w._render_timer.stop()
        w._render_timer.timeout.emit()
    calls = []
    import paleo_workbench.ui.pages.seismic_slice_preview_widget as mod
    monkeypatch.setattr(mod, "fast_slice_to_indexed8", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(RuntimeError("should not be called")))
    w.resize(420, 320)
    assert calls == []


def test_colormap_table_without_matplotlib(qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)
    w = _make_widget(qtbot)
    w._color_table = None
    w.slider.setValue(2)
    if hasattr(w, "_render_timer"):
        w._render_timer.stop()
        w._render_timer.timeout.emit()
    table = w._color_table
    assert table is not None and len(table) == 256
