"""V6 §12 — constrained-IDW adapter facts survive into the grid result.

The adapter computes search/decluster radii, barrier buffer mode, duplicate
drops and honest CV provenance; FactorGridResult.from_constrained_idw_dict
used to discard them (audit P1-10) — the surface's shaping parameters
vanished from provenance.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _adapter_dict() -> dict:
    n = 16
    return {
        "grid_x": np.linspace(0.0, 1000.0, n),
        "grid_y": np.linspace(0.0, 1000.0, n),
        "grid_z": np.full((n, n), 0.5),
        "backend": "constrained_idw",
        "method": "constrained_idw",
        "grid_n": n,
        "n_points": 8,
        "n_break_lines": 1,
        "n_direction_lines": 0,
        "duplicate_wells_dropped": 2,
        "min": 0.5,
        "max": 0.5,
        "mean": 0.5,
        "r_squared": 0.62,
        "r_squared_method": "spatial_4_fold",
        "anchored_fidelity": 0.999,
        "anchored_fidelity_n_skipped": 0,
        "boundary": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0], [0.0, 0.0]],
        "contours": None,
        "contour_levels": [0.25, 0.5, 0.75],
        "barrier_buffer_mode": "auto_map_units",
        "search_radius": 1470.0,
        "decluster_radius": 220.5,
    }


class TestDiagnosticsPreserved:
    def test_result_carries_adapter_facts(self):
        result = FactorGridResult.from_constrained_idw_dict(
            _adapter_dict(), factor_name="孔隙度", crs="EPSG:32650", unit="%"
        )
        params = result.algorithm_parameters
        assert params["search_radius"] == pytest.approx(1470.0)
        assert params["decluster_radius"] == pytest.approx(220.5)
        assert params["barrier_buffer_mode"] == "auto_map_units"
        assert params["duplicate_wells_dropped"] == 2
        assert params["r_squared_method"] == "spatial_4_fold"
        assert params["anchored_fidelity"] == pytest.approx(0.999)

    def test_absent_facts_omit_cleanly(self):
        data = _adapter_dict()
        for key in ("search_radius", "decluster_radius", "barrier_buffer_mode",
                    "duplicate_wells_dropped", "anchored_fidelity", "r_squared_method"):
            data.pop(key, None)
        result = FactorGridResult.from_constrained_idw_dict(
            data, factor_name="孔隙度"
        )
        params = result.algorithm_parameters
        for key in ("search_radius", "decluster_radius", "barrier_buffer_mode"):
            assert key not in params
