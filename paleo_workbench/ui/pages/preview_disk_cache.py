from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_cache import safe_file_stat
from paleo_workbench.ui.pages.preview_provider import PreviewResult

if TYPE_CHECKING:
    from geoviz import PreparedPreview, PreviewOptions

logger = logging.getLogger(__name__)

CACHEABLE_RESOURCE_TYPES = frozenset(
    {"horizon", "well_stratification", "well_head"}
)
DIR_NAME = ".preview_cache"


def is_disk_cacheable(asset: object) -> bool:
    return (
        isinstance(asset, ResourceItem)
        and asset.type in CACHEABLE_RESOURCE_TYPES
        and asset.format.strip().lower().lstrip(".") == "dat"
    )


def _options_fingerprint(options: PreviewOptions | None = None) -> str:
    # Runtime import: keep geoviz off cold import of this module.
    from geoviz import PAYLOAD_SCHEMA_VERSION, PreviewOptions as _PreviewOptions

    opts = options or _PreviewOptions.local()
    raw = (
        f"{opts.profile}|{opts.max_curves}|{opts.max_depth_samples}|"
        f"{opts.max_slice_axis}|{opts.max_points}|{opts.surface_grid_size}|"
        f"schema={PAYLOAD_SCHEMA_VERSION}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _entry_key_material(
    asset: ResourceItem,
    options: PreviewOptions | None = None,
    *,
    comparison_crs: str | None = None,
) -> str:
    path = Path(asset.path).resolve()
    st = safe_file_stat(path)
    metadata = asset.parsed_summary or {}
    material = {
        "source_path": str(path),
        "resource_id": asset.id,
        "semantic_type": asset.type,
        "format": asset.format,
        "source_stat": st,
        "checksum": str(asset.checksum or ""),
        "source_crs": str(asset.crs or ""),
        "coordinate_units": str(
            metadata.get("coordinate_units") or metadata.get("units") or ""
        ),
        "comparison_crs": (
            str(comparison_crs)
            if comparison_crs is not None
            else str(metadata.get("comparison_crs") or "")
        ),
        "options": _options_fingerprint(options),
    }
    raw = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _discard_entry(entry: Path) -> None:
    if entry.exists():
        shutil.rmtree(entry, ignore_errors=True)


class PreviewDiskCache:
    """Project-scoped prepare-result cache under ``.preview_cache/``.

    Complements the in-memory LRU: worker tries disk after a memory miss for
    horizon / well_stratification / well_head DAT only. Corrupt entries are
    deleted on read failure. Store failures never break live preview.
    """

    def __init__(
        self,
        project_root: Path | str | None = None,
        *,
        options: PreviewOptions | None = None,
        comparison_crs: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.options = options
        self.comparison_crs = comparison_crs

    def set_options(self, options: PreviewOptions) -> None:
        self.options = options

    def set_project_root(self, project_root: Path | str | None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None

    def set_comparison_crs(self, comparison_crs: str | None) -> None:
        self.comparison_crs = comparison_crs

    def _entries_dir(self) -> Path | None:
        if self.project_root is None:
            return None
        return self.project_root / DIR_NAME / "entries"

    def try_load(self, asset: ResourceItem) -> PreviewResult | None:
        if self.project_root is None or not is_disk_cacheable(asset):
            return None
        entries = self._entries_dir()
        if entries is None:
            return None
        try:
            key = _entry_key_material(
                asset,
                self.options,
                comparison_crs=self.comparison_crs,
            )
        except Exception:
            logger.warning("preview disk cache key failed for %s", asset.path, exc_info=True)
            return None
        entry = entries / key
        meta_path = entry / "meta.json"
        payload_path = entry / "payload.npz"
        if not meta_path.is_file() or not payload_path.is_file():
            return None
        try:
            from geoviz import decode_prepared_preview

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # Re-validate live key matches stored key (mtime/size/options).
            if meta.get("key") != key:
                _discard_entry(entry)
                return None
            with np.load(payload_path, allow_pickle=False) as data:
                arrays = {name: data[name] for name in data.files}
            prepared = decode_prepared_preview(meta["prepared"], arrays)
        except Exception:
            logger.warning(
                "preview disk cache miss (corrupt) for %s at %s",
                asset.path,
                entry,
                exc_info=True,
            )
            _discard_entry(entry)
            return None
        return PreviewResult(
            mode="geoviz",
            title=asset.name,
            path=asset.path,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            warning=prepared.warning,
            summary_rows=prepared.summary_rows,
            engine_preview=prepared,
            estimated_bytes=prepared.estimated_bytes,
        )

    def store(
        self,
        asset: ResourceItem,
        result: PreviewResult,
        *,
        commit_guard: Callable[[], AbstractContextManager[bool]] | None = None,
    ) -> None:
        if self.project_root is None or not is_disk_cacheable(asset):
            return
        if result.mode != "geoviz" or result.engine_preview is None:
            return
        try:
            from geoviz import PreparedPreview, encode_prepared_preview
        except ImportError:  # pragma: no cover
            return
        if not isinstance(result.engine_preview, PreparedPreview):
            return
        entries = self._entries_dir()
        if entries is None:
            return
        try:
            key = _entry_key_material(
                asset,
                self.options,
                comparison_crs=self.comparison_crs,
            )
            prepared_meta, arrays = encode_prepared_preview(result.engine_preview)
            entries.mkdir(parents=True, exist_ok=True)
            # Stage under a unique sibling dir, then replace the entry.
            staging = entries / f".tmp-{key}-{uuid.uuid4().hex}"
            staging.mkdir(parents=True, exist_ok=False)
            try:
                meta = {
                    "key": key,
                    "source_path": str(Path(asset.path).resolve()),
                    "semantic_type": asset.type,
                    "prepared": prepared_meta,
                }
                (staging / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                np.savez_compressed(staging / "payload.npz", **arrays)
                guard = commit_guard() if commit_guard is not None else nullcontext(True)
                with guard as allowed:
                    if not allowed:
                        shutil.rmtree(staging, ignore_errors=True)
                        return
                    entry = entries / key
                    if entry.exists():
                        shutil.rmtree(entry)
                    os.replace(str(staging), str(entry))
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
        except Exception:
            # Preview must still succeed without disk.
            logger.warning(
                "preview disk cache store failed for %s", asset.path, exc_info=True
            )
            return

    def clear(self) -> None:
        if self.project_root is None:
            return
        root = self.project_root / DIR_NAME
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
