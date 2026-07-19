from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewResult

DEFAULT_PREVIEW_CACHE_BYTES = 128 * 1024 * 1024


def preview_result_weight(value: PreviewResult) -> int:
    """Return the payload bytes retained by a cached preview result."""
    if value.estimated_bytes > 0:
        return value.estimated_bytes
    return (
        len(value.text.encode("utf-8"))
        + len(value.image_bytes)
        + len(value.pdf_bytes)
    )


def safe_file_stat(path: Path) -> tuple[int, int] | None:
    """Return ``(size, mtime_ns)`` for cache keys, or None if the path is unreadable."""
    try:
        st = path.stat()
        return (st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    except OSError:
        return None


# Backward-compatible alias for internal call sites / older imports.
_safe_stat = safe_file_stat


def make_preview_cache_key(
    asset: ResourceItem | ExportArtifact,
    settings_fingerprint: str | None = None,
) -> tuple:
    """Stable key for preview LRU entries.

    Includes type/format so rescan reclassification (same path/stat) is a miss.
    Filesystem (size, mtime_ns) invalidates on rewrite; checksum when present.
    """
    if settings_fingerprint is None:
        from paleo_workbench.ui.pages.preview_settings import PreviewSettings

        settings_fingerprint = PreviewSettings.defaults().fingerprint()

    if isinstance(asset, ExportArtifact):
        path = Path(asset.output_path)
        return (
            "artifact",
            asset.id,
            asset.output_path,
            asset.format,
            "",
            safe_file_stat(path),
            settings_fingerprint,
        )
    path = Path(asset.path)
    return (
        "resource",
        asset.id,
        asset.path,
        asset.type,
        asset.format,
        asset.checksum or "",
        safe_file_stat(path),
        settings_fingerprint,
    )


class PreviewCache:
    def __init__(
        self,
        max_size: int = 32,
        max_bytes: int = DEFAULT_PREVIEW_CACHE_BYTES,
    ):
        for name, value in (("max_size", max_size), ("max_bytes", max_bytes)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        self.max_size = max_size
        self.max_bytes = max_bytes
        self.current_bytes = 0
        self._data: OrderedDict[tuple, tuple[PreviewResult, int]] = OrderedDict()

    def get(self, key: tuple) -> PreviewResult | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key][0]

    def put(self, key: tuple, value: PreviewResult) -> None:
        if key in self._data:
            _old_value, old_weight = self._data.pop(key)
            self.current_bytes -= old_weight

        weight = preview_result_weight(value)
        if weight > self.max_bytes:
            return

        self._data[key] = (value, weight)
        self.current_bytes += weight
        while len(self._data) > self.max_size or self.current_bytes > self.max_bytes:
            _old_key, (_old_value, old_weight) = self._data.popitem(last=False)
            self.current_bytes -= old_weight

    def clear(self) -> None:
        self._data.clear()
        self.current_bytes = 0
