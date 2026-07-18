from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel

from geoviz import PreparedPreview, PreviewKind

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class LifecycleEngine:
    def __init__(self) -> None:
        self.created: list[QLabel] = []
        self.released: list[QLabel] = []
        self.watched_thread = None
        self.thread_running_at_release: list[bool] = []

    def create_widget(self, kind, parent=None):
        widget = QLabel(parent)
        self.created.append(widget)
        return widget

    def render(self, widget, preview):
        widget.setText(preview.title)

    def release(self, widget):
        if self.watched_thread is not None:
            self.thread_running_at_release.append(self.watched_thread.isRunning())
        self.released.append(widget)


class LifecycleProvider(PreviewProvider):
    def __init__(self, *, fail_second: bool = False) -> None:
        super().__init__()
        self.fail_second = fail_second
        self.started: list[str] = []
        self.second_started = threading.Event()

    def preview(self, asset):
        self.started.append(asset.name)
        if asset.name == "second.las":
            self.second_started.set()
            time.sleep(0.2)
            if self.fail_second:
                raise RuntimeError("second preview failed")
        prepared = PreparedPreview(
            kind=PreviewKind.WELL_LOG,
            title=asset.name,
            payload={"source": asset.path},
            estimated_bytes=16,
        )
        return PreviewResult(
            mode="geoviz",
            title=asset.name,
            engine_preview=prepared,
            estimated_bytes=prepared.estimated_bytes,
        )


@pytest.mark.parametrize("fail_second", [False, True])
@pytest.mark.parametrize("teardown", ["close", "deferred_delete"])
def test_page_teardown_leaves_no_preview_job_and_releases_each_engine_widget_once(
    qtbot, tmp_path, fail_second, teardown
):
    path = tmp_path / "well.las"
    second_path = tmp_path / "second.las"
    path.write_text("~Version", encoding="utf-8")
    second_path.write_text("~Version", encoding="utf-8")
    project = ProjectDocument.new("P")
    project.resources = [
        ResourceItem(name=path.name, path=str(path), type="well_log", format="las"),
        ResourceItem(
            name=second_path.name,
            path=str(second_path),
            type="well_log",
            format="las",
        ),
    ]
    page = DataPage(project)
    if teardown == "close":
        qtbot.addWidget(page)
    engine = LifecycleEngine()
    page.reader_panel.geoviz_host.engine = engine
    provider = LifecycleProvider(fail_second=fail_second)
    page._preview_controller.provider = provider
    page._preview_controller._shutdown_wait_ms = 1

    page._set_selected_asset(project.resources[0])
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "geoviz", timeout=3000)
    qtbot.waitUntil(
        lambda: page._preview_controller._active_job.thread is None,
        timeout=3000,
    )
    assert len(engine.created) == 1

    # Keep the rendered widget alive while a second worker is active so close()
    # exercises both controller shutdown and engine teardown in one boundary.
    page._preview_controller.loading.disconnect()
    page._set_selected_asset(project.resources[1])
    assert provider.second_started.wait(timeout=3.0)
    active_thread = page._preview_controller._active_job.thread
    assert active_thread is not None
    engine.watched_thread = active_thread
    assert engine.released == []

    controller = page._preview_controller
    if teardown == "close":
        page.close()
    else:
        page.event(QEvent(QEvent.Type.DeferredDelete))

    assert controller._active_job.thread is None
    assert controller._pending is None
    assert engine.released == engine.created
    assert engine.thread_running_at_release == [False]
    assert provider.started == ["well.las", "second.las"]
    assert controller.cache.current_bytes == 16

    if teardown == "close":
        assert not active_thread.isRunning()
        page.close()
        assert engine.released == engine.created
