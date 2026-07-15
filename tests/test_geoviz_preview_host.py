from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtWidgets import QLabel

from geoviz import PreparedPreview, PreviewKind


class RecordingEngine:
    def __init__(self) -> None:
        self.created: list[tuple[PreviewKind, QLabel]] = []
        self.rendered: list[tuple[QLabel, PreparedPreview]] = []
        self.released: list[QLabel] = []

    def create_widget(self, kind: PreviewKind, parent=None) -> QLabel:
        widget = QLabel(parent)
        self.created.append((kind, widget))
        return widget

    def render(self, widget: QLabel, preview: PreparedPreview) -> None:
        self.rendered.append((widget, preview))
        widget.setText(preview.title)

    def release(self, widget: QLabel) -> None:
        self.released.append(widget)
        widget.clear()


def _preview(kind: PreviewKind, title: str) -> PreparedPreview:
    return PreparedPreview(kind=kind, title=title, payload={})


def test_host_reuses_widget_for_consecutive_previews_of_same_kind(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)

    first = host.render(_preview(PreviewKind.WELL_LOG, "First well"))
    second = host.render(_preview(PreviewKind.WELL_LOG, "Second well"))

    assert first is second
    assert engine.created == [(PreviewKind.WELL_LOG, first)]
    assert engine.rendered[-1][0] is first
    assert first.text() == "Second well"
    assert engine.released == []


def test_host_releases_and_hides_old_widget_when_kind_changes(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    host.show()

    old_widget = host.render(_preview(PreviewKind.WELL_LOG, "Well"))
    new_widget = host.render(_preview(PreviewKind.SURFACE, "Surface"))

    assert engine.released == [old_widget]
    assert old_widget.isHidden()
    assert host.stack.currentWidget() is new_widget
    assert new_widget is not old_widget
    assert PreviewKind.WELL_LOG not in host.widgets

    replacement = host.render(_preview(PreviewKind.WELL_LOG, "Another well"))

    assert replacement is not old_widget
    assert [kind for kind, _widget in engine.created] == [
        PreviewKind.WELL_LOG,
        PreviewKind.SURFACE,
        PreviewKind.WELL_LOG,
    ]
    assert engine.released.count(old_widget) == 1


def test_host_clear_completes_active_widget_lifecycle(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    widget = host.render(_preview(PreviewKind.WELL_LOG, "Well"))

    host.clear()

    assert engine.released == [widget]
    assert widget.isHidden()
    assert host.stack.count() == 0


def test_host_release_all_completes_cached_widget_lifecycle(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    widget = host.render(_preview(PreviewKind.WELL_LOG, "Well"))

    host.release_all()

    assert engine.released == [widget]
    assert widget.isHidden()
    assert host.widgets == {}
    assert host.stack.count() == 0


def test_host_rejects_render_outside_ui_thread(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    host = GeoVizPreviewHost(RecordingEngine())
    qtbot.addWidget(host)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(host.render, _preview(PreviewKind.WELL_LOG, "Well"))
        with pytest.raises(RuntimeError, match="UI thread"):
            future.result()
