from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import numpy as np

from geoviz import (
    PreparedPreview,
    PreviewOptions,
    decode_prepared_preview,
    encode_prepared_preview,
)

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewResult

CACHEABLE_RESOURCE_TYPES = frozenset(
    {"horizon", "well_stratification", "well_head"}
)
DIR_NAME = ".preview_cache"
PAYLOAD_SCHEMA_VERSION = 1  # must match geoviz.prepared_codec


def is_disk_cacheable(asset: object) -> bool:
    return (
        isinstance(asset, ResourceItem)
        and asset.type in CACHEABLE_RESOURCE_TYPES
        and asset.format.strip().lower().lstrip(".") == "dat"
    )


def _options_fingerprint(options: PreviewOptions | None = None) -> str:
    opts = options or PreviewOptions.local()
    raw = (
        f"{opts.profile}|{opts.max_curves}|{opts.max_depth_samples}|"
        f"{opts.max_slice_axis}|{opts.max_points}|{opts.surface_grid_size}|"
        f"schema={PAYLOAD_SCHEMA_VERSION}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _source_stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        return (st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    except OSError:
        return None


def _entry_key_material(asset: ResourceItem) -> str:
    path = Path(asset.path).resolve()
    st = _source_stat(path)
    parts = [
        str(path),
        asset.type,
        asset.format,
        str(st),
        _options_fingerprint(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


class PreviewDiskCache:
    def __init__(self, project_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None

    def set_project_root(self, project_root: Path | str | None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None

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
        key = _entry_key_material(asset)
        entry = entries / key
        meta_path = entry / "meta.json"
        payload_path = entry / "payload.npz"
        if not meta_path.is_file() or not payload_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # Re-validate live key matches stored key (mtime/size/options).
            if meta.get("key") != key:
                return None
            with np.load(payload_path, allow_pickle=False) as data:
                arrays = {name: data[name] for name in data.files}
            prepared = decode_prepared_preview(meta["prepared"], arrays)
        except Exception:
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

    def store(self, asset: ResourceItem, result: PreviewResult) -> None:
        if self.project_root is None or not is_disk_cacheable(asset):
            return
        if result.mode != "geoviz" or not isinstance(
            result.engine_preview, PreparedPreview
        ):
            return
        entries = self._entries_dir()
        if entries is None:
            return
        key = _entry_key_material(asset)
        entry = entries / key
        try:
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
                if entry.exists():
                    shutil.rmtree(entry)
                os.replace(str(staging), str(entry))
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
        except Exception:
            return  # preview must still succeed without disk

    def clear(self) -> None:
        if self.project_root is None:
            return
        root = self.project_root / DIR_NAME
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
