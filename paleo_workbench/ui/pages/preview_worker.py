from __future__ import annotations

from copy import copy
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult

Asset = ResourceItem | ExportArtifact


def snapshot_asset(asset: Asset) -> Asset:
    """Copy asset so worker threads never share mutable project state."""
    if hasattr(asset, "model_copy"):
        return asset.model_copy(deep=True)
    return copy(asset)


def preload_media(result: PreviewResult) -> PreviewResult:
    """Read image file bytes off the UI thread.

    UI converts bytes → QImage/QPixmap. Avoids creating QImage/QPixmap on
    the worker thread (Shiboken/Qt teardown hazards under pytest-qt).
    """
    if not result.path or result.mode != "image":
        return result
    try:
        data = Path(result.path).read_bytes()
    except OSError:
        return result
    if not data:
        return result
    return replace(result, image_bytes=data)


class _PreviewWorker(QObject):
    finished = Signal(int, object)  # generation, PreviewResult
    failed = Signal(int, str)

    def __init__(
        self,
        provider: PreviewProvider,
        asset: Asset,
        generation: int,
        parent=None,
    ):
        super().__init__(parent)
        self._provider = provider
        # Always a snapshot — never the live project model object.
        self._asset = asset
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            result = self._provider.preview(self._asset)
            result = preload_media(result)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(self._generation, str(exc))
            return
        self.finished.emit(self._generation, result)


class PreviewRequestController(QObject):
    """UI-thread coordinator for async previews.

    At most one worker thread runs at a time. Newer cache-miss requests replace
    a single pending slot (latest-only). Stale generations never update the UI
    or the LRU cache. Assets passed to workers are deep-copied snapshots.
    """

    result_ready = Signal(object)  # PreviewResult
    loading = Signal()
    failed = Signal(str)

    def __init__(
        self,
        provider: PreviewProvider | None = None,
        parent=None,
        *,
        cache: PreviewCache | None = None,
        cache_max_size: int = 32,
        shutdown_wait_ms: int = 10_000,
    ):
        super().__init__(parent)
        self.provider = provider or PreviewProvider()
        self.cache = cache if cache is not None else PreviewCache(max_size=cache_max_size)
        self._shutdown_wait_ms = shutdown_wait_ms
        self._generation = 0
        self._jobs: list[tuple[QThread, _PreviewWorker]] = []
        self._active: tuple[QThread, _PreviewWorker] | None = None
        # Latest pending miss: (generation, snapshot_asset, cache_key)
        self._pending: tuple[int, Asset, tuple] | None = None
        self._inflight_keys: dict[int, tuple] = {}
        self._shutting_down = False

    @property
    def generation(self) -> int:
        return self._generation

    def request(self, asset: Asset | None) -> None:
        if self._shutting_down:
            return

        self._generation += 1
        generation = self._generation

        if asset is None:
            self._pending = None
            self.result_ready.emit(self.provider.preview(None))
            return

        key = make_preview_cache_key(asset)
        hit = self.cache.get(key)
        if hit is not None:
            self._pending = None
            self.result_ready.emit(hit)
            return

        snap = snapshot_asset(asset)
        self.loading.emit()
        if self._active is not None:
            self._pending = (generation, snap, key)
            return

        self._start_job(generation, snap, key)

    def shutdown(self, wait_ms: int | None = None) -> None:
        """Stop accepting work and wait for the active worker (no force-kill)."""
        self._shutting_down = True
        self._pending = None
        self._generation += 1
        self._inflight_keys.clear()

        active = self._active
        if active is None:
            self._jobs.clear()
            return

        thread, worker = active
        # Cooperative only: wait for the in-flight job to finish naturally.
        # Do not force-kill the worker thread — unsafe with native parsers.
        # Keep finished→thread.quit so the thread can exit after run().
        deadline = self._shutdown_wait_ms if wait_ms is None else wait_ms
        try:
            worker.finished.disconnect(self._on_finished)
        except (RuntimeError, TypeError):
            pass
        try:
            worker.failed.disconnect(self._on_failed)
        except (RuntimeError, TypeError):
            pass
        thread.wait(max(deadline, 0))
        self._active = None
        self._jobs.clear()

    def _start_job(self, generation: int, asset: Asset, key: tuple) -> None:
        self._inflight_keys[generation] = key
        thread = QThread(self)
        worker = _PreviewWorker(self.provider, asset, generation)
        worker.moveToThread(thread)
        self._active = (thread, worker)
        self._jobs = [(thread, worker)]
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._drop_job(t, w))
        thread.start()

    def _on_finished(self, generation: int, result: object) -> None:
        key = self._inflight_keys.pop(generation, None)
        if not self._shutting_down and generation == self._generation:
            if key is not None and isinstance(result, PreviewResult):
                # Cache metadata/text without large image payloads.
                cached = (
                    replace(result, image_bytes=b"")
                    if result.image_bytes
                    else result
                )
                self.cache.put(key, cached)
            self.result_ready.emit(result)
        self._after_job()

    def _on_failed(self, generation: int, message: str) -> None:
        self._inflight_keys.pop(generation, None)
        if not self._shutting_down and generation == self._generation:
            self.failed.emit(message)
        self._after_job()

    def _after_job(self) -> None:
        self._active = None
        if not self._shutting_down:
            self._pump_pending()

    def _pump_pending(self) -> None:
        if self._shutting_down or self._active is not None:
            return
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        generation, asset, key = pending
        if generation != self._generation:
            return
        hit = self.cache.get(key)
        if hit is not None:
            self.result_ready.emit(hit)
            return
        self.loading.emit()
        self._start_job(generation, asset, key)

    def _drop_job(self, thread: QThread, worker: _PreviewWorker) -> None:
        self._jobs = [job for job in self._jobs if job != (thread, worker)]
        if self._active == (thread, worker):
            self._active = None
