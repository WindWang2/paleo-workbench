"""V9 — ConstraintProduct 投影 + 双枚举收敛 + CRS 纪律 + UI 提交动作。"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace.layer_roles import ConstraintKind
from paleo_workbench.ui.workstation.stage_actions import STAGE_CONTEXT_ACTIONS
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    ProjectDocument,
)
from paleo_workbench.workflow.interpretation.constraint_product import (
    ConstraintProduct,
    assert_constraints_crs_compatible,
    constraint_product_for_group,
    constraint_products_for_document,
    to_engine_kind,
)


# ------------------------------------------------------------ 枚举收敛


def test_geo_to_engine_kind_unique_mapping():
    assert to_engine_kind(ConstraintKind.FAULT).value == "barrier"
    assert to_engine_kind(ConstraintKind.SOURCE_DIRECTION).value == "direction"
    assert to_engine_kind(ConstraintKind.PALEO_SHORELINE).value == "boundary_mask"
    assert to_engine_kind(ConstraintKind.MASK).value == "boundary_mask"
    assert to_engine_kind("fault").value == "barrier"
    assert to_engine_kind("not-a-kind") is None  # 未知不猜


def test_every_geo_kind_maps_to_engine_or_none():
    # 全枚举收敛检查：映射必须覆盖或显式 None，绝不 ValueError。
    for kind in ConstraintKind:
        assert to_engine_kind(kind) is not None, kind


# ------------------------------------------------------------ CRS 纪律


def test_crs_declared_mismatch_raises():
    with pytest.raises(ValueError, match="differs from factor CRS"):
        assert_constraints_crs_compatible("EPSG:32650", "EPSG:4326")


def test_crs_undeclared_gives_honest_notes():
    note = assert_constraints_crs_compatible("EPSG:32650", "")
    assert "undeclared" in note and "EPSG:32650" in note
    note = assert_constraints_crs_compatible(None, "EPSG:4326")
    assert "assumed" in note
    note = assert_constraints_crs_compatible("", "")
    assert "unverified" in note


def test_crs_same_returns_empty():
    assert assert_constraints_crs_compatible("EPSG:32650", "EPSG:32650") == ""


# ------------------------------------------------------------ 投影


def _group_document() -> tuple[ProjectDocument, ConstraintLayers]:
    doc = ProjectDocument.new("t")
    group = ConstraintLayers(
        id="cg_1", name="T1 约束", target_horizon="T1", crs="EPSG:32650")
    group.lines = [
        ConstraintLine(
            id="l1", name="断层F1", role="break",
            coordinates=[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
            properties={"constraint_kind": "fault",
                        "strength": 0.8, "confidence": "high"}),
        ConstraintLine(
            id="l2", name="古岸线", role="boundary",
            coordinates=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
                         [0.0, 0.0]],
            properties={"constraint_kind": "paleo_shoreline"}),
    ]
    doc.constraint_layers.append(group)
    return doc, group


def test_constraint_product_projects_lines_and_kinds():
    doc, group = _group_document()
    product = constraint_product_for_group(doc, group)
    assert product.constraint_id == "cg_1"
    assert set(product.kinds) == {"fault", "paleo_shoreline"}
    assert set(product.engine_kinds) == {"barrier", "boundary_mask"}
    assert product.crs_declared and product.crs == "EPSG:32650"
    assert product.n_active == 2
    fault = product.lines[0]
    assert fault.strength == 0.8 and fault.strength_declared
    assert fault.confidence == "high"
    shoreline = product.lines[1]
    assert shoreline.strength == 1.0 and not shoreline.strength_declared
    assert shoreline.confidence == "unknown"  # 未声明不猜


def test_constraint_product_uncommitted_is_draft_with_hash():
    doc, group = _group_document()
    product = constraint_product_for_group(doc, group)
    assert product.maturity == "draft"
    assert product.committed_version_id == ""
    assert product.content_hash  # 内容哈希存在（身份锚点）
    assert product.staleness == "uncommitted"


def test_constraint_products_for_document_lists_all():
    doc, _ = _group_document()
    products = constraint_products_for_document(doc)
    assert len(products) == 1
    assert isinstance(products[0], ConstraintProduct)


def test_strength_confidence_rejects_invalid_values():
    doc = ProjectDocument.new("t")
    group = ConstraintLayers(id="cg_2", name="x")
    group.lines = [ConstraintLine(
        id="l", name="bad", role="break",
        coordinates=[[0.0, 0.0], [1.0, 1.0]],
        properties={"strength": "not-a-number", "confidence": "superb"})]
    doc.constraint_layers.append(group)
    product = constraint_product_for_group(doc, group)
    line = product.lines[0]
    assert line.strength == 1.0 and not line.strength_declared
    assert line.confidence == "unknown"


# ------------------------------------------------------------ UI 动作


def test_commit_constraints_action_declared_for_phase2():
    actions = dict(STAGE_CONTEXT_ACTIONS["constraint_factor"])
    assert actions.get("commit_constraints") == "提交约束版本"
