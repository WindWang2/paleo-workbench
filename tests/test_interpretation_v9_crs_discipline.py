"""V9 — 融合 CRS 纪律（P0-5）。

混合已声明/未声明 CRS 的融合必须拒绝；全未声明允许但 qc 诚实记录
``crs_undeclared``（不伪称正常完成）。
"""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.workflow.factor_fusion import (
    FactorEvidence,
    FusionModel,
    Normalization,
    fuse,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _grid(values, crs="EPSG:32650") -> FactorGridResult:
    values = np.asarray(values, dtype=float)
    h, w = values.shape
    return FactorGridResult(
        grid_z=values.astype(np.float32),
        grid_x=np.linspace(0.0, float(w), w),
        grid_y=np.linspace(0.0, float(h), h),
        factor_name=f"g-{crs}",
        algorithm_id="idw",
        crs=crs,
        unit="1",
        source_refs=["a@v1"],
    )


def _model(grids) -> FusionModel:
    return FusionModel(
        name="m", kind="weighted_evidence",
        evidences=[
            FactorEvidence(f"f{i}", g, weight=1.0,
                           normalization=Normalization("minmax", 0.0, 100.0))
            for i, g in enumerate(grids)
        ],
        class_thresholds=[0.5], class_names=["低", "高"],
    )


def test_mixed_declared_undeclared_crs_refused():
    with pytest.raises(ValueError, match="declares no CRS"):
        fuse(_model([_grid([[1.0, 2.0], [3.0, 4.0]], crs="EPSG:32650"),
                     _grid([[1.0, 2.0], [3.0, 4.0]], crs=None)]))


def test_mixed_none_first_refused():
    with pytest.raises(ValueError, match="declares no CRS"):
        fuse(_model([_grid([[1.0, 2.0], [3.0, 4.0]], crs=None),
                     _grid([[1.0, 2.0], [3.0, 4.0]], crs="EPSG:4326")]))


def test_declared_mismatch_still_refused():
    with pytest.raises(ValueError, match="different CRSs"):
        fuse(_model([_grid([[1.0]], crs="EPSG:32650"),
                     _grid([[1.0]], crs="EPSG:4326")]))


def test_all_undeclared_fuses_with_honest_qc_flag():
    result = fuse(_model([_grid([[1.0, 60.0]], crs=None),
                          _grid([[50.0, 10.0]], crs=None)]))
    assert result.qc.get("crs_undeclared") is True
    assert result.likelihood.crs is None  # 未声明诚实传播，绝不猜


def test_all_declared_same_crs_no_flag():
    result = fuse(_model([_grid([[1.0, 60.0]]),
                          _grid([[50.0, 10.0]])]))
    assert "crs_undeclared" not in result.qc
    assert result.likelihood.crs == "EPSG:32650"
