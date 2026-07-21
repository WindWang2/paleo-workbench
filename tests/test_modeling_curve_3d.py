"""TDD Tests for Well旁显 3D Curve Mesh Generation (Issue #5 / Refactor)."""
import numpy as np
import pytest

from paleo_workbench.viz.geomodel.well_seismic import WellCurve3DGenerator


def test_generate_well_curve_3d_mesh():
    # Straight vertical well path from depth 0 to 100
    well_path = np.zeros((50, 3), dtype=np.float32)
    well_path[:, 2] = -np.linspace(0.0, 100.0, 50)  # downward z
    
    # Well log curve values (e.g. GR values between 40 and 120 API)
    curve_values = 80.0 + 30.0 * np.sin(well_path[:, 2] * 0.1)
    
    # Scale offset curves: offset curve on the x-axis
    offset_pts = WellCurve3DGenerator.generate_curve_mesh(
        well_path, curve_values, scale=0.5
    )
    
    assert offset_pts.shape == (50, 3)
    # The curve points should be offset from the well path on the x/y plane
    for i in range(len(well_path)):
        dist = np.linalg.norm(offset_pts[i, :2] - well_path[i, :2])
        # Expected offset amplitude is proportional to curve values
        assert dist == pytest.approx(curve_values[i] * 0.5, rel=1e-4)
