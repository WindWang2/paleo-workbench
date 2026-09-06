"""R1-M1 — depth-cursor unit contract for non-metre LAS documents.

The linking loop speaks MD in metres. A document whose LAS depth axis is
feet must never publish raw axis numbers as metres (fail-closed with a
reason) and must receive link cursors through an explicit conversion.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel


class _FtWellData:
    """Duck-typed loaded document with a LAS-declared ft depth axis."""

    well_name = "W-FT"
    depth_unit = "ft"


class _MWellData:
    well_name = "W-M"
    depth_unit = "m"


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def panel(qtbot, qapp):
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    return panel


def test_metre_document_publishes_normally(panel, qtbot):
    panel.well_log_data = _MWellData()
    assert panel.depth_cursor_unit() == "m"
    assert panel.depth_cursor_unavailable_reason() is None
    with qtbot.waitSignal(panel.depth_cursor_moved):
        panel._publish_gated_depth(1234.5)


def test_ft_document_refuses_publication_with_reason(panel, qtbot):
    panel.well_log_data = _FtWellData()
    assert panel.depth_cursor_unit() == "ft"
    assert panel.depth_cursor_unavailable_reason() == "depth-unit:ft"
    # No publication ever fires for a ft axis...
    with qtbot.assertNotEmitted(panel.depth_cursor_moved):
        panel._publish_gated_depth(3280.84)
    # ...and a pending flush cannot resurrect a held value either.
    panel._pending_engine_depth = 3280.84
    panel._flush_pending_depth()


def test_unknown_depth_unit_also_refuses(panel):
    class _Weird:
        well_name = "W-X"
        depth_unit = "cubits"

    panel.well_log_data = _Weird()
    assert panel.depth_cursor_unavailable_reason() == "depth-unit:cubits"


def test_set_link_cursor_converts_metres_into_ft_documents(panel):
    """Inbound link cursors are metres by contract; ft documents convert."""
    panel.well_log_data = _FtWellData()
    calls: list[tuple[str, float]] = []

    class _View:
        def set_crosshair(self, document_id, reference_depth, track_fraction=0.5):
            calls.append((document_id, reference_depth))
            return {"revision": 1}

    class _Plan:
        document_id = "doc-1"

    panel._backend = "engine"
    panel._engine_view = _View()
    panel._engine_plan = _Plan()
    assert panel.set_link_cursor(1000.0) is True
    assert len(calls) == 1
    # 1000 m = 3280.8398... ft — converted, never dumped as raw metres.
    assert calls[0][1] == pytest.approx(1000.0 / 0.3048)


def test_set_link_cursor_refuses_unknown_units(panel):
    class _Weird:
        well_name = "W-X"
        depth_unit = "cubits"

    panel.well_log_data = _Weird()

    class _View:
        def set_crosshair(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("unknown unit must fail closed before the write")

    class _Plan:
        document_id = "doc-1"

    panel._backend = "engine"
    panel._engine_view = _View()
    panel._engine_plan = _Plan()
    assert panel.set_link_cursor(1000.0) is False


def test_clear_link_cursor_works_regardless_of_unit(panel):
    panel.well_log_data = _FtWellData()
    cleared: list[str] = []

    class _View:
        def clear_crosshair(self, document_id):
            cleared.append(document_id)
            return {"revision": 1}

    class _Plan:
        document_id = "doc-1"

    panel._backend = "engine"
    panel._engine_view = _View()
    panel._engine_plan = _Plan()
    assert panel.set_link_cursor(None) is True
    assert cleared == ["doc-1"]
