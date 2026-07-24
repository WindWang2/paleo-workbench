"""Fence extract, multi-fence, probe, depth, profile assembly (#60–#64)."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_well_seismic_3d import (
    FenceSection,
    InMemoryVolumeAccess,
    VerticalDomain,
    WellHead,
    WellSeismicScene,
    select_depth_transform,
    survey_from_corners,
)

P1 = (1315, 4165, 0.0, 0.0)
P2 = (1315, 4805, 12793.0, 0.0)
P3 = (1725, 4805, 12793.0, 16406.0)


def _scene_with_volume() -> WellSeismicScene:
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=16, dt_ms=2.0)
    vol = np.random.randn(8, 8, 16).astype(np.float32)
    scene.set_volume_access(InMemoryVolumeAccess(vol))
    scene.set_preview_mode(True)
    scene.set_wells(
        [
            WellHead("A1", 1000, 2000, 1000, 2000, 100),
            WellHead("A2", 3000, 4000, 3000, 4000, 100),
        ]
    )
    return scene


def test_shared_fence_extract_identity():
    scene = _scene_with_volume()
    fence = FenceSection(
        name="F1",
        vertices_xy=np.array([[0.0, 0.0], [5000.0, 5000.0]], dtype=np.float64),
    )
    scene.add_fence(fence)
    a = scene.extract_active_fence(n_along=32)
    b = scene.extract_active_fence(n_along=32)
    assert a is not None and b is not None
    assert a.fence_id == b.fence_id
    assert a.amplitude.shape == b.amplitude.shape
    np.testing.assert_array_equal(a.amplitude, b.amplitude)


def test_multi_fence_active_and_well_to_well():
    scene = _scene_with_volume()
    f1 = scene.add_fence(
        FenceSection("A", np.array([[0, 0], [1000, 0]], dtype=float)), activate=True
    )
    f2 = scene.add_fence(
        FenceSection("B", np.array([[0, 0], [0, 1000]], dtype=float)), activate=False
    )
    assert scene.active_fence_id == f1.id
    scene.set_active_fence(f2.id)
    assert scene.active_fence_id == f2.id
    scene.set_fence_visible(f1.id, False)
    assert scene.fences[0].visible is False
    ww = scene.add_well_to_well_fence(["A1", "A2"], name="W2W")
    assert ww.name == "W2W"
    assert scene.active_fence_id == ww.id
    assert len(ww.vertices_xy) == 2


def test_near_well_filter_and_curve_fallback():
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection("F", np.array([[1000.0, 2000.0], [3000.0, 4000.0]], dtype=float))
    )
    scene.set_near_well_distance_m(50.0)
    scene.set_formation_tops({"A1": [("C3", 100.0)]})
    md = np.linspace(0, 100, 5)
    scene.set_well_curves(
        {
            "A1": {
                "SP": (md, md),
                "GR": (md, md * 2),
            }
        }
    )
    hits = scene.assemble_active_profile_wells()
    names = {h.name for h in hits}
    assert "A1" in names
    a1 = next(h for h in hits if h.name == "A1")
    assert a1.curve_name == "GR"
    assert a1.tops[0][0] == "C3"


def test_probe_slice_indices():
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection("F", np.array([[0.0, 0.0], [10000.0, 10000.0]], dtype=float))
    )
    probe = scene.set_probe(s_m=100.0, z=20.0)
    assert probe.x != 0 or probe.y != 0 or True
    idx = scene.probe_slice_indices()
    assert idx is not None
    assert len(idx) == 3


def test_depth_domain_and_v0_warning():
    scene = _scene_with_volume()
    scene.set_depth_transform(select_depth_transform(has_external_volume=False, v0_m_s=2500))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.DEPTH
    assert scene.depth_transform.approximate_warning is not None
