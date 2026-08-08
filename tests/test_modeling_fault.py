"""Unit tests for the Fault Cutting and Dislocation engine."""

from __future__ import annotations
import numpy as np
import pytest

from geoviz import FaultCuttingEngine


def test_basic_rigid_dislocation_point_normal():
    """Test standard block dislocation using (point, normal) representation."""
    # Fault plane passes through origin (0, 0, 0) with normal along +X
    fault_plane = ([0, 0, 0], [1, 0, 0])
    throw_vector = np.array([0, 0, 10.0])

    # Points on both sides of the fault
    surface_points = np.array([
        [2.0, 0.0, 0.0],   # Positive side (X > 0)
        [-2.0, 0.0, 0.0],  # Negative side (X < 0)
        [0.0, 0.0, 0.0],   # Boundary point (X = 0)
    ])

    displaced = FaultCuttingEngine.apply_dislocation(
        surface_points, fault_plane, throw_vector, split_throw=False
    )

    # Positive side should be displaced by throw_vector
    assert np.allclose(displaced[0], [2.0, 0.0, 10.0])
    # Negative side should remain stationary
    assert np.allclose(displaced[1], [-2.0, 0.0, 0.0])
    # Boundary point (>= 0) should be displaced by throw_vector
    assert np.allclose(displaced[2], [0.0, 0.0, 10.0])


def test_basic_rigid_dislocation_equation():
    """Test standard block dislocation using (a, b, c, d) plane representation."""
    # Plane: X - 1 = 0 => a=1, b=0, c=0, d=-1
    # Positive side: X > 1, Negative side: X < 1
    fault_plane = (1.0, 0.0, 0.0, -1.0)
    throw_vector = np.array([0.0, 5.0, 0.0])

    surface_points = np.array([
        [2.0, 0.0, 0.0],  # Positive side (2.0 > 1.0)
        [0.0, 0.0, 0.0],  # Negative side (0.0 < 1.0)
    ])

    displaced = FaultCuttingEngine.apply_dislocation(
        surface_points, fault_plane, throw_vector, split_throw=False
    )

    assert np.allclose(displaced[0], [2.0, 5.0, 0.0])
    assert np.allclose(displaced[1], [0.0, 0.0, 0.0])


def test_split_throw_dislocation():
    """Test dislocation when throw is split between hanging wall and footwall."""
    fault_plane = ([0, 0, 0], [0, 1, 0])  # Normal along Y
    throw_vector = np.array([0.0, 0.0, 8.0])

    surface_points = np.array([
        [0.0, 1.0, 0.0],   # Positive side (Y > 0)
        [0.0, -1.0, 0.0],  # Negative side (Y < 0)
    ])

    displaced = FaultCuttingEngine.apply_dislocation(
        surface_points, fault_plane, throw_vector, split_throw=True
    )

    # Positive side gets +0.5 * throw
    assert np.allclose(displaced[0], [0.0, 1.0, 4.0])
    # Negative side gets -0.5 * throw
    assert np.allclose(displaced[1], [0.0, -1.0, -4.0])


def test_linear_decay_dislocation():
    """Test dislocation with linear decay over a given decay distance."""
    fault_plane = ([0, 0, 0], [1, 0, 0])
    throw_vector = np.array([0.0, 0.0, 10.0])
    decay_distance = 4.0

    surface_points = np.array([
        [0.0, 0.0, 0.0],  # At the fault plane (dist = 0.0)
        [2.0, 0.0, 0.0],  # Inside decay range, positive side (dist = 2.0)
        [4.0, 0.0, 0.0],  # At/beyond decay range, positive side (dist = 4.0)
        [6.0, 0.0, 0.0],  # Well beyond decay range (dist = 6.0)
    ])

    # Case 1: split_throw=False
    displaced = FaultCuttingEngine.apply_dislocation(
        surface_points, fault_plane, throw_vector,
        split_throw=False, decay_distance=decay_distance, decay_style="linear"
    )

    # At fault plane (factor = 1.0)
    assert np.allclose(displaced[0], [0.0, 0.0, 10.0])
    # At dist=2.0 (factor = 1 - 2/4 = 0.5)
    assert np.allclose(displaced[1], [2.0, 0.0, 5.0])
    # At dist=4.0 (factor = 0.0)
    assert np.allclose(displaced[2], [4.0, 0.0, 0.0])
    # At dist=6.0 (factor = 0.0)
    assert np.allclose(displaced[3], [6.0, 0.0, 0.0])

    # Case 2: split_throw=True
    displaced_split = FaultCuttingEngine.apply_dislocation(
        surface_points, fault_plane, throw_vector,
        split_throw=True, decay_distance=decay_distance, decay_style="linear"
    )
    # At fault plane (factor = 1.0, pos_side gets +5.0)
    assert np.allclose(displaced_split[0], [0.0, 0.0, 5.0])
    # At dist=2.0 (factor = 0.5, pos_side gets +2.5)
    assert np.allclose(displaced_split[1], [2.0, 0.0, 2.5])


def test_decay_styles():
    """Test different decay styles (exponential, gaussian) for correctness."""
    fault_plane = ([0, 0, 0], [0, 0, 1])
    throw_vector = np.array([0.0, 0.0, 10.0])
    decay_distance = 5.0
    pt = np.array([[0.0, 0.0, 2.5]])  # dist = 2.5 => normalized_dist = 0.5

    # Exponential decay factor at x = 0.5:
    # (exp(3 * (1 - 0.5)) - 1) / (exp(3) - 1) = (exp(1.5) - 1) / (exp(3) - 1)
    expected_exp_factor = (np.exp(1.5) - 1.0) / (np.exp(3.0) - 1.0)
    res_exp = FaultCuttingEngine.apply_dislocation(
        pt, fault_plane, throw_vector, decay_distance=decay_distance, decay_style="exponential"
    )
    assert np.allclose(res_exp[0, 2], 2.5 + expected_exp_factor * 10.0)

    # Gaussian decay factor at x = 0.5:
    # (exp(-4 * 0.5^2) - exp(-4)) / (1 - exp(-4)) = (exp(-1) - exp(-4)) / (1 - exp(-4))
    expected_gauss_factor = (np.exp(-1.0) - np.exp(-4.0)) / (1.0 - np.exp(-4.0))
    res_gauss = FaultCuttingEngine.apply_dislocation(
        pt, fault_plane, throw_vector, decay_distance=decay_distance, decay_style="gaussian"
    )
    assert np.allclose(res_gauss[0, 2], 2.5 + expected_gauss_factor * 10.0)


def test_surface_shapes():
    """Test handling of different array shapes for surface_points."""
    fault_plane = ([0, 0, 0], [1, 0, 0])
    throw_vector = np.array([0.0, 0.0, 2.0])

    # 1. 3D grid shape (H, W, 3)
    grid_pts = np.zeros((3, 4, 3))
    grid_pts[:, :, 0] = np.array([
        [-1.0, 2.0, -3.0, 4.0],
        [-1.0, 2.0, -3.0, 4.0],
        [-1.0, 2.0, -3.0, 4.0]
    ])
    displaced_grid = FaultCuttingEngine.apply_dislocation(grid_pts, fault_plane, throw_vector)
    assert displaced_grid.shape == (3, 4, 3)
    # Check that points with positive X (2.0 and 4.0) got displaced by throw_vector [0, 0, 2]
    assert np.allclose(displaced_grid[0, 0], [-1.0, 0.0, 0.0])
    assert np.allclose(displaced_grid[0, 1], [2.0, 0.0, 2.0])

    # 2. Single point shape (3,)
    single_pt = np.array([1.0, 0.0, 0.0])
    displaced_single = FaultCuttingEngine.apply_dislocation(single_pt, fault_plane, throw_vector)
    assert displaced_single.shape == (3,)
    assert np.allclose(displaced_single, [1.0, 0.0, 2.0])


def test_variable_throw_vectors():
    """Test dislocation using a per-point variable throw vector array."""
    fault_plane = ([0, 0, 0], [1, 0, 0])
    surface_points = np.array([
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [-1.0, 0.0, 0.0]
    ])
    # Throw vectors vary for each point
    throw_vectors = np.array([
        [0.0, 0.0, 5.0],
        [0.0, 0.0, 10.0],
        [0.0, 0.0, 15.0]
    ])

    displaced = FaultCuttingEngine.apply_dislocation(surface_points, fault_plane, throw_vectors)

    # Pt 0 (positive side): gets throw_vectors[0]
    assert np.allclose(displaced[0], [1.0, 0.0, 5.0])
    # Pt 1 (positive side): gets throw_vectors[1]
    assert np.allclose(displaced[1], [2.0, 0.0, 10.0])
    # Pt 2 (negative side): remains stationary (throw_vectors[2] is ignored)
    assert np.allclose(displaced[2], [-1.0, 0.0, 0.0])


def test_validation_errors():
    """Test error handling with invalid inputs."""
    surface_points = np.array([[1.0, 2.0, 3.0]])
    throw_vector = np.array([0.0, 0.0, 1.0])

    # 1. Invalid fault_plane type
    with pytest.raises(TypeError, match="fault_plane must be a tuple"):
        FaultCuttingEngine.apply_dislocation(surface_points, "not a tuple", throw_vector)

    # 2. Invalid tuple length
    with pytest.raises(ValueError, match="fault_plane tuple must have length"):
        FaultCuttingEngine.apply_dislocation(surface_points, (1, 2, 3), throw_vector)

    # 3. Invalid (point, normal) shapes
    with pytest.raises(ValueError, match="both must have shape"):
        FaultCuttingEngine.apply_dislocation(surface_points, ([1, 2], [1, 2, 3]), throw_vector)

    # 4. Zero plane normal (a, b, c = 0)
    with pytest.raises(ValueError, match="normal vector cannot be zero"):
        FaultCuttingEngine.apply_dislocation(surface_points, (0.0, 0.0, 0.0, 5.0), throw_vector)

    # 5. Invalid surface_points shape
    with pytest.raises(ValueError, match="last dimension of size 3"):
        FaultCuttingEngine.apply_dislocation(np.array([[1.0, 2.0]]), ([0,0,0],[1,0,0]), throw_vector)

    # 6. Invalid throw_vector shape
    with pytest.raises(ValueError, match="throw_vector shape"):
        FaultCuttingEngine.apply_dislocation(surface_points, ([0,0,0],[1,0,0]), np.array([1, 2]))

    # 7. Invalid decay_distance value
    with pytest.raises(ValueError, match="decay_distance must be positive"):
        FaultCuttingEngine.apply_dislocation(
            surface_points, ([0,0,0],[1,0,0]), throw_vector, decay_distance=-1.0
        )

    # 8. Invalid decay_style
    with pytest.raises(ValueError, match="Unknown decay_style"):
        FaultCuttingEngine.apply_dislocation(
            surface_points, ([0,0,0],[1,0,0]), throw_vector, decay_distance=2.0, decay_style="cosine"
        )
