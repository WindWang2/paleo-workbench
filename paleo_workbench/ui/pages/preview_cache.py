from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def _safe_stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        return (st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    except OSError:
        return None


def make_preview_cache_key(asset: ResourceItem | ExportArtifact) -> tuple:
    """Stable key for preview LRU entries.

    Includes type/format so rescan reclassification (same path/stat) is a miss.
    Filesystem (size, mtime_ns) invalidates on rewrite; checksum when present.
    """
    if isinstance(asset, ExportArtifact):
        path = Path(asset.output_path)
        return (
            "artifact",
            asset.id,
            asset.output_path,
            asset.format,
            "",
            _safe_stat(path),
        )
    path = Path(asset.path)
    return (
        "resource",
        asset.id,
        asset.path,
        asset.type,
        asset.format,
        asset.checksum or "",
        _safe_stat(path),
    )


class PreviewCache:
    def __init__(self, max_size: int = 32):
        self.max_size = max_size
        self._data: OrderedDict[tuple, PreviewResult] = OrderedDict()

    def get(self, key: tuple) -> PreviewResult | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: tuple, value: PreviewResult) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
