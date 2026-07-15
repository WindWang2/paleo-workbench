from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtWidgets import QLabel

from geoviz import PreparedPreview, PreviewKind


class RecordingEngine:
    def __init__(self) -> None:
        self.created: list[tuple[PreviewKind, QLabel]] = []
        self.rendered: list[tuple[QLabel, PreparedPreview]] = []
        self.released: list[QLabel] = []
        self.create_error: Exception | None = None
        self.render_error: Exception | None = None
        self.render_fail_on_call: int | None = None
        self.release_error: Exception | None = None
        self.release_errors: dict[QLabel, Exception] = {}

    def create_widget(self, kind: PreviewKind, parent=None) -> QLabel:
        if self.create_error is not None:
            raise self.create_error
        widget = QLabel(parent)
        self.created.append((kind, widget))
        return widget

    def render(self, widget: QLabel, preview: PreparedPreview) -> None:
        self.rendered.append((widget, preview))
        if self.render_error is not None and (
            self.render_fail_on_call is None
            or len(self.rendered) == self.render_fail_on_call
        ):
            raise self.render_error
        widget.setText(preview.title)

    def release(self, widget: QLabel) -> None:
        self.released.append(widget)
        error = self.release_errors.get(widget, self.release_error)
        if error is not None:
            raise error
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


def test_host_create_failure_leaves_no_cached_or_active_widget(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    create_error = RuntimeError("create failed")
    engine.create_error = create_error
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)

    with pytest.raises(RuntimeError) as caught:
        host.render(_preview(PreviewKind.WELL_LOG, "Well"))

    assert caught.value is create_error
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0
    assert engine.released == []


def test_host_new_widget_render_failure_terminally_disposes_widget(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    render_error = RuntimeError("render failed")
    engine.render_error = render_error
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)

    with pytest.raises(RuntimeError) as caught:
        host.render(_preview(PreviewKind.WELL_LOG, "Well"))

    widget = engine.created[0][1]
    assert caught.value is render_error
    assert engine.released.count(widget) == 1
    assert widget.isHidden()
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0


def test_host_same_kind_render_failure_terminally_disposes_reused_widget(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    widget = host.render(_preview(PreviewKind.WELL_LOG, "First"))
    render_error = RuntimeError("second render failed")
    engine.render_error = render_error
    engine.render_fail_on_call = 2

    with pytest.raises(RuntimeError) as caught:
        host.render(_preview(PreviewKind.WELL_LOG, "Second"))

    assert caught.value is render_error
    assert engine.released.count(widget) == 1
    assert widget.isHidden()
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0


def test_host_render_preserves_render_error_when_cleanup_release_also_fails(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    render_error = RuntimeError("render failed")
    engine.render_error = render_error
    engine.release_error = RuntimeError("release failed")
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)

    with pytest.raises(RuntimeError) as caught:
        host.render(_preview(PreviewKind.WELL_LOG, "Well"))

    widget = engine.created[0][1]
    assert caught.value is render_error
    assert engine.released.count(widget) == 1
    assert widget.isHidden()
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0


def test_host_release_failure_still_completes_local_terminal_cleanup(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    widget = host.render(_preview(PreviewKind.WELL_LOG, "Well"))
    release_error = RuntimeError("release failed")
    engine.release_error = release_error

    with pytest.raises(RuntimeError) as caught:
        host.clear()

    assert caught.value is release_error
    assert engine.released.count(widget) == 1
    assert widget.isHidden()
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0


def test_host_release_all_cleans_every_widget_then_reraises_first_error(qtbot):
    from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost

    engine = RecordingEngine()
    host = GeoVizPreviewHost(engine)
    qtbot.addWidget(host)
    first = engine.create_widget(PreviewKind.WELL_LOG, host.stack)
    second = engine.create_widget(PreviewKind.SURFACE, host.stack)
    host.widgets[PreviewKind.WELL_LOG] = first
    host.widgets[PreviewKind.SURFACE] = second
    host.stack.addWidget(first)
    host.stack.addWidget(second)
    host._active_kind = PreviewKind.WELL_LOG
    first_error = RuntimeError("first release failed")
    engine.release_errors[first] = first_error

    with pytest.raises(RuntimeError) as caught:
        host.release_all()

    assert caught.value is first_error
    assert engine.released == [first, second]
    assert engine.released.count(first) == 1
    assert engine.released.count(second) == 1
    assert first.isHidden()
    assert second.isHidden()
    assert host.widgets == {}
    assert host._active_kind is None
    assert host.stack.count() == 0
