"""SeismicVolumeSource: metadata-first open, lazy slices, shared cache, generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.viz.seismic_volume_cache import (
    SeismicCacheKey,
    SeismicVolumeCache,
    reset_global_seismic_cache,
)
from paleo_workbench.viz.seismic_volume_source import (
    SeismicRequestGate,
    SeismicVolumeSource,
    clear_seismic_source_registry,
    get_shared_seismic_source,
    preview_strides,
    source_id_for_path,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_seismic_source_registry()
    reset_global_seismic_cache()
    yield
    clear_seismic_source_registry()
    reset_global_seismic_cache()


def _write_mini_segy(path: Path, *, n_il: int = 8, n_xl: int = 10, n_s: int = 16) -> Path:
    """Write a tiny structured SEG-Y via segyio (skip if segyio missing)."""
    segyio = pytest.importorskip("segyio")
    spec = segyio.spec()
    spec.sorting = 2  # inline sorting
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.ilines = list(range(1, n_il + 1))
    spec.xlines = list(range(1, n_xl + 1))
    with segyio.create(str(path), spec) as f:
        for ili, il in enumerate(spec.ilines):
            for xli, xl in enumerate(spec.xlines):
                # deterministic amplitude
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili + 0.001 * xli
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def test_preview_strides_respect_budget():
    fi, fx, ft = preview_strides(512, 512, 512, max_dim=128, max_budget=128**3)
    assert fi >= 4 and fx >= 4 and ft >= 4
    out = (math_ceil := __import__("math").ceil)
    voxels = out(512 / fi) * out(512 / fx) * out(512 / ft)
    assert voxels <= 128**3


def test_cache_byte_budget_evicts():
    cache = SeismicVolumeCache(max_bytes=8 * 1024)  # 8 KiB
    a = np.ones((32, 32), dtype=np.float32)  # 4 KiB
    b = np.ones((32, 32), dtype=np.float32) * 2
    c = np.ones((32, 32), dtype=np.float32) * 3
    cache.put(SeismicCacheKey("s", "inline", 0, 0), a)
    cache.put(SeismicCacheKey("s", "inline", 1, 0), b)
    # Third entry should evict oldest.
    cache.put(SeismicCacheKey("s", "inline", 2, 0), c)
    assert cache.get(SeismicCacheKey("s", "inline", 0, 0)) is None
    assert cache.get(SeismicCacheKey("s", "inline", 2, 0)) is not None
    assert cache.evictions >= 1


def test_metadata_first_and_lazy_slice(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "mini.sgy")
    src = SeismicVolumeSource(segy)
    meta = src.metadata()
    assert meta.n_inlines == 8
    assert meta.n_crosslines == 10
    assert meta.n_samples == 16
    assert meta.has_geometry
    assert not meta.is_pseudo
    assert meta.metadata_ms >= 0.0
    # No volume materialisation yet for metadata.
    assert src.physical_reads == 0

    sl = src.read_inline(0, lod=0)
    assert sl.shape == (10, 16)
    assert src.physical_reads == 1
    # Warm hit.
    sl2 = src.read_inline(0, lod=0)
    assert sl2 is not None
    assert src.physical_reads == 1  # no second physical read
    assert np.allclose(sl, sl2)

    xl = src.read_crossline(0, lod=0)
    assert xl.shape[1] == 16
    ts = src.read_timeslice(0, lod=0)
    assert ts.shape == (8, 10)
    src.close()


def test_preview_is_bounded_and_cached(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "cube.sgy", n_il=40, n_xl=40, n_s=40)
    src = SeismicVolumeSource(segy)
    vol, warning = src.read_preview(max_dim=16, max_budget=16**3)
    assert vol is not None
    assert all(d <= 16 for d in vol.shape)
    assert src.physical_reads == 1
    vol2, _ = src.read_preview(max_dim=16, max_budget=16**3)
    assert vol2 is not None
    assert src.physical_reads == 1  # cache hit
    assert np.allclose(vol, vol2)
    src.close()


def test_read_preview_in_flight_dedup_concurrent(tmp_path: Path):
    """Concurrent read_preview calls for the same key must issue ONE read (C43)."""
    from concurrent.futures import ThreadPoolExecutor

    segy = _write_mini_segy(tmp_path / "dedup.sgy", n_il=60, n_xl=60, n_s=60)
    src = SeismicVolumeSource(segy)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [
            pool.submit(
                src.read_preview, max_dim=16, max_budget=16**3
            )
            for _ in range(10)
        ]
        results = [f.result() for f in futures]
    volumes = [r[0] for r in results]
    assert all(v is not None for v in volumes)
    assert all(np.allclose(volumes[0], v) for v in volumes)
    # Exactly one physical read for the shared preview key.
    assert src.physical_reads == 1
    # Warm cache hit afterwards stays at one read.
    vol, _ = src.read_preview(max_dim=16, max_budget=16**3)
    assert vol is not None
    assert src.physical_reads == 1
    src.close()


def test_shared_source_registry(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "shared.sgy")
    a = get_shared_seismic_source(segy)
    b = get_shared_seismic_source(segy)
    assert a is b
    a.metadata()
    assert b.metadata().source_id == a.source_id


def test_request_gate_stale_suppression():
    gate = SeismicRequestGate()
    t1 = gate.begin(path="a.sgy", kind="inline", index=1)
    t2 = gate.begin(path="a.sgy", kind="inline", index=2)
    assert not gate.is_current(t1)
    assert gate.is_current(t2)
    gate.supersede()
    assert not gate.is_current(t2)


def test_source_id_changes_with_file_content(tmp_path: Path):
    p = tmp_path / "f.sgy"
    p.write_bytes(b"abc")
    id1 = source_id_for_path(p)
    p.write_bytes(b"abcd")
    id2 = source_id_for_path(p)
    assert id1 != id2


def test_load_seismic_volume_from_path_uses_source(tmp_path: Path):
    from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

    segy = _write_mini_segy(tmp_path / "load.sgy", n_il=20, n_xl=20, n_s=20)
    vol, warning = load_seismic_volume_from_path(str(segy))
    assert vol is not None
    assert vol.ndim == 3
    assert all(d <= 128 for d in vol.shape)
    # Second call should hit shared cache (no full re-read of full cube path).
    vol2, _ = load_seismic_volume_from_path(str(segy))
    assert vol2 is not None
    assert np.allclose(vol, vol2)


def test_missing_file():
    src = SeismicVolumeSource("/tmp/does-not-exist-seismic-xyz.sgy")
    with pytest.raises(FileNotFoundError):
        src.metadata()


def test_cache_readonly_view(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "ro.sgy")
    src = SeismicVolumeSource(segy)
    sl = src.read_inline(0)
    assert not sl.flags.writeable
    with pytest.raises(ValueError):
        sl[0, 0] = 99.0
    src.close()
