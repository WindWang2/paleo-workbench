"""Unit tests for Batch 3: Performance Optimization & Native Dispatch."""

import numpy as np
import pytest

from paleo_workbench.native_backend import native_backend


def test_native_backend_dispatch_dtw():
    c1 = np.array([10.0, 20.0, 30.0, 40.0, 50.0], dtype=np.float64)
    c2 = np.array([12.0, 18.0, 31.0, 42.0, 49.0], dtype=np.float64)

    cost, path_ref, path_target = native_backend.dispatch("dtw_match_curves", c1, c2)
    assert np.isfinite(cost)
    assert len(path_ref) > 0
    assert len(path_target) > 0
    assert path_ref[0] == 0
    assert path_ref[-1] == len(c1) - 1


def test_native_backend_disabled_acceleration():
    c1 = np.array([1.0, 2.0, 3.0])
    c2 = np.array([1.0, 2.0, 3.0])

    with native_backend.disabled_acceleration():
        cost, path_ref, path_target = native_backend.dispatch("dtw_match_curves", c1, c2)
        assert np.isclose(cost, 0.0)
        assert len(path_ref) == 3
