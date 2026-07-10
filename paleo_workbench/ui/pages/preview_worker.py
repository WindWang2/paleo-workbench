from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class _PreviewWorker(QObject):
    finished = Signal(int, object)  # generation, PreviewResult
    failed = Signal(int, str)

    def __init__(
        self,
        provider: PreviewProvider,
        asset: ResourceItem | ExportArtifact,
        generation: int,
        parent=None,
    ):
        super().__init__(parent)
        self._provider = provider
        self._asset = asset
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            result = self._provider.preview(self._asset)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(self._generation, str(exc))
            return
        self.finished.emit(self._generation, result)


class PreviewRequestController(QObject):
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
    ):
        super().__init__(parent)
        self.provider = provider or PreviewProvider()
        self.cache = cache if cache is not None else PreviewCache(max_size=cache_max_size)
        self._generation = 0
        self._jobs: list[tuple[QThread, _PreviewWorker]] = []
        # generation -> cache key for in-flight successful puts
        self._inflight_keys: dict[int, tuple] = {}

    @property
    def generation(self) -> int:
        return self._generation

    def request(self, asset: ResourceItem | ExportArtifact | None) -> None:
        self._generation += 1
        generation = self._generation
        if asset is None:
            self.result_ready.emit(self.provider.preview(None))
            return

        key = make_preview_cache_key(asset)
        hit = self.cache.get(key)
        if hit is not None:
            self.result_ready.emit(hit)
            return

        self.loading.emit()
        self._inflight_keys[generation] = key
        thread = QThread(self)
        worker = _PreviewWorker(self.provider, asset, generation)
        worker.moveToThread(thread)
        self._jobs.append((thread, worker))
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
        if generation != self._generation:
            return
        if key is not None and isinstance(result, PreviewResult):
            self.cache.put(key, result)
        self.result_ready.emit(result)

    def _on_failed(self, generation: int, message: str) -> None:
        self._inflight_keys.pop(generation, None)
        if generation != self._generation:
            return
        self.failed.emit(message)

    def _drop_job(self, thread: QThread, worker: _PreviewWorker) -> None:
        self._jobs = [job for job in self._jobs if job != (thread, worker)]
