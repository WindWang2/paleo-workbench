"""Unit tests for C++ marching_cubes_3d isosurface mesh extraction & volume integration (Ticket 01)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.seismic_3d_api import HAS_CPP_SEISMIC, marching_cubes_3d

# marching_cubes_3d needs either the seismic_3d_core C++ extension or
# scikit-image as a Python fallback. CI builds neither, so skip the whole
# module when both are unavailable.
try:
    import skimage  # noqa: F401
    _HAS_SKIMAGE = True
except ImportError:
    _HAS_SKIMAGE = False

pytestmark = pytest.mark.skipif(
    not HAS_CPP_SEISMIC and not _HAS_SKIMAGE,
    reason="marching_cubes_3d needs seismic_3d_core C++ extension or scikit-image",
)


def test_marching_cubes_3d_sphere_mesh_extraction():
    grid_size = 20
    x, y, z = np.ogrid[:grid_size, :grid_size, :grid_size]
    radius = 6.0
    vol = np.sqrt((x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2) - radius

    verts, faces = marching_cubes_3d(vol.astype(np.float32), isovalue=0.0)

    assert len(verts) > 0
    assert len(faces) > 0
    assert verts.ndim == 2 and verts.shape[1] == 3
    assert faces.ndim == 2 and faces.shape[1] == 3


def _signed_mesh_volume(verts, faces) -> float:
    """Divergence-theorem volume, sign INTACT: V = (1/6) * sum(v0 . (v1 x v2)).

    The sign encodes triangle winding, so it must not be discarded — taking
    ``abs()`` here is what hid the native/fallback orientation divergence in
    #876 from this very test.
    """
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    return float(np.sum(np.einsum("ij, ij->i", v0, np.cross(v1, v2))) / 6.0)


def test_marching_cubes_3d_closed_geobody_volume():
    # Sphere volume calculation from mesh: V = (4/3) * pi * r^3
    r = 5.0
    grid_size = 30
    x, y, z = np.ogrid[:grid_size, :grid_size, :grid_size]
    vol = np.sqrt((x - 15) ** 2 + (y - 15) ** 2 + (z - 15) ** 2) - r

    verts, faces = marching_cubes_3d(vol.astype(np.float32), isovalue=0.0)
    mesh_volume = _signed_mesh_volume(verts, faces)

    expected_volume = (4.0 / 3.0) * np.pi * (r**3)
    # Both backends define the "inside" set as value >= isovalue and orient
    # normals AWAY from it. Here the sphere INTERIOR is negative, so the
    # >=isovalue region is the exterior and the winding is inward — a negative
    # signed volume. Asserting the sign (rather than abs()) is what pins
    # orientation parity between the C++ kernel and the Python fallback (#876).
    assert mesh_volume == pytest.approx(-expected_volume, rel=0.15)
    assert abs(mesh_volume) == pytest.approx(expected_volume, rel=0.15)


def test_marching_cubes_3d_orientation_follows_the_isovalue_convention():
    """Flipping the field flips the winding, in whichever backend is active.

    With the sphere INTERIOR above the isovalue the object is the sphere, so
    normals point outward and the signed volume is positive. This is the
    assertion that fails if the fallback and the C++ kernel disagree on
    orientation (#876).
    """
    r = 5.0
    grid_size = 30
    x, y, z = np.ogrid[:grid_size, :grid_size, :grid_size]
    dist = np.sqrt((x - 15) ** 2 + (y - 15) ** 2 + (z - 15) ** 2)
    expected_volume = (4.0 / 3.0) * np.pi * (r**3)

    inward = _signed_mesh_volume(
        *marching_cubes_3d((dist - r).astype(np.float32), isovalue=0.0)
    )
    outward = _signed_mesh_volume(
        *marching_cubes_3d((r - dist).astype(np.float32), isovalue=0.0)
    )

    assert inward < 0.0 < outward, (
        "winding must follow the >=isovalue convention in both polarities "
        f"(got {inward} and {outward})"
    )
    assert abs(inward) == pytest.approx(expected_volume, rel=0.15)
    assert outward == pytest.approx(expected_volume, rel=0.15)
