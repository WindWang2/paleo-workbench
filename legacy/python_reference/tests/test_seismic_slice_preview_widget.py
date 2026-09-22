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


def test_slice_preview_uses_one_global_stretch_for_all_slices(qtbot):
    """C44: every slice must share the volume-wide stretch range, so adjacent
    slices cannot jump in contrast and a constant slice never black-screens."""
    from paleo_workbench.viz.seismic_3d_api import fast_slice_to_indexed8

    w = SeismicSlicePreviewWidget()
    qtbot.addWidget(w)
    rng = np.random.default_rng(7)
    vol = rng.uniform(-1.0, 1.0, size=(12, 14, 10)).astype(np.float32)
    vol[:, :, 3] *= 4.0  # one slice with 4x amplitude (would jump per-slice)
    vol[:, :, 5] = 0.25  # constant slice (would degenerate to (0,0) per-slice)

    w.load_seismic("dummy.segy", volume=vol)
    w.show()

    lo, hi = w._stretch_range
    assert hi > lo
    # The stretch range reported by every slice equals the cached global range.
    for i in range(10):
        norm, nlo, nhi = fast_slice_to_indexed8(
            vol, axis=2, index=i, value_range=w._stretch_range
        )
        assert (nlo, nhi) == (lo, hi)
    # The constant slice maps to a mid gray, not black (no per-slice (0,0)).
    w.slider.setValue(5)
    w._render_timer.stop()
    w._render_timer.timeout.emit()
    constant_norm = w._last_norm
    assert constant_norm.max() > 0
    assert constant_norm.min() < 255
    assert 100 < constant_norm.mean() < 160


def test_slice_preview_recomputes_stretch_when_volume_replaced(qtbot):
    w = SeismicSlicePreviewWidget()
    qtbot.addWidget(w)
    vol1 = np.random.default_rng(1).uniform(-1.0, 1.0, size=(8, 8, 8)).astype(np.float32)
    w.load_seismic("a.segy", volume=vol1)
    first = w._stretch_range

    vol2 = np.random.default_rng(2).uniform(-100.0, 100.0, size=(8, 8, 8)).astype(np.float32)
    w.load_seismic("b.segy", volume=vol2)
    second = w._stretch_range

    assert first is not None and second is not None
    assert first != second
