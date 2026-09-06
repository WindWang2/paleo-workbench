"""V6 §14/§16/§17 — factor unit validation, fusion honesty, publish gate."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_units import validate_factor_unit_against_values


def _grid(crs="EPSG:32650", unit="%", values=None, factor="孔隙度"):
    n = 8
    zz = values if values is not None else np.full((n, n), 45.0)
    return FactorGridResult(
        factor_name=factor,
        algorithm_id="idw",
        grid_x=np.linspace(0, 1000, n),
        grid_y=np.linspace(0, 1000, n),
        grid_z=zz,
        crs=crs,
        unit=unit,
    )


class TestUnitMagnitudeValidation:
    def test_percent_declared_but_fraction_values_flagged(self):
        values = np.full((4, 4), 0.35)  # 0..1 fraction labeled "%"
        diagnostics = validate_factor_unit_against_values("孔隙度", "%", values)
        assert any("fraction" in d for d in diagnostics)

    def test_percent_declared_percent_values_clean(self):
        values = np.full((4, 4), 35.0)
        assert validate_factor_unit_against_values("孔隙度", "%", values) == []

    def test_unknown_unit_clean(self):
        values = np.full((4, 4), 0.35)
        assert validate_factor_unit_against_values("孔隙度", None, values) == []

    def test_unitless_fraction_clean(self):
        values = np.full((4, 4), 0.35)
        assert validate_factor_unit_against_values("砂岩含量", "1", values) == []


class TestFusionHonesty:
    def _model(self, crs_b="EPSG:32650", unit_b="%"):
        from paleo_workbench.workflow.factor_fusion import (
            FactorEvidence,
            FusionModel,
            Normalization,
        )

        g1 = _grid(values=np.full((8, 8), 40.0))
        g2 = _grid(crs=crs_b, unit=unit_b, values=np.full((8, 8), 20.0), factor="泥质含量")
        return FusionModel(
            name="融合",
            kind="weighted_evidence",
            evidences=[
                FactorEvidence(
                    factor_name=g1.factor_name,
                    grid=g1,
                    weight=0.6,
                    normalization=Normalization(kind="minmax", low=0.0, high=100.0),
                ),
                FactorEvidence(
                    factor_name=g2.factor_name,
                    grid=g2,
                    weight=0.4,
                    normalization=Normalization(kind="minmax", low=0.0, high=100.0),
                ),
            ],
            class_names=["低", "高"],
            class_thresholds=[0.5],
        )

    def test_crs_mismatch_refused(self):
        from paleo_workbench.workflow.factor_fusion import fuse

        with pytest.raises(ValueError, match="CRS"):
            fuse(self._model(crs_b="EPSG:4326"))

    def test_unit_mismatch_bounds_diagnostic(self):
        from paleo_workbench.workflow.factor_fusion import fuse

        # evidence B is a fraction (v/v) but bounds assume 0..100 percent
        result = fuse(self._model(unit_b="v/v"))
        qc = result.qc
        warnings = qc.get("unit_warnings") or qc.get("warnings") or []
        assert any("v/v" in str(w) or "unit" in str(w).lower() for w in warnings)

    def test_consistent_units_no_warning(self):
        from paleo_workbench.workflow.factor_fusion import fuse

        result = fuse(self._model())
        warnings = result.qc.get("unit_warnings") or []
        assert warnings == []
