# Project Preview Disk Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist bounded GeoViz prepare results for horizon / well_stratification / well_head under `<project>/.preview_cache/`, so re-select skips re-parse while LAS and SGY stay fully interactive.

**Architecture:** A public `geoviz` codec round-trips cacheable `PreparedPreview` payloads without Qt. Workbench owns project paths, cache keys (path+mtime+size+options), atomic file I/O, and a worker-side try-disk-then-prepare path. In-memory LRU remains first; disk is the second tier. UI still renders via `GeoVizPreviewHost`.

**Tech Stack:** Python 3.12, NumPy, PySide6, existing `PreviewRequestController` / `LocalVisualizationProvider`, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-preview-disk-cache-design.md`

## Global Constraints

- LAS / SGY must not read or write `.preview_cache/` in v1.
- Cacheable semantic types only: `horizon`, `well_stratification`, `well_head`.
- Worker thread: stat, disk I/O, deserialize, `prepare`, serialize. UI thread: widget create/render only.
- Workbench production code imports only the public `geoviz` facade (no `geoviz.*` internals, no `geoviz_*`).
- `geo-viz-engine` must not import `paleo_workbench`.
- Nested engine commits first; parent stages gitlink only after engine tip is usable.
- No project root → skip disk cache (memory-only), still preview via live prepare.
- Corrupt / incomplete entries → miss + live prepare; never crash the reader.

## File Structure

### Engine (`geo-viz-engine`)

- Create `geoviz/prepared_codec.py`: encode/decode cacheable `PreparedPreview` to meta JSON + NumPy arrays (no Qt).
- Modify `geoviz/__init__.py`: export `encode_prepared_preview`, `decode_prepared_preview`, `CACHEABLE_PREVIEW_KINDS` (or equivalent).
- Create `tests/test_geoviz_prepared_codec.py`.

### Workbench

- Create `paleo_workbench/ui/pages/preview_disk_cache.py`: roots, keys, atomic write/read, clear, corruption handling.
- Modify `paleo_workbench/ui/pages/preview_worker.py`: inject disk cache into worker path for cacheable resources.
- Modify `paleo_workbench/ui/pages/geoviz_preview_provider.py` or small helper: `is_disk_cacheable(asset) -> bool`.
- Modify `paleo_workbench/resources/classifier.py`: classify `井位` path segment as `well_head` (so well-head DAT can hit GeoViz + cache).
- Modify `paleo_workbench/ui/pages/data_page.py`: set project root on controller; expose clear action.
- Modify `paleo_workbench/ui/pages/data_toolbar.py` or menu wiring: “清除预览缓存” (minimal: toolbar or page method called from menu).
- Modify `.gitignore`: ignore `**/.preview_cache/` if not covered.
- Create `tests/test_preview_disk_cache.py`.
- Extend `tests/test_preview_async.py` and/or `tests/test_geoviz_preview_provider.py` for hit/miss/isolation.
- Modify `tests/test_resources_classifier.py`: well_head path case.
- Modify `progress.md`: short verification note.

---

### Task 1: Public prepared-preview codec (engine)

**Files:**
- Create: `geo-viz-engine/geoviz/prepared_codec.py`
- Modify: `geo-viz-engine/geoviz/__init__.py`
- Test: `geo-viz-engine/tests/test_geoviz_prepared_codec.py`

**Interfaces:**
- Consumes: `PreparedPreview`, `PreviewKind`, DAT payloads (`XYPreviewPayload`, `SurfacePreviewPayload`), `FormationTop` tuple.
- Produces: `(meta: dict, arrays: dict[str, np.ndarray])` encode; reverse decode; raise `ValueError` on unsupported kind / schema.

- [ ] **Step 1: Write failing codec tests**

```python
# geo-viz-engine/tests/test_geoviz_prepared_codec.py
from __future__ import annotations

import numpy as np
import pytest

from geoviz import (
    PreparedPreview,
    PreviewKind,
    decode_prepared_preview,
    encode_prepared_preview,
)
from geoviz.previews.dat import SurfacePreviewPayload, XYPreviewPayload
from geoviz_cross_well import FormationTop


def test_roundtrip_xy_scatter():
    payload = XYPreviewPayload(
        names=("A1", "B2"),
        x=np.array([1.0, 2.0]),
        y=np.array([3.0, 4.0]),
    )
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="wells",
        payload=payload,
        summary_rows=(("井数", "2"),),
        estimated_bytes=64,
    )
    meta, arrays = encode_prepared_preview(prepared)
    restored = decode_prepared_preview(meta, arrays)
    assert restored.kind is PreviewKind.XY_SCATTER
    assert restored.title == "wells"
    assert restored.summary_rows == (("井数", "2"),)
    assert list(restored.payload.names) == ["A1", "B2"]
    np.testing.assert_array_equal(restored.payload.x, payload.x)
    np.testing.assert_array_equal(restored.payload.y, payload.y)


def test_roundtrip_surface():
    payload = SurfacePreviewPayload(
        grid_x=np.array([0.0, 1.0]),
        grid_y=np.array([0.0, 1.0]),
        grid_z=np.array([[1.0, 2.0], [3.0, 4.0]]),
        levels=(1.5, 2.5),
    )
    prepared = PreparedPreview(
        kind=PreviewKind.SURFACE,
        title="hz",
        payload=payload,
        estimated_bytes=128,
    )
    restored = decode_prepared_preview(*encode_prepared_preview(prepared))
    np.testing.assert_array_equal(restored.payload.grid_z, payload.grid_z)
    assert restored.payload.levels == (1.5, 2.5)


def test_roundtrip_formation_tops():
    tops = (
        FormationTop("W1", "A", 100.0, color="#111111"),
        FormationTop("W2", "A", 110.0, color="#111111"),
    )
    prepared = PreparedPreview(
        kind=PreviewKind.FORMATION_TOPS,
        title="tops",
        payload=tops,
        estimated_bytes=32,
    )
    restored = decode_prepared_preview(*encode_prepared_preview(prepared))
    assert len(restored.payload) == 2
    assert restored.payload[0].well_name == "W1"
    assert restored.payload[0].depth_m == 100.0


def test_rejects_well_log_kind():
    with pytest.raises(ValueError):
        encode_prepared_preview(
            PreparedPreview(kind=PreviewKind.WELL_LOG, title="x", payload=object())
        )
```

Note: tests under engine may import `geoviz.previews.dat` for fixture construction; production workbench must not.

- [ ] **Step 2: Run tests — expect FAIL (import errors)**

```bash
cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_prepared_codec.py -q
```

Expected: FAIL (`encode_prepared_preview` not found).

- [ ] **Step 3: Implement codec**

```python
# geo-viz-engine/geoviz/prepared_codec.py
from __future__ import annotations

from typing import Any

import numpy as np

from geoviz_cross_well import FormationTop

from .contracts import PreparedPreview, PreviewKind
from .previews.dat import SurfacePreviewPayload, XYPreviewPayload

PAYLOAD_SCHEMA_VERSION = 1
CACHEABLE_KINDS = frozenset(
    {PreviewKind.XY_SCATTER, PreviewKind.SURFACE, PreviewKind.FORMATION_TOPS}
)


def encode_prepared_preview(
    preview: PreparedPreview,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if preview.kind not in CACHEABLE_KINDS:
        raise ValueError(f"unsupported kind for disk cache: {preview.kind}")
    meta: dict[str, Any] = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "kind": str(preview.kind),
        "title": preview.title,
        "summary_rows": [list(row) for row in preview.summary_rows],
        "warning": preview.warning,
        "estimated_bytes": preview.estimated_bytes,
    }
    arrays: dict[str, np.ndarray] = {}
    if preview.kind is PreviewKind.XY_SCATTER:
        payload = preview.payload
        if not isinstance(payload, XYPreviewPayload):
            raise ValueError("XY_SCATTER payload type mismatch")
        meta["names"] = list(payload.names)
        arrays["x"] = np.asarray(payload.x)
        arrays["y"] = np.asarray(payload.y)
    elif preview.kind is PreviewKind.SURFACE:
        payload = preview.payload
        if not isinstance(payload, SurfacePreviewPayload):
            raise ValueError("SURFACE payload type mismatch")
        meta["levels"] = list(payload.levels)
        arrays["grid_x"] = np.asarray(payload.grid_x)
        arrays["grid_y"] = np.asarray(payload.grid_y)
        arrays["grid_z"] = np.asarray(payload.grid_z)
    else:  # FORMATION_TOPS
        tops = preview.payload
        if not (
            isinstance(tops, tuple) and all(isinstance(t, FormationTop) for t in tops)
        ):
            raise ValueError("FORMATION_TOPS payload type mismatch")
        meta["tops"] = [
            {
                "well_name": t.well_name,
                "formation_name": t.formation_name,
                "depth_m": float(t.depth_m),
                "color": t.color,
            }
            for t in tops
        ]
    return meta, arrays


def decode_prepared_preview(
    meta: dict[str, Any], arrays: dict[str, np.ndarray]
) -> PreparedPreview:
    if int(meta.get("schema_version", -1)) != PAYLOAD_SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    kind = PreviewKind(meta["kind"])
    if kind not in CACHEABLE_KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    summary = tuple((str(a), str(b)) for a, b in meta.get("summary_rows", ()))
    if kind is PreviewKind.XY_SCATTER:
        payload = XYPreviewPayload(
            names=tuple(meta["names"]),
            x=np.asarray(arrays["x"]),
            y=np.asarray(arrays["y"]),
        )
    elif kind is PreviewKind.SURFACE:
        payload = SurfacePreviewPayload(
            grid_x=np.asarray(arrays["grid_x"]),
            grid_y=np.asarray(arrays["grid_y"]),
            grid_z=np.asarray(arrays["grid_z"]),
            levels=tuple(float(x) for x in meta.get("levels", ())),
        )
    else:
        payload = tuple(
            FormationTop(
                row["well_name"],
                row["formation_name"],
                float(row["depth_m"]),
                color=str(row.get("color") or ""),
            )
            for row in meta.get("tops", ())
        )
    return PreparedPreview(
        kind=kind,
        title=str(meta.get("title") or ""),
        payload=payload,
        summary_rows=summary,
        warning=str(meta.get("warning") or ""),
        estimated_bytes=int(meta.get("estimated_bytes") or 0),
    )
```

Export from `geoviz/__init__.py`:

```python
from .prepared_codec import decode_prepared_preview, encode_prepared_preview

# add to __all__
```

- [ ] **Step 4: Run codec tests — expect PASS**

```bash
cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_prepared_codec.py -q
```

Expected: all passed.

- [ ] **Step 5: Commit engine**

```bash
git -C geo-viz-engine add geoviz/prepared_codec.py geoviz/__init__.py tests/test_geoviz_prepared_codec.py
git -C geo-viz-engine commit -m "feat: add prepared preview disk codec"
```

---

### Task 2: Workbench disk cache module

**Files:**
- Create: `paleo_workbench/ui/pages/preview_disk_cache.py`
- Create: `tests/test_preview_disk_cache.py`
- Modify: `.gitignore` (add `**/.preview_cache/`)

**Interfaces:**
- `CACHEABLE_RESOURCE_TYPES = frozenset({"horizon", "well_stratification", "well_head"})`
- `class PreviewDiskCache`: `project_root: Path | None`, `try_load(asset) -> PreviewResult | None`, `store(asset, result) -> None`, `clear() -> None`
- Key fingerprint includes options from `PreviewOptions.local()` fields that affect prepare.

- [ ] **Step 1: Write failing unit tests**

```python
# tests/test_preview_disk_cache.py
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geoviz import PreparedPreview, PreviewKind
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_disk_cache import (
    CACHEABLE_RESOURCE_TYPES,
    PreviewDiskCache,
)
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def _well_head_result(path: Path) -> PreviewResult:
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="wells",
        payload=XYPreviewPayload(
            names=("A1",),
            x=np.array([1.0]),
            y=np.array([2.0]),
        ),
        estimated_bytes=32,
    )
    return PreviewResult(
        mode="geoviz",
        title="wells",
        path=str(path),
        format="dat",
        type_label="well_head",
        engine_preview=prepared,
        estimated_bytes=32,
    )


def test_store_and_load_roundtrip(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("#WellHead File From SMI\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    loaded = cache.try_load(asset)
    assert loaded is not None
    assert loaded.mode == "geoviz"
    assert isinstance(loaded.engine_preview, PreparedPreview)
    assert loaded.engine_preview.kind is PreviewKind.XY_SCATTER


def test_mtime_change_is_miss(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    src.write_text("v2\n", encoding="utf-8")
    assert cache.try_load(asset) is None


def test_corrupt_payload_is_miss(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    entries = list((root / ".preview_cache" / "entries").iterdir())
    assert entries
    (entries[0] / "payload.npz").write_bytes(b"not-npz")
    assert cache.try_load(asset) is None


def test_clear_removes_entries(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    cache.clear()
    assert cache.try_load(asset) is None
    assert not (root / ".preview_cache" / "entries").exists() or not any(
        (root / ".preview_cache" / "entries").iterdir()
    )


def test_no_project_root_skips_disk(tmp_path: Path):
    src = tmp_path / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=None)
    cache.store(asset, _well_head_result(src))
    assert cache.try_load(asset) is None


def test_cacheable_type_set():
    assert CACHEABLE_RESOURCE_TYPES == {
        "horizon",
        "well_stratification",
        "well_head",
    }
```

Note: tests may construct payloads via engine packages; production disk cache must use only `geoviz.encode_prepared_preview` / `decode_prepared_preview`.

- [ ] **Step 2: Run — expect FAIL**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_preview_disk_cache.py -q
```

Expected: FAIL (module missing).

- [ ] **Step 3: Implement `preview_disk_cache.py`**

Core API sketch:

```python
# paleo_workbench/ui/pages/preview_disk_cache.py
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict
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
        key = _entry_key_material(asset)
        entry = self._entries_dir() / key  # type: ignore[operator]
        meta_path = entry / "meta.json"
        payload_path = entry / "payload.npz"
        if not meta_path.is_file() or not payload_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # re-validate live stat matches stored key material via recompute
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
            with tempfile.TemporaryDirectory(dir=str(entries)) as tmp:
                tmp_path = Path(tmp)
                meta = {
                    "key": key,
                    "source_path": str(Path(asset.path).resolve()),
                    "semantic_type": asset.type,
                    "prepared": prepared_meta,
                }
                (tmp_path / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                np.savez_compressed(tmp_path / "payload.npz", **arrays)
                if entry.exists():
                    shutil.rmtree(entry)
                shutil.move(str(tmp_path), str(entry))
                # TemporaryDirectory cleanup: move emptied it; recreate empty to avoid errors
                tmp_path.mkdir(exist_ok=True)
        except Exception:
            return  # preview must still succeed without disk

    def clear(self) -> None:
        if self.project_root is None:
            return
        root = self.project_root / DIR_NAME
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
```

Fix atomic replace carefully: write into `entries/.tmp-<key>/` then `os.replace` directory if platform allows, or write files into entry via temp names + replace. Prefer:

1. Create `entry_dir` with `meta.json.tmp` / `payload.npz.tmp`
2. `os.replace` each into final names
3. Write `key` into meta only after both payload and meta are consistent

Implementers: choose a robust atomic pattern; tests only require no half-valid hit.

Add to `.gitignore`:

```gitignore
**/.preview_cache/
```

- [ ] **Step 4: Run unit tests — expect PASS**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_preview_disk_cache.py -q
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_disk_cache.py tests/test_preview_disk_cache.py .gitignore
git add geo-viz-engine  # gitlink if Task 1 already pushed into nested repo
git commit -m "feat: add project preview disk cache store"
```

(If Task 1 engine commit exists, stage `geo-viz-engine` gitlink in the same or prior parent commit.)

---

### Task 3: Classify well_head paths

**Files:**
- Modify: `paleo_workbench/resources/classifier.py`
- Modify: `tests/test_resources_classifier.py`

- [ ] **Step 1: Failing test**

```python
def test_well_head_dat_under_well_folder():
    assert classify_path(Path("井位/ExportWellHead.dat")) == (
        "well_head",
        "dat",
        "indexed",
    )
```

- [ ] **Step 2: Run — expect FAIL** (currently `tabular`)

- [ ] **Step 3: Implement**

In `classify_path` DAT branch, before tabular default:

```python
if any("井位" in part for part in path_parts) or "wellhead" in name or "well_head" in name:
    return "well_head", ext, "indexed"
```

Keep existing horizon / well_stratification / time_depth rules; order time_depth and horizon before well_head if paths could overlap.

- [ ] **Step 4: Run classifier tests — PASS**

```bash
.venv/bin/python -m pytest tests/test_resources_classifier.py -q
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/resources/classifier.py tests/test_resources_classifier.py
git commit -m "fix: classify well-head DAT semantic type"
```

---

### Task 4: Wire disk cache into preview worker

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_worker.py`
- Modify: `tests/test_preview_async.py` (or new tests in `tests/test_preview_disk_cache.py`)

**Behavior:**
- `PreviewRequestController` holds optional `PreviewDiskCache`.
- `_PreviewWorker.run`: if cacheable and `disk.try_load` returns result → emit without `provider.preview`; else `provider.preview`, then `disk.store` on success for cacheable geoviz results.
- LAS/SGY never call disk methods with storeable types (guarded by `is_disk_cacheable`).
- Stale generation: existing controller logic; optional: skip `store` if generation already stale (controller stores only on current gen — disk write can stay in worker; duplicate write OK).

- [ ] **Step 1: Failing integration test**

```python
def test_second_request_uses_disk_without_prepare(tmp_path, qtbot):
    # Project root = tmp_path
    # Resource well_head DAT on disk
    # Provider/engine.prepare wrapped with call counter
    # First controller.request → prepare_calls == 1 and cache entry exists
    # Clear in-memory PreviewCache only
    # Second controller.request → prepare_calls still 1, result_ready geoviz
```

Implement with a thin spy on `LocalVisualizationProvider` or mock engine `prepare`.

Also:

```python
def test_las_never_writes_preview_cache(tmp_path, qtbot):
    # Select LAS resource twice with project_root set
    # assert not (tmp_path / ".preview_cache").exists() or no entries for that key
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Wire worker**

```python
# _PreviewWorker.__init__ adds disk_cache: PreviewDiskCache | None
# run():
#   if isinstance(self._asset, ResourceItem) and self._disk is not None:
#       hit = self._disk.try_load(self._asset)
#       if hit is not None:
#           self.finished.emit(self._generation, hit)
#           return
#   result = self._provider.preview(self._asset)
#   ...
#   if self._disk is not None and isinstance(self._asset, ResourceItem):
#       self._disk.store(self._asset, result)
#   self.finished.emit(...)
```

Controller:

```python
def __init__(..., disk_cache: PreviewDiskCache | None = None):
    self.disk_cache = disk_cache or PreviewDiskCache(None)

def set_project_root(self, root: Path | str | None) -> None:
    self.disk_cache.set_project_root(root)

def clear_disk_cache(self) -> None:
    self.disk_cache.clear()
    self.cache.clear()  # memory too
```

Pass `disk_cache` into `_PreviewWorker`.

- [ ] **Step 4: Run focused tests — PASS**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_preview_disk_cache.py tests/test_preview_async.py \
  tests/test_geoviz_preview_provider.py -q --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_worker.py tests/test_preview_async.py tests/test_preview_disk_cache.py
git commit -m "feat: use disk cache in preview worker"
```

---

### Task 5: Project root + clear action on data page

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/ui/pages/data_toolbar.py` (or menu) for clear action if low-friction
- Modify: `tests/test_data_page.py` (or focused new test)

**Behavior:**
- On `update_state` / project load, set `self._preview_controller.set_project_root(project.meta.project_root)` (resolve if relative).
- Method `clear_preview_cache()` → controller clear + optional status message.
- UI: add a toolbar or context-free action “清除预览缓存”. Prefer `DataToolbar` overflow/menu button if one exists; else a method + QAction on page wired from app menu later is OK, but plan requires **one visible entry**:
  - Add `clear_preview_cache_btn` on `DataToolbar` next to rescan, or
  - Add action under data page that tests can call: `page.clear_preview_cache()`.

Minimum for v1: public method + unit test; wire button if toolbar pattern is trivial.

- [ ] **Step 1: Test project root propagation and clear**

```python
def test_data_page_clear_preview_cache(tmp_path, qtbot):
    # open page with project_root=tmp_path
    # plant a fake .preview_cache/entries/x
    # page.clear_preview_cache()
    # directory gone; memory cache empty
```

- [ ] **Step 2: Implement**

```python
def clear_preview_cache(self) -> None:
    self._preview_controller.clear_disk_cache()
```

In `update_state`:

```python
root = getattr(self.project.meta, "project_root", None) or None
self._preview_controller.set_project_root(root)
```

- [ ] **Step 3: Run data page focused tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_data_page.py tests/test_preview_disk_cache.py -q --timeout=30
```

- [ ] **Step 4: Commit**

```bash
git add paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/pages/data_toolbar.py tests/test_data_page.py
git commit -m "feat: clear project preview disk cache from data page"
```

---

### Task 6: Final verification and progress note

**Files:**
- Modify: `progress.md`
- Update gitlink if engine advanced

- [ ] **Step 1: Run engine codec + workbench focused suites**

```bash
cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_geoviz_prepared_codec.py tests/test_geoviz_dat_preview.py -q --timeout=60

cd .. && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_preview_disk_cache.py \
  tests/test_preview_async.py \
  tests/test_geoviz_preview_provider.py \
  tests/test_geoviz_preview_host.py \
  tests/test_resources_classifier.py \
  tests/test_data_page.py \
  -vv --timeout=30
```

Expected: all selected tests pass (use known offscreen stall workarounds: `--timeout=30`, avoid bare `-q` if hangs).

- [ ] **Step 2: Optional real-data smoke still green**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_geoviz_real_data_smoke.py -m slow -q --timeout=120
```

- [ ] **Step 3: Append `progress.md` section**

```markdown
## Session: 2026-07-16 — Preview disk cache

Project-local `.preview_cache/` stores bounded prepare results for horizon /
well_stratification / well_head. LAS and SGY remain interactive without disk
cache. Clear via DataPage.clear_preview_cache().
```

- [ ] **Step 4: Commit**

```bash
git add progress.md geo-viz-engine
git commit -m "docs: record preview disk cache verification"
```

- [ ] **Step 5: Mark design status Approved** in spec header if still Draft.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `.preview_cache/` under project | Task 2 |
| Cacheable: horizon, well_stratification, well_head | Tasks 2–4 |
| LAS/SGY unchanged / no disk | Task 4 tests |
| Bounded prepare payload not screenshots | Task 1 codec |
| Worker I/O + prepare | Task 4 |
| UI render only | unchanged host; Task 4 |
| Key: path+mtime+size+options | Task 2 |
| Corrupt → miss | Task 2 |
| No project root → skip disk | Task 2 |
| Clear action | Task 5 |
| well_head classifiable in practice | Task 3 |
| Memory LRU first | existing + Task 4 |

## Placeholder / consistency notes

- Codec schema version `1` must match between `geoviz.prepared_codec` and workbench fingerprint.
- Atomic directory move on Windows may need file-level replace; tests only require consistency.
- Do not import `geoviz.previews.dat` from workbench production modules — only from engine tests or codec internals.
