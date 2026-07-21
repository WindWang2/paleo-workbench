"""TDD Tests for 3D Well-Seismic Tie Calibration (Issue #5 / Refactor)."""
import numpy as np
import pytest

from paleo_workbench.viz.geomodel.well_seismic import WellSeismicTieCalibration


def test_compute_synthetic_seismogram():
    # Synthetic logs: 100 samples
    sonic = np.full(100, 300.0, dtype=np.float32)  # dt = 300 us/m
    density = np.full(100, 2.3, dtype=np.float32)  # rho = 2.3 g/cm3
    
    # Introduce a reflector at index 50
    sonic[50:] = 200.0
    density[50:] = 2.7
    
    synthetic = WellSeismicTieCalibration.compute_synthetic(
        sonic, density, wavelet_freq=30.0, dt_s=0.002
    )
    
    # Seismogram must have reflectivity pulse convolved with Ricker wavelet
    assert len(synthetic) > 0
    # Peak response should be around the reflector depth mapping
    assert np.max(np.abs(synthetic)) > 0.0


def test_align_twt_depth_shift():
    # Simple linear T-D model: TWT = depth * 2 (velocity = 1000 m/s)
    depths = np.linspace(0.0, 1000.0, 11)
    twt_times = depths * 2.0
    
    # Shifts depth coordinates by +10 meters (simulating shift calibration)
    calibrated_depths = WellSeismicTieCalibration.align_twt_depth(
        depths, twt_times, depth_shift=10.0
    )
    
    assert len(calibrated_depths) == len(depths)
    assert calibrated_depths[0] == 10.0
    assert calibrated_depths[-1] == 1010.0
