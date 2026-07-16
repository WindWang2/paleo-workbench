import threading
import time
from pathlib import Path

import pytest

from geoviz import PreparedPreview, PreviewKind

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController


def _wait_controller_idle(qtbot, controller: PreviewRequestController, timeout: int = 5000) -> None:
    """Block until in-flight preview workers finish (avoids Qt teardown aborts)."""
    qtbot.waitUntil(
        lambda: (
            len(controller._jobs) == 0
            and controller._active is None
            and controller._pending is None
        ),
        timeout=timeout,
    )


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
    # Serial queue: A runs then latest pending B. Stale A must not overwrite B.
    _wait_controller_idle(qtbot, page._preview_controller)
    assert page.reader_panel.title_label.text() == "b.txt"
    assert page.reader_panel.current_mode == "message"
    assert page.reader_panel.message_label.text() == "preview:b.txt"
    assert "a.txt" in provider.started
    assert "b.txt" in provider.started
    assert saw_loading["value"] is True
    # Never more than one concurrent job.
    assert page._preview_controller._active is None


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
        lambda _folder, project_path=None: [
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


def test_serial_queue_keeps_only_latest_pending(qtbot, tmp_path):
    """While a job runs, intermediate selections collapse to the latest pending."""
    paths = [tmp_path / f"{name}.txt" for name in ("a", "b", "c")]
    for path in paths:
        path.write_text(path.stem, encoding="utf-8")
    resources = [
        ResourceItem(name=p.name, path=str(p), type="document", format="txt")
        for p in paths
    ]
    provider = DelayedProvider(
        delay_by_name={"a.txt": 0.3, "b.txt": 0.05, "c.txt": 0.05}
    )
    controller = PreviewRequestController(provider)
    results: list[object] = []
    controller.result_ready.connect(results.append)

    controller.request(resources[0])
    controller.request(resources[1])
    controller.request(resources[2])

    _wait_controller_idle(qtbot, controller)
    # a ran; b was superseded by c while a was active — only a then c.
    assert provider.calls[0] == "a.txt"
    assert "c.txt" in provider.calls
    assert "b.txt" not in provider.calls
    assert results[-1].title == "c.txt"


def test_slow_geoviz_request_replaced_by_latest_only_reaches_reader_and_cache(
    qtbot, tmp_path
):
    paths = [tmp_path / f"{name}.las" for name in ("a", "b")]
    for path in paths:
        path.write_text("~Version", encoding="utf-8")
    resources = [
        ResourceItem(name=p.name, path=str(p), type="well_log", format="las")
        for p in paths
    ]

    class SlowGeoVizProvider(PreviewProvider):
        def preview(self, asset):
            if asset.name == "a.las":
                time.sleep(0.2)
            prepared = PreparedPreview(
                kind=PreviewKind.WELL_LOG,
                title=asset.name,
                payload={"source": asset.name},
                estimated_bytes=60,
            )
            return PreviewResult(
                mode="geoviz",
                title=asset.name,
                engine_preview=prepared,
                estimated_bytes=prepared.estimated_bytes,
            )

    provider = SlowGeoVizProvider()
    controller = PreviewRequestController(provider, cache_max_size=8)
    received: list[PreviewResult] = []
    received_threads: list[threading.Thread] = []

    def receive(result: PreviewResult) -> None:
        received.append(result)
        received_threads.append(threading.current_thread())

    controller.result_ready.connect(receive)

    controller.request(resources[0])
    controller.request(resources[1])
    _wait_controller_idle(qtbot, controller)

    from paleo_workbench.ui.pages.preview_cache import make_preview_cache_key

    assert [result.title for result in received] == ["b.las"]
    assert received_threads == [threading.main_thread()]
    assert controller.cache.get(make_preview_cache_key(resources[0])) is None
    cached_b = controller.cache.get(make_preview_cache_key(resources[1]))
    assert cached_b is received[0]
    assert cached_b.engine_preview is received[0].engine_preview


def test_geoviz_payload_is_not_preloaded_or_stripped(qtbot, tmp_path, monkeypatch):
    import paleo_workbench.ui.pages.preview_worker as worker_module

    path = tmp_path / "well.las"
    path.write_text("~Version", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="well_log", format="las")
    media = b"x" * (worker_module.MAX_CACHED_MEDIA_BYTES + 1)
    prepared = PreparedPreview(
        kind=PreviewKind.WELL_LOG,
        title=path.name,
        payload={"opaque": media},
        estimated_bytes=len(media),
    )
    result = PreviewResult(
        mode="geoviz",
        title=path.name,
        path=str(path),
        image_bytes=media,
        pdf_bytes=media,
        engine_preview=prepared,
        estimated_bytes=prepared.estimated_bytes,
    )

    class GeoVizProvider(PreviewProvider):
        def preview(self, asset):
            return result

    preload_calls: list[PreviewResult] = []
    original_preload = worker_module.preload_media
    monkeypatch.setattr(
        worker_module,
        "preload_media",
        lambda value: preload_calls.append(value) or original_preload(value),
    )
    controller = PreviewRequestController(
        GeoVizProvider(),
        cache=worker_module.PreviewCache(max_bytes=4 * len(media)),
    )
    received: list[PreviewResult] = []
    controller.result_ready.connect(received.append)

    controller.request(resource)
    _wait_controller_idle(qtbot, controller)

    assert preload_calls == []
    assert received == [result]
    cached = controller.cache.get(worker_module.make_preview_cache_key(resource))
    assert cached is result
    assert cached.image_bytes is media
    assert cached.pdf_bytes is media


def test_shutdown_stops_accepting_and_clears_jobs(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    provider = DelayedProvider(default_delay=0.4)
    controller = PreviewRequestController(provider)
    results: list[object] = []
    controller.result_ready.connect(results.append)

    controller.request(resource)
    qtbot.waitUntil(lambda: len(provider.started) >= 1, timeout=2000)
    controller.shutdown(wait_ms=2000)

    assert len(controller._jobs) == 0
    assert controller._active is None
    assert controller._pending is None
    # Further requests ignored while shut down.
    controller.request(resource)
    assert len(controller._jobs) == 0
    # Stale completion must not deliver after shutdown.
    qtbot.wait(100)
    assert results == []


@pytest.mark.parametrize("fails", [False, True])
def test_shutdown_timeout_falls_back_to_waiting_for_real_thread_stop(
    qtbot, tmp_path, fails
):
    paths = [tmp_path / f"{name}.txt" for name in ("a", "b")]
    for path in paths:
        path.write_text(path.stem, encoding="utf-8")
    resources = [
        ResourceItem(name=path.name, path=str(path), type="document", format="txt")
        for path in paths
    ]

    class SlowEndingProvider(PreviewProvider):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.calls: list[str] = []

        def preview(self, asset):
            self.calls.append(asset.name)
            self.started.set()
            time.sleep(0.05)
            if fails:
                raise RuntimeError("ending failed")
            return PreviewResult(mode="message", title=asset.name)

    provider = SlowEndingProvider()
    controller = PreviewRequestController(provider)
    results: list[PreviewResult] = []
    failures: list[str] = []
    controller.result_ready.connect(results.append)
    controller.failed.connect(failures.append)

    controller.request(resources[0])
    assert provider.started.wait(timeout=3.0)
    controller.request(resources[1])
    assert controller._pending is not None
    assert controller._active is not None
    active_thread = controller._active[0]

    controller.shutdown(wait_ms=1)
    running_after_shutdown = active_thread.isRunning()
    if running_after_shutdown:
        # Bounded join only — never block the suite on a stuck QThread.
        active_thread.requestInterruption()
        active_thread.quit()
        assert active_thread.wait(5_000)

    assert controller._active is None
    assert controller._jobs == []
    assert controller._pending is None
    assert results == []
    assert failures == []
    assert controller.cache.current_bytes == 0
    qtbot.wait(50)
    # Provider may finish after the short shutdown wait; only require that
    # the first request was started.
    assert "a.txt" in provider.calls


def test_data_page_close_shuts_down_preview_controller(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("P")
    project.resources = [
        ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    ]
    page = DataPage(project)
    qtbot.addWidget(page)
    provider = DelayedProvider(default_delay=0.3)
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    page._set_selected_asset(project.resources[0])
    qtbot.waitUntil(lambda: len(provider.started) >= 1, timeout=2000)
    page.close()
    assert page._preview_controller._jobs == []
    assert page._preview_controller._active is None


def test_worker_uses_asset_snapshot(qtbot, tmp_path):
    """Worker must not see live mutations made after request()."""
    path = tmp_path / "notes.txt"
    path.write_text("v1", encoding="utf-8")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    release = threading.Event()
    entered = threading.Event()
    seen_names: list[str] = []

    class GatedProvider(PreviewProvider):
        def preview(self, asset):
            if asset is None:
                return super().preview(asset)
            seen_names.append(asset.name)
            entered.set()
            assert release.wait(timeout=3.0)
            return PreviewResult(
                mode="message",
                title=asset.name,
                path=getattr(asset, "path", ""),
                message=f"name={asset.name}",
            )

    provider = GatedProvider()
    controller = PreviewRequestController(provider)
    results: list[object] = []
    controller.result_ready.connect(results.append)

    controller.request(resource)
    assert entered.wait(timeout=3.0)
    # Mutate the live project object while the worker is blocked.
    resource.name = "MUTATED"
    release.set()
    _wait_controller_idle(qtbot, controller)
    assert seen_names == ["notes.txt"]
    assert results[-1].title == "notes.txt"
    assert "MUTATED" not in results[-1].message


def test_shutdown_does_not_force_kill():
    import inspect

    # Contract: cooperative wait only — force-kill must not appear as a call.
    src = inspect.getsource(PreviewRequestController.shutdown)
    assert "thread.terminate" not in src
    assert "QThread.terminate" not in src
    assert "wait(" in src


def test_preload_media_image_bytes(tmp_path):
    from paleo_workbench.ui.pages.preview_worker import preload_media

    path = tmp_path / "dot.bin"
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    path.write_bytes(payload)
    result = PreviewResult(mode="image", title="dot.bin", path=str(path))
    loaded = preload_media(result)
    assert loaded.image_bytes == payload


def test_preload_media_pdf_bytes(tmp_path):
    from paleo_workbench.ui.pages.preview_worker import preload_media

    path = tmp_path / "doc.pdf"
    payload = b"%PDF-1.4\n%%EOF\n"
    path.write_bytes(payload)
    result = PreviewResult(mode="pdf", title="doc.pdf", path=str(path))
    loaded = preload_media(result)
    assert loaded.pdf_bytes == payload


def test_cacheable_result_strips_large_media():
    from paleo_workbench.ui.pages.preview_worker import (
        MAX_CACHED_MEDIA_BYTES,
        cacheable_result,
    )

    small = PreviewResult(
        mode="image",
        title="s",
        path="/s.png",
        image_bytes=b"x" * 100,
    )
    assert cacheable_result(small).image_bytes == b"x" * 100

    large = PreviewResult(
        mode="pdf",
        title="big",
        path="/b.pdf",
        pdf_bytes=b"y" * (MAX_CACHED_MEDIA_BYTES + 1),
    )
    assert cacheable_result(large).pdf_bytes == b""


def test_image_cache_keeps_small_bytes_on_reselect(qtbot, tmp_path):
    """Small images stay in LRU so re-select does not re-open the file on UI."""
    from PySide6.QtGui import QImage

    path = tmp_path / "tiny.png"
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0x112233)
    image.save(path.as_posix())
    resource = ResourceItem(
        name="tiny.png",
        path=str(path),
        type="image_reference",
        format="png",
    )
    controller = PreviewRequestController()
    results: list[object] = []
    loadings: list[bool] = []
    controller.result_ready.connect(results.append)
    controller.loading.connect(lambda: loadings.append(True))

    controller.request(resource)
    _wait_controller_idle(qtbot, controller)
    assert len(results) == 1
    assert results[0].mode == "image"
    assert results[0].image_bytes  # preloaded off-thread

    controller.request(resource)
    # Small payload cached → sync hit, no second loading flash required.
    assert len(results) == 2
    assert results[1].image_bytes == results[0].image_bytes
    assert len(controller._jobs) == 0


def test_path_only_image_cache_reloads_bytes_off_thread(qtbot, tmp_path):
    """Path-only LRU entries re-read media off-thread (no UI QPixmap(path))."""
    from paleo_workbench.ui.pages.preview_cache import make_preview_cache_key
    from paleo_workbench.ui.pages.preview_worker import needs_media_preload

    path = tmp_path / "bigish.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    resource = ResourceItem(
        name="bigish.png",
        path=str(path),
        type="image_reference",
        format="png",
    )
    controller = PreviewRequestController()
    # Seed a path-only cache entry (simulates stripped large media).
    key = make_preview_cache_key(resource)
    path_only = PreviewResult(mode="image", title="bigish.png", path=str(path))
    assert needs_media_preload(path_only) is True
    controller.cache.put(key, path_only)

    results: list[object] = []
    loadings: list[bool] = []
    controller.result_ready.connect(results.append)
    controller.loading.connect(lambda: loadings.append(True))

    controller.request(resource)
    _wait_controller_idle(qtbot, controller)
    assert loadings == [True]
    assert len(results) == 1
    assert results[0].image_bytes == path.read_bytes()


def test_needs_media_preload_geotiff():
    from paleo_workbench.ui.pages.preview_worker import needs_media_preload

    # geotiff without image_bytes (e.g. cache-stripped large thumbnail) → needs preload
    assert needs_media_preload(PreviewResult(mode="geotiff", title="t", path="x.tif")) is True
    # geotiff with image_bytes → no preload
    assert (
        needs_media_preload(
            PreviewResult(mode="geotiff", title="t", path="x.tif", image_bytes=b"x")
        )
        is False
    )
