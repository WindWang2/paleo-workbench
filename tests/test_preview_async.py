import threading
import time
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController


def _wait_controller_idle(qtbot, controller: PreviewRequestController, timeout: int = 5000) -> None:
    """Block until in-flight preview workers finish (avoids Qt teardown aborts)."""
    qtbot.waitUntil(lambda: len(controller._jobs) == 0, timeout=timeout)


class SlowProvider(PreviewProvider):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        self.calls.append(asset.name)
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"preview:{asset.name}",
        )


class DelayedProvider(PreviewProvider):
    """Provider that sleeps so overlapping requests can finish out of order."""

    def __init__(self, delay_by_name: dict[str, float] | None = None, default_delay: float = 0.15):
        super().__init__()
        self.delay_by_name = delay_by_name or {}
        self.default_delay = default_delay
        self.calls: list[str] = []
        self.started: list[str] = []
        self._lock = threading.Lock()

    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        with self._lock:
            self.started.append(asset.name)
            self.calls.append(asset.name)
        time.sleep(self.delay_by_name.get(asset.name, self.default_delay))
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"preview:{asset.name}",
        )


class FailingProvider(PreviewProvider):
    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        raise RuntimeError("preview boom")


def test_rapid_selection_keeps_last_result(qtbot, tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aaa")
    b.write_text("bbb")
    project = ProjectDocument.new("P")
    project.resources = [
        ResourceItem(name="a.txt", path=str(a), type="document", format="txt"),
        ResourceItem(name="b.txt", path=str(b), type="document", format="txt"),
    ]
    page = DataPage(project)
    qtbot.addWidget(page)
    provider = SlowProvider()
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    page._set_selected_asset(project.resources[0])
    page._set_selected_asset(project.resources[1])

    def ready_for_b():
        return page.reader_panel.title_label.text() == "b.txt"

    qtbot.waitUntil(ready_for_b, timeout=3000)
    assert page.reader_panel.current_mode in {"message", "text"}
    assert "b.txt" in page.reader_panel.title_label.text()
    _wait_controller_idle(qtbot, page._preview_controller)


def test_delayed_provider_last_wins_under_overlap(qtbot, tmp_path):
    """A is slow; B is fast. A finishes after B but must be discarded (last wins)."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aaa")
    b.write_text("bbb")
    project = ProjectDocument.new("P")
    resources = [
        ResourceItem(name="a.txt", path=str(a), type="document", format="txt"),
        ResourceItem(name="b.txt", path=str(b), type="document", format="txt"),
    ]
    project.resources = resources
    page = DataPage(project)
    qtbot.addWidget(page)

    # A sleeps longer so its worker completes after B; generation must discard A.
    provider = DelayedProvider(delay_by_name={"a.txt": 0.35, "b.txt": 0.05})
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    saw_loading = {"value": False}

    def on_loading():
        saw_loading["value"] = True

    page._preview_controller.loading.connect(on_loading)

    page._set_selected_asset(resources[0])
    page._set_selected_asset(resources[1])

    qtbot.waitUntil(
        lambda: page.reader_panel.title_label.text() == "b.txt"
        and page.reader_panel.current_mode == "message",
        timeout=3000,
    )
    # Wait for the slow A job to finish; it must not overwrite B.
    _wait_controller_idle(qtbot, page._preview_controller)
    assert page.reader_panel.title_label.text() == "b.txt"
    assert page.reader_panel.current_mode == "message"
    assert page.reader_panel.message_label.text() == "preview:b.txt"
    # Both workers should have been started (overlap).
    assert "a.txt" in provider.started
    assert "b.txt" in provider.started
    assert saw_loading["value"] is True


def test_reader_shows_loading_with_delayed_provider(qtbot, tmp_path):
    path = tmp_path / "slow.txt"
    path.write_text("content", encoding="utf-8")
    resource = ResourceItem(name="slow.txt", path=str(path), type="document", format="txt")
    project = ProjectDocument.new("P")
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    provider = DelayedProvider(default_delay=0.25)
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    modes: list[str] = []
    page.reader_panel.reader_mode_changed.connect(modes.append)

    page._set_selected_asset(resource)

    qtbot.waitUntil(lambda: "loading" in modes, timeout=3000)
    qtbot.waitUntil(
        lambda: page.reader_panel.current_mode in {"text", "message"},
        timeout=3000,
    )
    assert page.reader_panel.title_label.text() == "slow.txt"
    _wait_controller_idle(qtbot, page._preview_controller)


def test_reader_shows_loading_or_settles_after_select(qtbot, tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 100)
    resource = ResourceItem(name="big.txt", path=str(path), type="document", format="txt")
    project = ProjectDocument.new("P")
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    page._set_selected_asset(resource)

    # Loading may flash, or the result may already be ready; either way not empty.
    qtbot.waitUntil(lambda: page.reader_panel.current_mode != "empty", timeout=3000)
    qtbot.waitUntil(
        lambda: page.reader_panel.current_mode in {"text", "message", "loading"},
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: page.reader_panel.current_mode in {"text", "message"},
        timeout=3000,
    )
    assert page.reader_panel.title_label.text() in {"big.txt", "加载中… big.txt"}
    _wait_controller_idle(qtbot, page._preview_controller)


def test_preview_failed_signal_surfaces_message(qtbot, tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("x", encoding="utf-8")
    resource = ResourceItem(name="bad.txt", path=str(path), type="document", format="txt")
    project = ProjectDocument.new("P")
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    provider = FailingProvider()
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    failures: list[str] = []
    page._preview_controller.failed.connect(failures.append)

    page._set_selected_asset(resource)

    qtbot.waitUntil(lambda: len(failures) == 1, timeout=3000)
    assert "preview boom" in failures[0]
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "message", timeout=3000)
    assert page.reader_panel.title_label.text() == "预览失败"
    _wait_controller_idle(qtbot, page._preview_controller)


def test_rescan_invalidates_inflight_preview(qtbot, tmp_path, monkeypatch):
    """Rescan must bump generation so a slow pre-rescan preview cannot win."""
    path = tmp_path / "notes.txt"
    path.write_text("alpha", encoding="utf-8")
    project = ProjectDocument.new("P")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    # Gate the first preview until rescan has requested a newer generation.
    release_first = threading.Event()
    entered_first = threading.Event()
    call_count = {"n": 0}
    lock = threading.Lock()

    class GatedProvider(PreviewProvider):
        def preview(self, asset):
            if asset is None:
                return super().preview(asset)
            with lock:
                call_count["n"] += 1
                n = call_count["n"]
            if n == 1:
                entered_first.set()
                # Block until rescan issues request #2.
                assert release_first.wait(timeout=3.0)
                return PreviewResult(
                    mode="message",
                    title="STALE",
                    path=getattr(asset, "path", ""),
                    message="stale-pre-rescan",
                )
            return PreviewResult(
                mode="message",
                title="FRESH",
                path=getattr(asset, "path", ""),
                message="fresh-after-rescan",
            )

    provider = GatedProvider()
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    page._set_selected_asset(resource)
    # Wait until the first worker has entered the gated preview.
    assert entered_first.wait(timeout=3.0)
    gen_before_rescan = page._preview_controller.generation

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.scan_resources",
        lambda _folder: [
            ResourceItem(
                id=resource.id,
                name="notes.txt",
                path=str(path),
                type="document",
                format="txt",
                status="indexed",
            )
        ],
    )
    assert page.rescan_selected_asset() is True
    assert page._preview_controller.generation > gen_before_rescan

    # Release the stale worker; it must not overwrite the rescan result.
    release_first.set()

    qtbot.waitUntil(
        lambda: page.reader_panel.title_label.text() == "FRESH",
        timeout=3000,
    )
    _wait_controller_idle(qtbot, page._preview_controller)
    assert page.reader_panel.title_label.text() == "FRESH"
    assert page.reader_panel.current_mode == "message"


def test_stale_generation_discarded(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    controller = PreviewRequestController()
    received: list[object] = []
    controller.result_ready.connect(received.append)

    controller.request(resource)
    first_generation = controller.generation
    # Bump generation without waiting so the in-flight job is stale.
    controller._generation = first_generation + 1

    # Allow the worker to finish; stale result must not be emitted.
    _wait_controller_idle(qtbot, controller)
    assert received == []

    controller.request(None)
    assert len(received) == 1
    assert received[0].mode == "empty"


def test_cache_hit_skips_provider_and_loading(qtbot, tmp_path):
    """Re-selecting the same unchanged asset serves from LRU without provider.preview."""
    path = tmp_path / "hit.txt"
    path.write_text("cached content", encoding="utf-8")
    resource = ResourceItem(name="hit.txt", path=str(path), type="document", format="txt")
    provider = SlowProvider()
    controller = PreviewRequestController(provider)
    results: list[object] = []
    loadings: list[bool] = []
    controller.result_ready.connect(results.append)
    controller.loading.connect(lambda: loadings.append(True))

    controller.request(resource)
    _wait_controller_idle(qtbot, controller)
    assert provider.calls == ["hit.txt"]
    assert len(results) == 1
    assert loadings == [True]

    controller.request(resource)
    # Cache hit is synchronous — no worker, no second provider call, no loading.
    assert provider.calls == ["hit.txt"]
    assert len(controller._jobs) == 0
    assert len(results) == 2
    assert loadings == [True]
    assert results[0].title == results[1].title == "hit.txt"
    assert results[1].message == "preview:hit.txt"


def test_cache_miss_after_file_rewrite(qtbot, tmp_path):
    """Rewriting the file changes the cache key so provider runs again."""
    path = tmp_path / "rewrite.txt"
    path.write_text("v1", encoding="utf-8")
    resource = ResourceItem(
        name="rewrite.txt",
        path=str(path),
        type="document",
        format="txt",
        checksum="c1",
    )
    provider = SlowProvider()
    controller = PreviewRequestController(provider)
    results: list[object] = []
    controller.result_ready.connect(results.append)

    controller.request(resource)
    _wait_controller_idle(qtbot, controller)
    assert provider.calls == ["rewrite.txt"]

    path.write_text("v2-longer-content", encoding="utf-8")
    controller.request(resource)
    _wait_controller_idle(qtbot, controller)
    assert provider.calls == ["rewrite.txt", "rewrite.txt"]
    assert len(results) == 2
