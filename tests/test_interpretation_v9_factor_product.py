"""V9 — FactorProduct 投影 + AlgorithmSpec 注册表测试。"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.interpretation.algorithm_registry import (
    ALGORITHMS,
    canonical_algorithm_id,
    display_label,
    get_algorithm,
    ui_interpolation_methods,
)
from paleo_workbench.workflow.interpretation.factor_product import (
    factor_product_for_task,
    factor_products,
)
from paleo_workbench.workflow.interpretation.summaries import (
    factor_summary,
    factor_summary_for_task,
)


# ------------------------------------------------------------ 注册表


def test_registry_declares_capability_matrix():
    kriging = get_algorithm("kriging")
    assert kriging.produces_uncertainty is True
    assert kriging.family == "interpolation"
    constrained = get_algorithm("constrained_idw")
    assert set(constrained.supported_constraints) >= {
        "boundary_mask", "barrier", "direction"}
    fusion = get_algorithm("factor_fusion")
    assert fusion.family == "fusion"
    assert fusion.produces_uncertainty is True
    assert fusion.supported_constraints == {}  # 约束在插值阶段消费


def test_canonical_resolution_covers_all_legacy_vocabularies():
    # UI 标签、engine id、历史写法全部归一。
    assert canonical_algorithm_id("克里金") == "kriging"
    assert canonical_algorithm_id("IDW") == "idw"
    assert canonical_algorithm_id("idw") == "idw"
    assert canonical_algorithm_id("约束IDW") == "constrained_idw"
    assert canonical_algorithm_id("样条") == "spline"
    assert canonical_algorithm_id("方向趋势") == "directional"
    assert canonical_algorithm_id("linear") == "linear"
    with pytest.raises(ValueError):
        canonical_algorithm_id("不存在的方法")


def test_ui_methods_match_legacy_tokens_exactly():
    import paleo_workbench.tokens as tokens

    assert ui_interpolation_methods() == tokens.INTERPOLATION_METHODS == [
        "克里金", "IDW", "约束IDW", "样条", "方向趋势"]
    assert display_label("kriging") == "克里金"


def test_registry_is_single_authority_for_cancel_and_crs():
    for spec in ALGORITHMS.values():
        assert isinstance(spec.supports_cancel, bool)
        assert isinstance(spec.requires_crs, bool)


# ------------------------------------------------------------ 投影


def _task_document() -> tuple[ProjectDocument, FactorMapTask]:
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂岩厚度", target_horizon="T1", factor_type="砂岩厚度",
        method="IDW", status="complete", source_kind="real",
        quality_metrics={"r_squared": 0.8, "n_points": 10, "backend": "idw"},
    )
    task.grid_metadata = {"unit": "m", "crs": "EPSG:32650", "shape": [50, 50]}
    task.grid_artifact_version_id = ""
    task.parameters = {"constraint_pins": [{"group": "g", "content_hash": "h1"}]}
    doc.factor_map_tasks.append(task)
    return doc, task


def test_factor_product_projects_identity_and_artifacts():
    doc, task = _task_document()
    product = factor_product_for_task(doc, task.id, workspace_state=MappingWorkspaceState())
    assert product is not None
    assert product.factor_id == task.id
    assert product.algorithm_id == "idw"
    assert product.unit == "m" and product.unit_declared
    assert product.crs == "EPSG:32650" and product.crs_declared
    assert product.factor_family == "sand_thickness"
    grid_ref = product.artifact("grid")
    assert grid_ref.present  # metadata 存在即有载荷（live/artifact）
    poly = product.artifact("polygons")
    assert not poly.present and poly.absent_reason
    assert product.artifact("uncertainty").absent_reason
    assert product.constraint_pins[0]["group"] == "g"


def test_factor_product_missing_task_returns_none():
    doc, _ = _task_document()
    assert factor_product_for_task(doc, "nope") is None


def test_factor_products_batch_with_freshness():
    doc, task = _task_document()
    products = factor_products(doc, workspace_state=MappingWorkspaceState())
    assert len(products) == 1
    # 无 grid version → dependencies 给 UNKNOWN（诚实），投影携带。
    assert products[0].freshness in ("unknown", "")


def test_factor_summary_displays_honesty_states():
    doc, task = _task_document()
    summary = factor_summary_for_task(
        doc, task.id, workspace_state=MappingWorkspaceState())
    payload = summary.to_display_dict()
    labels = {row["label"]: row for row in payload["rows"]}
    assert labels["方法"]["value"] == "IDW 反距离加权"
    assert labels["CRS"]["state"] == "ok"
    assert labels["结果版本"]["state"] == "unknown"  # 未登记版本不伪称 ok
    assert labels["单位"]["value"] == "m"


def test_factor_summary_none_is_honest():
    summary = factor_summary(None)
    assert summary.rows[0].state == "missing"
