"""SourceBackedVolumeAccess + progressive joint volume path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.viz.seismic_volume_cache import reset_global_seismic_cache
from paleo_workbench.viz.seismic_volume_source import (
    SeismicVolumeSource,
    clear_seismic_source_registry,
)
from paleo_workbench.viz.source_backed_volume_access import SourceBackedVolumeAccess
from paleo_workbench.viz.real_geological_scene import (
    build_real_scene_snapshot,
    classify_project_mode,
)
from paleo_workbench.project.models import ProjectDocument


@pytest.fixture(autouse=True)
def _clean():
    clear_seismic_source_registry()
    reset_global_seismic_cache()
    yield
    clear_seismic_source_registry()
    reset_global_seismic_cache()


def _mini_segy(path: Path, n_il=8, n_xl=10, n_s=16) -> Path:
    segyio = pytest.importorskip("segyio")
    spec = segyio.spec()
    spec.sorting = 2
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.ilines = list(range(1, n_il + 1))
    spec.xlines = list(range(1, n_xl + 1))
    with segyio.create(str(path), spec) as f:
        for ili, il in enumerate(spec.ilines):
            for xli, xl in enumerate(spec.xlines):
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def test_source_backed_volume_access_protocol(tmp_path: Path):
    segy = _mini_segy(tmp_path / "a.sgy")
    src = SeismicVolumeSource(segy)
    access = SourceBackedVolumeAccess(src)
    assert access.shape == (8, 10, 16)
    assert access.data is None  # no dense until LOD attach
    sl = access.slice_inline(0)
    assert sl.shape == (10, 16)
    xl = access.slice_crossline(0)
    assert xl.ndim == 2
    ts = access.slice_time(0)
    assert ts.shape == (8, 10)
    tr = access.sample_trace(0, 0)
    assert tr.shape == (16,)
    src.close()


def test_display_lod_does_not_require_full_native_materialisation(tmp_path: Path):
    segy = _mini_segy(tmp_path / "b.sgy", n_il=20, n_xl=20, n_s=20)
    src = SeismicVolumeSource(segy)
    access = SourceBackedVolumeAccess(src)
    assert access.data is None
    vol, _ = src.read_lod_volume(level=0)
    assert vol is not None
    access.set_display_data(vol, lod_level=0, adopt_shape=True)
    assert access.data is not None
    assert access.lod_level == 0
    assert access.shape == tuple(vol.shape)
    # Scrub uses display when shapes match.
    assert access.slice_inline(0).shape[0] == vol.shape[1]
    src.close()


def test_fence_extract_source_backed_without_dense(tmp_path: Path):
    from geoviz_well_seismic_3d.fence import FenceSection, extract_fence_strip

    segy = _mini_segy(tmp_path / "c.sgy")
    src = SeismicVolumeSource(segy)
    access = SourceBackedVolumeAccess(src)
    fence = FenceSection(
        name="test",
        vertices_xy=np.array([[0.0, 0.0], [100.0, 0.0]], dtype=np.float64),
    )
    # Without registration: use identity mapping helpers
    ext = extract_fence_strip(
        access,
        fence=fence,
        xy_to_il_xl=lambda x, y: (1.0, 1.0),
        iline_start=1.0,
        iline_step=1.0,
        xline_start=1.0,
        xline_step=1.0,
        n_along=8,
    )
    assert ext.amplitude.shape[0] == 8
    assert ext.amplitude.shape[1] == 16
    src.close()


def test_real_scene_snapshot_empty_project():
    project = ProjectDocument.new("Empty")
    snap = build_real_scene_snapshot(project, generation=1)
    assert snap.mode in {"empty", "real"}  # may find demo data on disk
    assert snap.generation == 1
    # Never invent synthetic faults
    assert "synthetic" not in (snap.asset_summary or {})


def test_classify_project_mode_none():
    assert classify_project_mode(None) == "empty"
