"""Metadata-first seismic volume access for 2D slices and 3D preview LODs.

Wraps ``geoviz.SeismicLoader`` (already supports inspect / read_inline /
read_crossline / read_timeslice / strided downsampling) with:

* stable ``source_id`` (path + size + mtime)
* shared byte-budget cache
* LOD / preview reads without materialising full native-resolution cubes
* optional generation tracking for latest-request-wins consumers

Does **not** rewrite RAW SEG-Y; all outputs are ephemeral display/preview arrays.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from paleo_workbench.viz.seismic_volume_cache import (
    SeismicCacheKey,
    SeismicVolumeCache,
    get_global_seismic_cache,
)

Orientation = Literal["inline", "crossline", "timeslice"]

# Preview budget for dense ndarray adapters (prediction / joint 3D fallback).
DEFAULT_PREVIEW_MAX_DIM = 128
DEFAULT_PREVIEW_BUDGET = (
    DEFAULT_PREVIEW_MAX_DIM * DEFAULT_PREVIEW_MAX_DIM * DEFAULT_PREVIEW_MAX_DIM
)


@dataclass(frozen=True, slots=True)
class SeismicVolumeMetadata:
    path: str
    source_id: str
    n_inlines: int
    n_crosslines: int
    n_samples: int
    sample_interval_ms: float
    iline_start: int
    iline_step: int
    xline_start: int
    xline_step: int
    t0_ms: float
    has_geometry: bool
    is_pseudo: bool = False
    metadata_ms: float = 0.0

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.n_inlines, self.n_crosslines, self.n_samples)

    def iline_number(self, index: int) -> int:
        return int(self.iline_start + index * self.iline_step)

    def xline_number(self, index: int) -> int:
        return int(self.xline_start + index * self.xline_step)


def source_id_for_path(path: str | Path) -> str:
    """Identity that invalidates cache when the file is replaced on disk.

    Size+mtime alone miss a same-size replacement with preserved mtime
    (``cp -p`` / ``rsync -a`` / restored archives). The inode number
    (st_ino) + device (st_dev) detect any actual file swap even when every
    timestamp is preserved (H10 cache identity).
    """
    p = Path(path)
    try:
        st = p.stat()
        return (
            f"{p.resolve().as_posix()}|{st.st_size}|{int(st.st_mtime_ns)}"
            f"|{st.st_dev}|{st.st_ino}"
        )
    except OSError:
        return f"{p.as_posix()}|missing"


def preview_strides(
    n_il: int,
    n_xl: int,
    n_s: int,
    *,
    max_dim: int = DEFAULT_PREVIEW_MAX_DIM,
    max_budget: int = DEFAULT_PREVIEW_BUDGET,
) -> tuple[int, int, int]:
    """Compute positive strides so downsampled volume fits max_dim / budget."""
    fi = max(1, math.ceil(n_il / max_dim)) if n_il > 0 else 1
    fx = max(1, math.ceil(n_xl / max_dim)) if n_xl > 0 else 1
    ft = max(1, math.ceil(n_s / max_dim)) if n_s > 0 else 1
    # Grow strides if voxel budget still exceeds.
    while True:
        out_il = max(1, math.ceil(n_il / fi)) if n_il else 1
        out_xl = max(1, math.ceil(n_xl / fx)) if n_xl else 1
        out_s = max(1, math.ceil(n_s / ft)) if n_s else 1
        if out_il * out_xl * out_s <= max_budget:
            break
        # Prefer coarsening the longest remaining axis.
        dims = [(out_il, 0), (out_xl, 1), (out_s, 2)]
        dims.sort(reverse=True)
        axis = dims[0][1]
        if axis == 0:
            fi += 1
        elif axis == 1:
            fx += 1
        else:
            ft += 1
    return (fi, fx, ft)


class _InFlightPreviewRead:
    """Single-flight slot for one preview cache key.

    The first caller performs the read and publishes ``result``/``warning``
    (or ``error``) through a ``threading.Event``; concurrent callers for the
    same key wait on the event and reuse the first read instead of issuing a
    duplicate full strided/pseudo pass (C43 in-flight dedup).
    """

    __slots__ = ("event", "result", "warning", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.warning: str = ""
        self.error: BaseException | None = None


class SeismicVolumeSource:
    """Lazy SEGY accessor with shared cache and LOD/preview helpers."""

    def __init__(
        self,
        path: str | Path,
        *,
        cache: SeismicVolumeCache | None = None,
    ) -> None:
        self._path = str(Path(path))
        self._cache = cache if cache is not None else get_global_seismic_cache()
        self._loader = None
        self._meta: SeismicVolumeMetadata | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._is_pseudo = False
        self.physical_reads = 0
        self._in_flight: dict[SeismicCacheKey, _InFlightPreviewRead] = {}

    # ------------------------------------------------------------------ open
    @property
    def path(self) -> str:
        return self._path

    @property
    def source_id(self) -> str:
        if self._meta is not None:
            return self._meta.source_id
        return source_id_for_path(self._path)

    def metadata(self) -> SeismicVolumeMetadata:
        """Open headers only (no volume materialisation)."""
        with self._lock:
            if self._meta is not None:
                return self._meta
            if self._closed:
                raise RuntimeError("SeismicVolumeSource is closed")
            t0 = time.perf_counter()
            if not Path(self._path).is_file():
                raise FileNotFoundError(self._path)
            try:
                from geoviz import SeismicLoader

                loader = SeismicLoader(self._path)
                raw = loader.inspect()
                self._loader = loader
                # The loader's unstructured fallback mocks 1 inline x N crosslines
                # when real ilines/xlines are absent; that pseudo geometry must
                # not bind a survey or serve structured slice reads.
                has_geometry = self._loader_has_geometry()
                self._meta = SeismicVolumeMetadata(
                    path=self._path,
                    source_id=source_id_for_path(self._path),
                    n_inlines=int(raw.n_inlines),
                    n_crosslines=int(raw.n_crosslines),
                    n_samples=int(raw.n_samples),
                    sample_interval_ms=float(raw.sample_interval),
                    iline_start=int(raw.iline_start),
                    iline_step=int(raw.iline_step),
                    xline_start=int(raw.xline_start),
                    xline_step=int(raw.xline_step),
                    t0_ms=float(getattr(raw, "t0_ms", 0.0) or 0.0),
                    has_geometry=has_geometry,
                    is_pseudo=not has_geometry,
                    metadata_ms=(time.perf_counter() - t0) * 1000.0,
                )
                return self._meta
            except Exception:
                # Geometry/loader failed — keep source openable for pseudo path.
                self._is_pseudo = True
                self._meta = SeismicVolumeMetadata(
                    path=self._path,
                    source_id=source_id_for_path(self._path),
                    n_inlines=0,
                    n_crosslines=0,
                    n_samples=0,
                    sample_interval_ms=4.0,
                    iline_start=1,
                    iline_step=1,
                    xline_start=1,
                    xline_step=1,
                    t0_ms=0.0,
                    has_geometry=False,
                    is_pseudo=True,
                    metadata_ms=(time.perf_counter() - t0) * 1000.0,
                )
                return self._meta

    def close(self) -> None:
        with self._lock:
            source_id = self.source_id
            self._closed = True
            if self._loader is not None:
                try:
                    self._loader.close()
                except Exception:
                    pass
                self._loader = None
            # Keep _meta for source_id identity after close; drop the loader so
            # later reads cannot refill the shared cache with a pseudo cube.
        # Do not flush the process-global cache: a sibling shared source may
        # still be serving slices under the same source_id.
        if self._cache is not get_global_seismic_cache():
            try:
                self._cache.invalidate_source(source_id)
            except Exception:
                pass

    def _loader_has_geometry(self) -> bool:
        """True when the loader's open handle exposes real ilines/xlines.

        ``None`` means segyio opened the file unstructured; slice reads would
        then fail with raw TypeError/AttributeError inside the loader.
        """
        handle = getattr(self._loader, "_f", None)
        return (
            handle is not None
            and getattr(handle, "ilines", None) is not None
            and getattr(handle, "xlines", None) is not None
        )

    def __enter__(self) -> "SeismicVolumeSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ slices
    def read_inline(self, index: int, *, lod: int = 0) -> np.ndarray:
        return self._read_orientation("inline", index, lod=lod)

    def read_crossline(self, index: int, *, lod: int = 0) -> np.ndarray:
        return self._read_orientation("crossline", index, lod=lod)

    def read_timeslice(self, index: int, *, lod: int = 0) -> np.ndarray:
        return self._read_orientation("timeslice", index, lod=lod)

    def _read_orientation(
        self, kind: Orientation, index: int, *, lod: int = 0
    ) -> np.ndarray:
        if self._closed:
            raise RuntimeError("SeismicVolumeSource is closed")
        meta = self.metadata()
        if (
            meta.is_pseudo
            or self._loader is None
            or not self._loader_has_geometry()
        ):
            raise RuntimeError(
                "lazy slice requires structured SEGY geometry; use read_preview()"
            )
        key = SeismicCacheKey(
            source_id=meta.source_id,
            kind=kind,
            index=int(index),
            lod=int(lod),
        )
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        with self._lock:
            # Double-check under lock.
            hit = self._cache.get(key)
            if hit is not None:
                return hit
            loader = self._loader
            assert loader is not None
            if kind == "inline":
                iline = meta.iline_number(int(index))
                data = loader.read_inline(iline)
            elif kind == "crossline":
                xline = meta.xline_number(int(index))
                data = loader.read_crossline(xline)
            else:
                data = loader.read_timeslice(int(index))
            self.physical_reads += 1
            if lod > 0:
                data = _downsample_2d(data, step=2**lod)
            return self._cache.put(key, data)

    # ------------------------------------------------------------------ LOD / preview
    def read_preview(
        self,
        *,
        max_dim: int = DEFAULT_PREVIEW_MAX_DIM,
        max_budget: int = DEFAULT_PREVIEW_BUDGET,
        lod: int = 0,
        cancellation_token=None,
    ) -> tuple[np.ndarray | None, str]:
        """Dense bounded volume for 3D/prediction adapters (not full-res cube).

        Uses strided engine downsampling when geometry is available; falls back
        to the legacy pseudo-3D path only when geometry is absent.
        """
        if self._closed:
            raise RuntimeError("SeismicVolumeSource is closed")
        meta = self.metadata()
        key = SeismicCacheKey(
            source_id=meta.source_id,
            kind="preview",
            index=0,
            lod=int(lod),
            attribute=f"d{max_dim}_b{max_budget}",
        )
        hit = self._cache.get(key)
        if hit is not None:
            return hit, ""

        pseudo = (
            meta.is_pseudo
            or self._loader is None
            or not self._loader_has_geometry()
        )

        # Single-flight: claim the slot under lock, then perform the read
        # WITHOUT holding the lock (long strided/pseudo reads must not block
        # foreground slice reads, H10). Concurrent callers for the same key
        # wait on the first read instead of duplicating it (C43).
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                return hit, ""
            slot = self._in_flight.get(key)
            if slot is None:
                slot = _InFlightPreviewRead()
                self._in_flight[key] = slot
                owner = True
            else:
                owner = False
            if owner and cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if not pseudo:
                assert self._loader is not None

        if not owner:
            slot.event.wait()
            with self._lock:
                self._in_flight.pop(key, None)
            if slot.error is not None:
                raise slot.error
            cached = self._cache.get(key)
            if cached is not None:
                return cached, slot.warning
            return slot.result, slot.warning

        try:
            if pseudo:
                from paleo_workbench.viz.seismic_load import (
                    _load_pseudo_3d_ignore_geometry,
                )

                vol, warning = _load_pseudo_3d_ignore_geometry(self._path)
                if vol is None:
                    self._publish_in_flight(key, slot, None, warning or "SEGY preview failed")
                    return None, warning or "SEGY preview failed"
                cached = self._cache.put(key, vol)
                self._publish_in_flight(
                    key,
                    slot,
                    cached,
                    warning or "SEGY 无完整三维几何，已按伪三维预览",
                )
                return cached, warning or "SEGY 无完整三维几何，已按伪三维预览"

            strides = preview_strides(
                meta.n_inlines,
                meta.n_crosslines,
                meta.n_samples,
                max_dim=max_dim,
                max_budget=max_budget,
            )
            # Extra LOD coarsens further.
            if lod > 0:
                scale = 2**lod
                strides = tuple(max(1, s * scale) for s in strides)  # type: ignore[assignment]

            # Long volume reads must NOT hold the source lock: foreground slice
            # reads on the GUI thread would freeze for the whole read (H10). Use
            # a fresh per-call loader handle so concurrent slice reads proceed
            # independently.
            from geoviz import SeismicLoader

            fresh_loader = SeismicLoader(self._path)
            volume = fresh_loader.get_volume_downsampled(
                factor=strides, cancellation_token=cancellation_token
            )
            self.physical_reads += 1
            vol = np.ascontiguousarray(volume, dtype=np.float32)
            # Final bound if budget still exceeded (safety).
            from paleo_workbench.viz.seismic_load import _bound_volume

            vol, further = _bound_volume(vol)
            warning = ""
            if strides != (1, 1, 1) or further:
                warning = (
                    f"SEGY 已按 LOD 预览加载 "
                    f"(shape={tuple(int(x) for x in vol.shape)}, strides={strides})"
                )
            cached = self._cache.put(key, vol)
            self._publish_in_flight(key, slot, cached, warning)
            return cached, warning
        except BaseException as exc:
            with self._lock:
                self._in_flight.pop(key, None)
                slot.error = exc
                slot.event.set()
            raise

    def _publish_in_flight(
        self,
        key: SeismicCacheKey,
        slot: _InFlightPreviewRead,
        result: Any,
        warning: str,
    ) -> None:
        """Publish the owner's read result so joined callers can proceed."""
        with self._lock:
            self._in_flight.pop(key, None)
            slot.result = result
            slot.warning = warning
            slot.event.set()

    def read_lod_volume(
        self,
        level: int = 0,
        *,
        cancellation_token=None,
    ) -> tuple[np.ndarray | None, str]:
        """LOD ladder: 0=preview (128³), 1=medium (~256), 2=finer (~384)."""
        level = max(0, min(2, int(level)))
        # Invert: higher LOD number = finer detail (goal text L0 preview / L2 detail).
        # Implement as max_dim growth.
        dims = (DEFAULT_PREVIEW_MAX_DIM, 256, 384)
        budgets = (
            DEFAULT_PREVIEW_BUDGET,
            256 * 256 * 256,
            384 * 384 * 256,
        )
        return self.read_preview(
            max_dim=dims[level],
            max_budget=budgets[level],
            lod=0,
            cancellation_token=cancellation_token,
        )


def _downsample_2d(data: np.ndarray, *, step: int) -> np.ndarray:
    step = max(1, int(step))
    if step == 1:
        return np.ascontiguousarray(data, dtype=np.float32)
    return np.ascontiguousarray(data[::step, ::step], dtype=np.float32)


# ---------------------------------------------------------------------------
# Shared registry (2D + 3D share one source per path identity)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, SeismicVolumeSource] = {}
_REGISTRY_LOCK = threading.Lock()


def get_shared_seismic_source(path: str | Path) -> SeismicVolumeSource:
    """Return a process-shared source for *path* (metadata-first, cached slices)."""
    p = Path(path)
    key = str(p.resolve()) if p.exists() else str(p)
    with _REGISTRY_LOCK:
        src = _REGISTRY.get(key)
        if src is not None and not src._closed:
            if p.exists() and src.source_id != source_id_for_path(p):
                # File replaced on disk under the same path: drop the stale
                # handle (its cached meta keeps the old identity/loader) so a
                # fresh open sees the new content.
                del _REGISTRY[key]
                try:
                    get_global_seismic_cache().invalidate_source(src.source_id)
                except Exception:
                    pass
                src.close()
            else:
                return src
        src = SeismicVolumeSource(path)
        _REGISTRY[key] = src
        return src


def close_shared_seismic_source(path: str | Path) -> None:
    key = str(Path(path).resolve()) if Path(path).exists() else str(path)
    with _REGISTRY_LOCK:
        src = _REGISTRY.pop(key, None)
    if src is not None:
        try:
            get_global_seismic_cache().invalidate_source(src.source_id)
        except Exception:
            pass
        src.close()


def clear_seismic_source_registry() -> None:
    with _REGISTRY_LOCK:
        items = list(_REGISTRY.values())
        _REGISTRY.clear()
    for src in items:
        try:
            src.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Generation helper for slider scrub / request supersession
# ---------------------------------------------------------------------------


@dataclass
class SeismicRequestTicket:
    """Latest-request-wins token for async slice delivery."""

    generation: int
    path: str
    kind: Orientation | str
    index: int
    lod: int = 0


class SeismicRequestGate:
    """Track generation so stale async results can be discarded on the host."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._current: SeismicRequestTicket | None = None

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin(
        self,
        *,
        path: str,
        kind: str,
        index: int,
        lod: int = 0,
    ) -> SeismicRequestTicket:
        with self._lock:
            self._generation += 1
            ticket = SeismicRequestTicket(
                generation=self._generation,
                path=path,
                kind=kind,
                index=int(index),
                lod=int(lod),
            )
            self._current = ticket
            return ticket

    def is_current(self, ticket: SeismicRequestTicket) -> bool:
        with self._lock:
            return (
                self._current is not None
                and ticket.generation == self._current.generation
            )

    def supersede(self) -> None:
        with self._lock:
            self._generation += 1
            self._current = None
