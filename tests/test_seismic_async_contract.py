from __future__ import annotations

from paleo_workbench.viz.models import VizPayload


def test_seismic_host_never_invokes_synchronous_segy_load(monkeypatch, tmp_path):
    segy = tmp_path / "cube.sgy"
    segy.write_bytes(b"stub")
    calls = []

    class FakeView:
        def __init__(self, *, auto_load=False):
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


def test_seismic_panel_empty_state_cancels_pending_file_load(monkeypatch, qtbot):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    events = []

    class FakeView(QWidget):
        segy_loaded = Signal(object)

        def __init__(self, *, auto_load=False):
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
