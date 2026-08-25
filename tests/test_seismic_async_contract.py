from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from paleo_workbench.viz.models import VizPayload


def test_seismic_host_never_invokes_synchronous_segy_load(monkeypatch, tmp_path):
    segy = tmp_path / "cube.sgy"
    segy.write_bytes(b"stub")
    calls = []

    class FakeView:
        def __init__(self, *, auto_load=False, parent=None):
            pass

        def load_segy(self, path):
            raise AssertionError("GUI host must not call synchronous SEGY loader")

        def load_segy_async(self, path):
            calls.append(path)

    import paleo_workbench.viz.hosts.seismic_host as host_module

    monkeypatch.setattr(host_module, "SeismicView", FakeView)
    host = host_module.SeismicHost()

    assert host.apply(VizPayload(kind="seismic", label="cube", seismic_path=str(segy))) is True
    assert calls == [str(segy)]


def test_seismic_host_overlay_closure_only_fires_for_requested_path(monkeypatch, tmp_path):
    """A stale overlay closure must never fire on a newer file's load."""
    from PySide6.QtCore import QObject, Signal

    segy_a = tmp_path / "a.sgy"
    segy_a.write_bytes(b"stub")
    segy_b = tmp_path / "b.sgy"
    segy_b.write_bytes(b"stub")
    events: list[tuple[str, str]] = []

    class FakeView(QObject):
        segy_loaded = Signal(object)

        def __init__(self, *, auto_load=False, parent=None):
            super().__init__()

        def load_segy_async(self, path):
            pass

        def load_demo(self, volume):
            events.append(("demo", getattr(volume, "tag", None)))

        def load_overlay_volume(self, volume):
            events.append(("overlay", getattr(volume, "tag", None)))

    import paleo_workbench.viz.hosts.seismic_host as host_module

    monkeypatch.setattr(host_module, "SeismicView", FakeView)
    host = host_module.SeismicHost()

    vol_a = SimpleNamespace(tag="vol-a")
    vol_b = SimpleNamespace(tag="vol-b")

    # Apply A with volume: overlay pending for path a.
    host.apply(
        VizPayload(kind="seismic", label="a", seismic_path=str(segy_a), seismic_volume=vol_a)
    )
    assert events == []

    # Re-apply B with a different volume: A's closure must be dropped.
    host.apply(
        VizPayload(kind="seismic", label="b", seismic_path=str(segy_b), seismic_volume=vol_b)
    )
    # A's load finishes late: its overlay must NOT be applied.
    host.widget.segy_loaded.emit(SimpleNamespace(path=str(segy_a)))
    assert events == []

    # B's load finishes: B's overlay applied exactly once, then self-disconnected.
    host.widget.segy_loaded.emit(SimpleNamespace(path=str(segy_b)))
    assert events == [("overlay", "vol-b")]
    host.widget.segy_loaded.emit(SimpleNamespace(path=str(segy_b)))
    assert events == [("overlay", "vol-b")]


def test_seismic_host_clear_disconnects_pending_overlay(monkeypatch, tmp_path):
    from PySide6.QtCore import QObject, Signal

    segy = tmp_path / "cube.sgy"
    segy.write_bytes(b"stub")
    events: list[str] = []

    class FakeView(QObject):
        segy_loaded = Signal(object)

        def __init__(self, *, auto_load=False, parent=None):
            super().__init__()

        def load_segy_async(self, path):
            pass

        def load_demo(self, volume):
            events.append("demo")

        def load_overlay_volume(self, volume):
            events.append("overlay")

    import paleo_workbench.viz.hosts.seismic_host as host_module

    monkeypatch.setattr(host_module, "SeismicView", FakeView)
    host = host_module.SeismicHost()
    host.apply(
        VizPayload(
            kind="seismic", label="x", seismic_path=str(segy), seismic_volume=np.zeros(1)
        )
    )
    host.clear()
    # The pending overlay connection was dropped by clear().
    host.widget.segy_loaded.emit(SimpleNamespace(path=str(segy)))
    assert events == ["demo"]  # only the empty-volume demo from clear()


def test_seismic_panel_empty_state_cancels_pending_file_load(monkeypatch, qtbot):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    events = []

    class FakeView(QWidget):
        segy_loaded = Signal(object)

        def __init__(self, *, auto_load=False, parent=None):
            super().__init__()

        def cancel_pending_segy_load(self):
            events.append("cancel")

        def is_ready(self):
            return False

    import paleo_workbench.ui.pages.seismic_view_panel as panel_module

    monkeypatch.setattr(panel_module, "SeismicView", FakeView)
    panel = panel_module.SeismicViewPanel()
    qtbot.addWidget(panel)

    panel._show_empty("未选择预测任务")

    assert events == ["cancel"]
