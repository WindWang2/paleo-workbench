from __future__ import annotations

from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import replace
from pathlib import Path
import threading
import traceback
from typing import Literal

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_disk_cache import (
    PreviewDiskCache,
    is_disk_cacheable,
)
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_settings import PreviewSettings
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

Asset = ResourceItem | ExportArtifact

# Keep small media payloads in the LRU so re-select is path-free on the UI.
MAX_CACHED_MEDIA_BYTES = 512 * 1024
MAX_PRELOAD_MEDIA_BYTES = 64 * 1024 * 1024

PendingKind = Literal["asset", "media"]
RequestKind = Literal["default", "summary", "visualization"]


class _CacheEpoch:
    """Serialize cache clearing against request-local worker disk writes."""

    def __init__(self) -> None:
        self._current = 0
        self._lock = threading.RLock()

    @contextmanager
    def advance(self, generation: int):
        with self._lock:
            self._current = generation
            yield

    @contextmanager
    def write_if_current(self, generation: int):
        with self._lock:
            yield self._current == generation

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return self._current == generation


def _build_for_request_kind(
    provider: PreviewProvider,
    asset: Asset | None,
    request_kind: RequestKind,
) -> PreviewResult:
    if request_kind == "summary":
        return provider.preview_summary(asset)
    if request_kind == "visualization":
        return provider.preview_visualization(asset)
    return provider.preview(asset)


def snapshot_asset(asset: Asset) -> Asset:
    """Copy asset so worker threads never share mutable project state."""
    if hasattr(asset, "model_copy"):
        return asset.model_copy(deep=True)
    return deepcopy(asset)


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
    if result.mode not in {"image", "geotiff", "pdf"}:
        return result
    if result.mode in {"image", "geotiff"} and result.image_bytes:
        return result
    if result.mode == "pdf" and result.pdf_bytes:
        return result
    if not result.path:
        return result
    path = Path(result.path)
    try:
        if path.stat().st_size > MAX_PRELOAD_MEDIA_BYTES:
            return result
    except OSError:
        return result
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_PRELOAD_MEDIA_BYTES + 1)
    except OSError:
        return result
    if not data or len(data) > MAX_PRELOAD_MEDIA_BYTES:
        return result
    if result.mode in {"image", "geotiff"}:
        return replace(result, image_bytes=data)
    if result.mode == "pdf":
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
        *,
        disk_cache: PreviewDiskCache | None = None,
        settings: PreviewSettings | None = None,
        request_kind: RequestKind = "default",
        cache_epoch: _CacheEpoch | None = None,
        cache_generation: int = 0,
    ):
        super().__init__(parent)
        self._settings = settings or PreviewSettings.defaults()
        self._provider = provider.with_settings(self._settings)
        # Always a snapshot — never the live project model object.
        self._asset = asset
        self._generation = generation
        self._request_kind = request_kind
        self._cache_epoch = cache_epoch
        self._cache_generation = cache_generation
        if disk_cache is None:
            self._disk = None
        else:
            # Request-local cache facade prevents an in-flight worker from
            # observing options changed by a newer settings generation.
            self._disk = PreviewDiskCache(
                disk_cache.project_root,
                options=self._settings.to_geoviz_options(),
                comparison_crs=disk_cache.comparison_crs,
            )

    @Slot()
    def run(self) -> None:
        try:
            use_disk = (
                self._request_kind != "summary"
                and
                self._disk is not None
                and isinstance(self._asset, ResourceItem)
                and is_disk_cacheable(self._asset)
            )
            if use_disk:
                hit = self._disk.try_load(self._asset)
                if hit is not None:
                    self.finished.emit(self._generation, hit)
                    return

            result = _build_for_request_kind(
                self._provider,
                self._asset,
                self._request_kind,
            )
            if result.mode != "geoviz":
                result = preload_media(result)

            if use_disk and result.cacheable:
                if self._cache_epoch is None:
                    self._disk.store(self._asset, result)
                else:
                    self._disk.store(
                        self._asset,
                        result,
                        commit_guard=lambda: self._cache_epoch.write_if_current(
                            self._cache_generation
                        ),
                    )
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(self._generation, f"{exc}\n{traceback.format_exc()}")
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
            self.failed.emit(self._generation, f"{exc}\n{traceback.format_exc()}")
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
        disk_cache: PreviewDiskCache | None = None,
        settings: PreviewSettings | None = None,
        request_kind: RequestKind = "default",
    ):
        super().__init__(parent)
        self.provider = provider or PreviewProvider()
        self.settings = settings or getattr(
            self.provider,
            "settings",
            PreviewSettings.defaults(),
        )
        self.cache = cache if cache is not None else PreviewCache(max_size=cache_max_size)
        self.disk_cache = disk_cache if disk_cache is not None else PreviewDiskCache(None)
        self.disk_cache.set_options(self.settings.to_geoviz_options())
        self._comparison_crs: str | None = self.disk_cache.comparison_crs
        if request_kind not in {"default", "summary", "visualization"}:
            raise ValueError(f"unknown preview request kind: {request_kind}")
        self.request_kind = request_kind
        self._shutdown_wait_ms = shutdown_wait_ms
        self._generation = 0
        self._cache_epoch = _CacheEpoch()
        self._cache_generation = 0
        self._active_job = OwnedWorkerJob(self)
        self._active_job.released.connect(self._on_thread_finished)
        # Latest pending carries request generation and cache generation.
        self._pending: tuple[PendingKind, int, object, tuple, int] | None = None
        self._inflight_keys: dict[int, tuple[tuple, int]] = {}
        self._shutting_down = False

    @property
    def generation(self) -> int:
        return self._generation

    def set_project_root(self, root: Path | str | None) -> None:
        self.disk_cache.set_project_root(root)

    def set_comparison_crs(self, comparison_crs: str | None) -> bool:
        """Invalidate prepared previews when their CRS comparison changes."""
        normalized = str(comparison_crs).strip() if comparison_crs else None
        if self.disk_cache.comparison_crs == normalized:
            return False
        self._comparison_crs = normalized
        self.disk_cache.set_comparison_crs(normalized)
        self.cache.clear()
        self.invalidate()
        return True

    def clear_disk_cache(self) -> None:
        """Clear project disk preview cache and in-memory LRU."""
        if self._shutting_down:
            return
        self._advance_cache_generation()
        self.disk_cache.clear()
        self.cache.clear()

    def _advance_generation(self) -> int:
        self._generation += 1
        return self._generation

    def _advance_cache_generation(self) -> int:
        self._cache_generation += 1
        with self._cache_epoch.advance(self._cache_generation):
            pass
        return self._cache_generation

    def set_settings(self, settings: PreviewSettings) -> bool:
        """Invalidate old generations and install a new immutable profile."""
        if settings == self.settings:
            return False
        self.settings = settings
        self._advance_generation()
        self._pending = None
        self.cache.clear()
        self.disk_cache.set_options(settings.to_geoviz_options())
        return True

    def invalidate(self) -> None:
        """Invalidate pending/result delivery without starting another request."""
        if self._shutting_down:
            return
        self._advance_generation()
        self._pending = None

    def request(self, asset: Asset | None) -> None:
        if self._shutting_down:
            return

        generation = self._advance_generation()
        cache_generation = self._cache_generation

        if asset is None:
            self._pending = None
            configured = self.provider.with_settings(self.settings)
            self.result_ready.emit(
                _build_for_request_kind(configured, None, self.request_kind)
            )
            return

        key = make_preview_cache_key(
            asset,
            self.settings.fingerprint(),
            comparison_crs=self._comparison_crs,
        )
        hit = self.cache.get(key)
        if hit is not None:
            if needs_media_preload(hit):
                # Path-only cache: re-read media off-thread, skip provider rebuild.
                self.loading.emit()
                if self._active_job.thread is not None:
                    self._pending = (
                        "media",
                        generation,
                        hit,
                        key,
                        cache_generation,
                    )
                    return
                self._start_media_job(generation, hit, key, cache_generation)
                return
            self._pending = None
            self.result_ready.emit(hit)
            return

        snap = snapshot_asset(asset)
        self.loading.emit()
        if self._active_job.thread is not None:
            self._pending = (
                "asset",
                generation,
                snap,
                key,
                cache_generation,
            )
            return

        self._start_job(generation, snap, key, cache_generation)

    def shutdown(self, wait_ms: int | None = None) -> None:
        """Stop accepting work and wait for the active worker (no force-kill)."""
        self._shutting_down = True
        self._pending = None
        self._advance_generation()
        self._advance_cache_generation()
        self._inflight_keys.clear()

        if self._active_job.thread is None:
            return

        # Preserve the former two-stage finite wait as one total deadline.
        deadline = self._shutdown_wait_ms if wait_ms is None else wait_ms
        initial_wait_ms = max(int(deadline), 0)
        second_wait_ms = min(initial_wait_ms + 500, 2_000)
        self._active_job.shutdown(initial_wait_ms + second_wait_ms)

    def _start_job(
        self,
        generation: int,
        asset: Asset,
        key: tuple,
        cache_generation: int,
    ) -> None:
        self._inflight_keys[generation] = (key, cache_generation)
        worker = _PreviewWorker(
            self.provider,
            asset,
            generation,
            disk_cache=self.disk_cache,
            settings=self.settings,
            request_kind=self.request_kind,
            cache_epoch=self._cache_epoch,
            cache_generation=cache_generation,
        )
        self._active_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_finished),
                (worker.failed, self._on_failed),
            ),
        )

    def _start_media_job(
        self,
        generation: int,
        result: PreviewResult,
        key: tuple,
        cache_generation: int,
    ) -> None:
        self._inflight_keys[generation] = (key, cache_generation)
        worker = _MediaPreloadWorker(result, generation)
        self._active_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_finished),
                (worker.failed, self._on_failed),
            ),
        )

    def _on_finished(self, generation: int, result: object) -> None:
        inflight = self._inflight_keys.pop(generation, None)
        key, cache_generation = inflight if inflight is not None else (None, -1)
        if not self._shutting_down and generation == self._generation:
            if (
                key is not None
                and isinstance(result, PreviewResult)
                and result.cacheable
                and self._cache_epoch.is_current(cache_generation)
            ):
                self.cache.put(key, cacheable_result(result))
            self.result_ready.emit(result)
        # Do not start the next job here — wait for thread.finished.

    def _on_failed(self, generation: int, message: str) -> None:
        self._inflight_keys.pop(generation, None)
        if not self._shutting_down and generation == self._generation:
            self.failed.emit(message)

    def _on_thread_finished(self) -> None:
        if self._shutting_down:
            return
        # Defer so Shiboken can finish deleteLater of the prior worker/thread
        # before we spawn another QThread (avoids intermittent offscreen segfaults).
        QTimer.singleShot(0, self._pump_pending)

    def _pump_pending(self) -> None:
        if self._shutting_down or self._active_job.thread is not None:
            return
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        kind, generation, payload, key, cache_generation = pending
        if generation != self._generation:
            return
        if kind == "media":
            assert isinstance(payload, PreviewResult)
            hit = self.cache.get(key)
            if hit is not None and not needs_media_preload(hit):
                self.result_ready.emit(hit)
                return
            self.loading.emit()
            self._start_media_job(
                generation,
                payload if hit is None else hit,
                key,
                cache_generation,
            )
            return
        hit = self.cache.get(key)
        if hit is not None:
            if needs_media_preload(hit):
                self.loading.emit()
                self._start_media_job(generation, hit, key, cache_generation)
                return
            self.result_ready.emit(hit)
            return
        self.loading.emit()
        assert not isinstance(payload, PreviewResult)
        self._start_job(generation, payload, key, cache_generation)
