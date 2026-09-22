"""L2 host-side wiring: engine backend interaction on WellLogCanvasPanel.

Covers the depth-cursor producer (native crosshairChanged → gated
depth_cursor_moved in REFERENCE depth), the pick/selection event bridges,
the external link-cursor consumer with echo suppression, programmatic
depth jump, capability honesty, and teardown safety.
"""

from __future__ import annotations

import time

import pytest

from paleo_workbench.project.models import PredictionTask
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter


def _make_fake_view_cls(*, capable: bool = True):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    class FakeView(QWidget):
        crosshairChanged = Signal()
        hoverChanged = Signal()
        curveClicked = Signal()
        selectionChanged = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.submit_calls = 0
            self.crosshair_calls: list[tuple] = []
            self.viewport_calls: list[tuple] = []
            self._crosshair: dict | None = None
            self._click: dict | None = None
            self._selection: dict | None = None

        def submit_multi_track(self, payload):
            self.submit_calls += 1
            return {
                "depth": {"access_mode": "zero_copy"},
                "curve_count": len(payload["curves"]),
                "track_count": len(payload["tracks"]),
                "render_prepared": True,
            }

        if capable:

            def crosshair_state(self):
                return self._crosshair

            def set_crosshair(self, document_id, reference_depth, track_fraction=0.5):
                self.crosshair_calls.append(
                    (document_id, float(reference_depth), float(track_fraction))
                )
                self._crosshair = {
                    "document_id": document_id,
                    "reference_depth": float(reference_depth),
                    "display_depth": float(reference_depth),
                    "track_fraction": float(track_fraction),
                }
                # The engine coalesces native events; emulate the emission.
                self.crosshairChanged.emit()

            def clear_crosshair(self, document_id):
                self.crosshair_calls.append((document_id, None))
                self._crosshair = None

            def set_viewport_depth_range(self, document_id, top, bottom):
                self.viewport_calls.append((document_id, float(top), float(bottom)))

            def click_pick_info(self):
                return self._click

            def selection_state(self):
                return self._selection

    return FakeView


def _install_fake(monkeypatch, capable: bool = True):
    fake_cls = _make_fake_view_cls(capable=capable)

    def _fake_import():
        return object(), fake_cls, object()

    monkeypatch.setattr(engine_adapter, "try_import_welllog", _fake_import)
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "1")
    return fake_cls


def _task() -> PredictionTask:
    return PredictionTask(
        name="engine-task",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.8}]},
    )


def _panel_with_engine(qtbot, monkeypatch, *, capable: bool = True):
    fake_cls = _install_fake(monkeypatch, capable=capable)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(_task())
    assert panel.backend() == "engine"
    assert panel._engine_view is not None and isinstance(panel._engine_view, fake_cls)
    return panel, panel._engine_view


# ---------------------------------------------------------------------------
# Capability honesty
# ---------------------------------------------------------------------------


def test_depth_cursor_supported_reflects_binding_capability(qtbot, monkeypatch):
    panel, _view = _panel_with_engine(qtbot, monkeypatch, capable=True)
    assert panel.depth_cursor_supported() is True


def test_depth_cursor_supported_false_on_incapable_binding(qtbot, monkeypatch):
    panel, _view = _panel_with_engine(qtbot, monkeypatch, capable=False)
    assert panel.depth_cursor_supported() is False


def test_legacy_backend_always_supports_depth_cursor(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    assert panel.depth_cursor_supported() is True


# ---------------------------------------------------------------------------
# Producer: native crosshair → depth_cursor_moved (reference depth)
# ---------------------------------------------------------------------------


def test_engine_crosshair_publishes_reference_depth(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    depths: list[float] = []
    panel.depth_cursor_moved.connect(depths.append)

    view._crosshair = {"reference_depth": 1234.5, "display_depth": 1234.5}
    view.crosshairChanged.emit()

    assert depths == [1234.5]


def test_engine_crosshair_is_gated(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    depths: list[float] = []
    panel.depth_cursor_moved.connect(depths.append)

    view._crosshair = {"reference_depth": 100.0}
    view.crosshairChanged.emit()
    view._crosshair = {"reference_depth": 200.0}
    view.crosshairChanged.emit()  # inside the 120 ms gate → suppressed

    assert depths == [100.0]


def test_engine_crosshair_none_state_publishes_nothing(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    depths: list[float] = []
    panel.depth_cursor_moved.connect(depths.append)

    view._crosshair = None
    view.crosshairChanged.emit()
    view.hoverChanged.emit()

    assert depths == []


def test_engine_pick_and_selection_bridges(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    picks: list[dict] = []
    selections: list[dict] = []
    panel.curve_picked.connect(picks.append)
    panel.depth_selection_changed.connect(selections.append)

    view._click = {"curve_id": "c1", "reference_depth": 500.0}
    view.curveClicked.emit()
    view._selection = {"sampling_axis_id": "ax", "top": 10.0, "bottom": 20.0}
    view.selectionChanged.emit()

    assert picks and picks[0]["curve_id"] == "c1"
    assert selections and selections[0]["top"] == 10.0


# ---------------------------------------------------------------------------
# Consumer: external link cursor + echo suppression
# ---------------------------------------------------------------------------


def test_set_link_cursor_drives_native_crosshair(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    assert panel.set_link_cursor(1500.0) is True
    doc_id, depth, _fraction = view.crosshair_calls[-1]
    assert depth == 1500.0
    assert doc_id  # the live document id


def test_set_link_cursor_echo_does_not_republish(qtbot, monkeypatch):
    """External write → native crosshairChanged → must NOT re-publish."""
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    depths: list[float] = []
    panel.depth_cursor_moved.connect(depths.append)

    assert panel.set_link_cursor(1500.0) is True
    # set_crosshair on the fake emits crosshairChanged synchronously — the
    # panel must swallow it (value match + echo window).
    assert depths == []

    # A later, genuinely different hover value publishes normally.
    view._crosshair = {"reference_depth": 777.0}
    panel._depth_last_pub_ms = None
    view.crosshairChanged.emit()
    assert depths == [777.0]


def test_set_link_cursor_clear(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    panel.set_link_cursor(1500.0)
    assert panel.set_link_cursor(None) is True
    assert view.crosshair_calls[-1][1] is None


def test_set_link_cursor_unsupported_paths(qtbot, monkeypatch):
    panel, _view = _panel_with_engine(qtbot, monkeypatch, capable=False)
    assert panel.set_link_cursor(100.0) is False
    assert panel.set_link_cursor(None) is False

    # legacy backend: no native channel at all
    panel2, _view2 = _panel_with_engine(qtbot, monkeypatch)
    panel2.set_backend("legacy")
    assert panel2.set_link_cursor(100.0) is False

    # no document loaded: engine selected but empty state
    panel3, _view3 = _panel_with_engine(qtbot, monkeypatch)
    panel3.update_state(None)
    assert panel3.set_link_cursor(100.0) is False


def test_set_link_cursor_survives_destroyed_view(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    panel._release_engine_document()
    view.deleteLater()
    assert panel.set_link_cursor(100.0) is False  # no crash, honest False


# ---------------------------------------------------------------------------
# Consumer: programmatic depth jump
# ---------------------------------------------------------------------------


def test_jump_to_depth_drives_viewport(qtbot, monkeypatch):
    panel, view = _panel_with_engine(qtbot, monkeypatch)
    assert panel.jump_to_depth(1000.0, 2000.0) is True
    assert len(view.viewport_calls) == 1
    document_id, top, bottom = view.viewport_calls[0]
    assert (top, bottom) == (1000.0, 2000.0)
    assert document_id  # the live document id


def test_jump_to_depth_unsupported(qtbot, monkeypatch):
    panel, _view = _panel_with_engine(qtbot, monkeypatch, capable=False)
    assert panel.jump_to_depth(0.0, 100.0) is False
