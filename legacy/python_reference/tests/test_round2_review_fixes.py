"""Regression tests for Round 2 review findings (#1241 and P2 defects)."""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# DEF-D1-04: Planar geometry UTM scale-dependent epsilon
# ---------------------------------------------------------------------------


def test_geometry_planar_utm_on_edge_inclusion() -> None:
    """Test point on UTM edge (x ~ 500,000, length ~ 10,000) is recognized."""
    from paleo_workbench.mapping.geometry_planar import point_in_ring_scalar_inclusive

    # UTM ring (perimeter ~ 40,000 meters)
    ring = [
        (500000.0, 4000000.0),
        (510000.0, 4000000.0),
        (510000.0, 4010000.0),
        (500000.0, 4010000.0),
        (500000.0, 4000000.0),
    ]
    # Point exactly halfway along bottom segment
    test_x = 505000.0
    test_y = 4000000.0
    assert point_in_ring_scalar_inclusive(test_x, test_y, ring)

    # Point on bottom segment with slight float perturbation within 1e-9 * segment_len
    # segment_len = 10,000, tolerance is ~ 1e-5
    perturbed_y = 4000000.0 + 1e-6
    assert point_in_ring_scalar_inclusive(test_x, perturbed_y, ring)


# ---------------------------------------------------------------------------
# DEF-D1-03: Vector operations empty coordinates validation
# ---------------------------------------------------------------------------


def test_vector_operations_empty_coordinates_validation() -> None:
    """Test merge_selected_polygons rejects empty coordinates."""
    from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
    from paleo_workbench.mapping.vector_operations import merge_selected_polygons

    layer = VectorLayer(
        id="facies",
        name="Facies",
        features=[
            VectorFeature("f1", {"type": "Polygon", "coordinates": []}),
            VectorFeature("f2", {"type": "Polygon", "coordinates": []}),
        ],
    )
    session = layer.start_editing()

    with pytest.raises(ValueError, match="cannot form a valid merged polygon|only polygon features can be merged"):
        merge_selected_polygons(session, ["f1", "f2"])


# ---------------------------------------------------------------------------
# DEF-D2-04: Kriging fallback warning outside active_qc guard
# ---------------------------------------------------------------------------


def test_map_product_kriging_fallback_honesty_without_active_qc() -> None:
    """Kriging fallback warning must be included even when active_qc is None."""
    from paleo_workbench.project.models import FactorMapTask, ProjectDocument
    from paleo_workbench.workflow.map_product import (
        MapProductAssembly,
        MapProductRecord,
        publish_map_product,
    )

    project = ProjectDocument.new("TestProduct")
    task = FactorMapTask(
        id="task-1",
        name="SandRatio",
        target_horizon="T2",
        factor_type="sand_ratio",
        method="kriging_fallback",
        grid_metadata={"algorithm_parameters": {"method": "kriging_fallback"}},
    )
    project.factor_map_tasks.append(task)

    assembly = MapProductAssembly(
        product_name="Test",
        factor_task_ids=[task.id],
    )
    # 产品级 QA：factor 无登记版本是 ERROR（R3-F1 后阻断 publish）——
    # 本测试聚焦 fallback 警告可见性，给任务补登记版本号（须在指纹前）。
    task.grid_artifact_version_id = "ver_kf1"
    record = MapProductRecord(
        id="prod-1",
        product_name="Test",
        factor_task_ids=[task.id],
        scientific_fingerprint=assembly.scientific_fingerprint(project),
    )
    # Project has NO active_quality_report_id (active_qc is None)
    project.active_quality_report_id = None
    # V9（goal §31）：publish 阶梯——评审 → 冻结 → 发布。
    from paleo_workbench.workflow.map_product import (
        freeze_map_product,
        review_map_product,
    )
    record.run_id = "run_r2"
    record.output_version_id = "ver_r2"
    record.lifecycle = "reviewed"  # 合成记录：QA error 会被评审拒（直置阶梯）
    freeze_map_product(record)

    report = publish_map_product(record, project, accept_warnings=True)
    assert any("computed by the numpy kriging fallback" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# DEF-D2-05: Interpolation fingerprint memo key detects point mutation
# ---------------------------------------------------------------------------


def test_interpolation_fingerprint_memo_key_detects_point_mutation() -> None:
    """In-place point mutation with identical point count changes memo key."""
    from paleo_workbench.project.models import FactorMapTask
    from paleo_workbench.workflow.interpolation_fingerprint import _fingerprint_memo_key

    task = FactorMapTask(
        id="task-1",
        name="SandRatio",
        target_horizon="T2",
        factor_type="sand_ratio",
        method="IDW",
        parameters={"sample_points": [{"x": 100.0, "y": 200.0, "value": 0.5}]},
    )

    kwargs = {
        "method": "IDW",
        "grid_n": 50,
        "power": 2.0,
        "fault_polylines": None,
        "generator_version": "v1",
    }

    key1 = _fingerprint_memo_key(task, **kwargs)

    # Mutate point coordinate in-place (same point count = 1)
    task.parameters["sample_points"][0]["value"] = 0.8
    key2 = _fingerprint_memo_key(task, **kwargs)

    assert key1 != key2, "Memo key failed to detect in-place value change"


# ---------------------------------------------------------------------------
# #1241: QTimer.singleShot context safety on destroyed QObject
# ---------------------------------------------------------------------------


def test_qtimer_singleshot_canceled_when_context_destroyed(qapp) -> None:
    """Verify Qt singleShot with context does NOT fire after context is deleted."""
    from PySide6.QtCore import QObject, QTimer, QCoreApplication, QEvent

    fired = []
    obj = QObject()

    QTimer.singleShot(0, obj, lambda: fired.append(1))
    # Delete obj before event loop runs
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert fired == [], "singleShot fired after context QObject was deleted!"
