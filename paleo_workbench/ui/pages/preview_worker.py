from __future__ import annotations

from copy import copy
from dataclasses import replace
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult

Asset = ResourceItem | ExportArtifact

# Keep small media payloads in the LRU so re-select is path-free on the UI.
MAX_CACHED_MEDIA_BYTES = 512 * 1024

PendingKind = Literal["asset", "media"]


def snapshot_asset(asset: Asset) -> Asset:
    """Copy asset so worker threads never share mutable project state."""
    if hasattr(asset, "model_copy"):
        return asset.model_copy(deep=True)
    return copy(asset)


def needs_media_preload(result: PreviewResult) -> bool:
    """True when UI would otherwise open the file path for image/PDF/GeoTIFF."""
    if not result.path:
        return False
    if result.mode == "image" and not result.image_bytes:
        return True
    if result.mode == "geotiff" and not result.image_bytes:
        return True
    if result.mode == "pdf" and not result.pdf_bytes:
        return True
    return False


def preload_media(result: PreviewResult) -> PreviewResult:
    """Read image/PDF file bytes off the UI thread.

    UI converts image bytes → QPixmap and PDF bytes → QPdfDocument (via QBuffer).
    Avoid creating QImage/QPixmap/QPdfDocument on the worker thread.
    """
    if not result.path:
        return result
    if result.mode == "image":
        if result.image_bytes:
            return result
        try:
            data = Path(result.path).read_bytes()
        except OSError:
            return result
        if not data:
            return result
        return replace(result, image_bytes=data)
    if result.mode == "geotiff":
        if result.image_bytes:
            return result
        try:
            data = Path(result.path).read_bytes()
        except OSError:
            return result
        if not data:
            return result
        return replace(result, image_bytes=data)
    if result.mode == "pdf":
        if result.pdf_bytes:
            return result
        try:
            data = Path(result.path).read_bytes()
        except OSError:
            return result
        if not data:
            return result
        return replace(result, pdf_bytes=data)
    return result


def cacheable_result(result: PreviewResult) -> PreviewResult:
    """Strip large media payloads before storing in the UI-thread LRU."""
    if result.mode == "geoviz":
        return result
    image_bytes = result.image_bytes
    pdf_bytes = result.pdf_bytes
    if image_bytes and len(image_bytes) > MAX_CACHED_MEDIA_BYTES:
        image_bytes = b""
    if pdf_bytes and len(pdf_bytes) > MAX_CACHED_MEDIA_BYTES:
        pdf_bytes = b""
    if image_bytes is result.image_bytes and pdf_bytes is result.pdf_bytes:
        return result
    return replace(result, image_bytes=image_bytes, pdf_bytes=pdf_bytes)


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
            if result.mode != "geoviz":
                result = preload_media(result)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(self._generation, str(exc))
            return
        self.finished.emit(self._generation, result)


class _MediaPreloadWorker(QObject):
    """Reload image/PDF bytes for a path-only cached PreviewResult."""

    finished = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, result: PreviewResult, generation: int, parent=None):
        super().__init__(parent)
        self._result = result
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            out = preload_media(self._result)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(self._generation, str(exc))
            return
        self.finished.emit(self._generation, out)


class PreviewRequestController(QObject):
    """UI-thread coordinator for async previews.

    At most one worker thread runs at a time. Newer cache-miss requests replace
    a single pending slot (latest-only). Stale generations never update the UI
    or the LRU cache. Assets passed to workers are deep-copied snapshots.

    Image/PDF file bytes are always read off the UI thread (full preview job or
    media-only reload after a path-only cache hit).
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
        self._jobs: list[tuple[QThread, QObject]] = []
        self._active: tuple[QThread, QObject] | None = None
        # Latest pending: ("asset", gen, Asset, key) | ("media", gen, PreviewResult, key)
        self._pending: tuple[PendingKind, int, object, tuple] | None = None
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
            if needs_media_preload(hit):
                # Path-only cache: re-read media off-thread, skip provider rebuild.
                self.loading.emit()
                if self._active is not None:
                    self._pending = ("media", generation, hit, key)
                    return
                self._start_media_job(generation, hit, key)
                return
            self._pending = None
            self.result_ready.emit(hit)
            return

        snap = snapshot_asset(asset)
        self.loading.emit()
        if self._active is not None:
            self._pending = ("asset", generation, snap, key)
            return

        self._start_job(generation, snap, key)

    def shutdown(self, wait_ms: int | None = None) -> None:
        """Stop accepting work and wait for the active worker (no force-kill)."""
        self._shutting_down = True
        self._pending = None
        self._generation += 1
        self._inflight_keys.clear()

        jobs = list(self._jobs)
        if self._active is not None and self._active not in jobs:
            jobs.append(self._active)
        if not jobs:
            self._active = None
            self._jobs.clear()
            return

        # Cooperative only: ask every owned thread to stop its event loop after
        # the current bounded provider call returns. Never abandon ownership of
        # a running QThread, even if the caller's bounded wait expires.
        deadline = self._shutdown_wait_ms if wait_ms is None else wait_ms
        for thread, worker in jobs:
            try:
                worker.finished.disconnect(self._on_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                worker.failed.disconnect(self._on_failed)
            except (RuntimeError, TypeError):
                pass
            thread.requestInterruption()
            thread.quit()

        for thread, _worker in jobs:
            if not thread.wait(max(deadline, 0)):
                thread.wait()

        for thread, _worker in jobs:
            while thread.isRunning():
                thread.wait()

        self._active = None
        self._jobs.clear()

    def _wire_thread(self, thread: QThread, worker: QObject) -> None:
        self._active = (thread, worker)
        self._jobs = [(thread, worker)]
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        # quit() is thread-safe. Invoke it directly from the worker thread so
        # shutdown() can wait without deadlocking on a quit queued to the UI
        # thread that is currently blocked in QThread.wait().
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Pump the next job only after the thread has fully stopped — starting a
        # new QThread while Shiboken is still tearing down the previous one can
        # segfault under pytest-qt / offscreen.
        thread.finished.connect(lambda t=thread, w=worker: self._on_thread_finished(t, w))
        thread.start()

    def _start_job(self, generation: int, asset: Asset, key: tuple) -> None:
        self._inflight_keys[generation] = key
        thread = QThread(self)
        worker = _PreviewWorker(self.provider, asset, generation)
        worker.moveToThread(thread)
        self._wire_thread(thread, worker)

    def _start_media_job(self, generation: int, result: PreviewResult, key: tuple) -> None:
        self._inflight_keys[generation] = key
        thread = QThread(self)
        worker = _MediaPreloadWorker(result, generation)
        worker.moveToThread(thread)
        self._wire_thread(thread, worker)

    def _on_finished(self, generation: int, result: object) -> None:
        key = self._inflight_keys.pop(generation, None)
        if not self._shutting_down and generation == self._generation:
            if key is not None and isinstance(result, PreviewResult):
                self.cache.put(key, cacheable_result(result))
            self.result_ready.emit(result)
        # Do not start the next job here — wait for thread.finished.

    def _on_failed(self, generation: int, message: str) -> None:
        self._inflight_keys.pop(generation, None)
        if not self._shutting_down and generation == self._generation:
            self.failed.emit(message)

    def _on_thread_finished(self, thread: QThread, worker: QObject) -> None:
        self._jobs = [job for job in self._jobs if job != (thread, worker)]
        if self._active == (thread, worker):
            self._active = None
        if self._shutting_down:
            return
        # Defer so Shiboken can finish deleteLater of the prior worker/thread
        # before we spawn another QThread (avoids intermittent offscreen segfaults).
        QTimer.singleShot(0, self._pump_pending)

    def _pump_pending(self) -> None:
        if self._shutting_down or self._active is not None:
            return
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        kind, generation, payload, key = pending
        if generation != self._generation:
            return
        if kind == "media":
            assert isinstance(payload, PreviewResult)
            hit = self.cache.get(key)
            if hit is not None and not needs_media_preload(hit):
                self.result_ready.emit(hit)
                return
            self.loading.emit()
            self._start_media_job(generation, payload if hit is None else hit, key)
            return
        hit = self.cache.get(key)
        if hit is not None:
            if needs_media_preload(hit):
                self.loading.emit()
                self._start_media_job(generation, hit, key)
                return
            self.result_ready.emit(hit)
            return
        self.loading.emit()
        assert not isinstance(payload, PreviewResult)
        self._start_job(generation, payload, key)
