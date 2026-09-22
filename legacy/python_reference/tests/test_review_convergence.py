"""Regression pins for the 2026-09-12 review-convergence cluster."""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.pipeline import GeologicalMappingPipeline
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_vocabulary import STAGE_CONTEXT_ACTIONS
from paleo_workbench.qgis_runtime import loader
from paleo_workbench.workflow.factor_fusion import Normalization
from paleo_workbench.workflow.factor_interpolation import resolve_engine_method
from paleo_workbench.workflow.interpolation_evaluation import bilinear_sample_grid


def test_loader_survives_missing_add_dll_directory(monkeypatch):
    monkeypatch.setattr(loader, "_PREPARED", False)
    monkeypatch.delattr(loader.os, "add_dll_directory", raising=False)
    report = loader.prepare_bridge_load(force=True)
    assert report.prepared is True


def test_derived_sand_ratio_is_percent():
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        [{"well_id": "w1", "name": "W1", "x": 1.0, "y": 2.0, "H_s": 4.0, "H_t": 8.0}],
        "砂地比",
    )
    assert dataset.points[0].value == pytest.approx(50.0)


def test_unknown_interpolation_method_raises():
    with pytest.raises(ValueError, match="unknown interpolation method"):
        resolve_engine_method("not-a-real-method")
    assert resolve_engine_method("spline") == "样条"


def test_bilinear_off_grid_is_none():
    gx = np.array([0.0, 1.0, 2.0])
    gy = np.array([0.0, 1.0])
    gz = np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]])
    assert bilinear_sample_grid(gz, gx, gy, 3.0, 0.0) is None
    assert bilinear_sample_grid(gz, gx, gy, 2.0, 0.0) == pytest.approx(20.0)


def test_fusion_normalization_does_not_promote_inf():
    membership = Normalization(kind="minmax", low=0.0, high=1.0).apply(
        np.array([np.inf, np.nan, 0.5])
    )
    assert not np.isfinite(membership[0])
    assert not np.isfinite(membership[1])
    assert membership[2] == pytest.approx(0.5)


def test_phase3_vocabulary_has_freeze_and_fusion():
    ids = {action_id for action_id, _label in STAGE_CONTEXT_ACTIONS["integrated_compilation"]}
    assert "freeze_input_set" in ids
    assert "run_fusion" in ids


def test_fusion_pin_blank_current_loads_catalog_artifact(tmp_path):
    from paleo_workbench.catalog.grid_artifact import write_grid_artifact
    from paleo_workbench.project.factor_grid_artifacts import store_live_factor_grid
    from paleo_workbench.project.models import FactorMapTask, ProjectDocument
    from paleo_workbench.workflow.factor_grid_result import FactorGridResult
    from paleo_workbench.workflow.integrated_compilation import (
        fusion_inputs_from_document,
    )

    doc = ProjectDocument.new("pin")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status="complete", source_kind="real")
    task.grid_artifact_version_id = ""
    doc.factor_map_tasks.append(task)
    live = FactorGridResult(
        grid_z=np.array([[99.0]], dtype=np.float32),
        grid_x=np.array([0.0]), grid_y=np.array([0.0]),
        factor_name="砂厚", algorithm_id="idw", crs="EPSG:32650", unit="m",
        source_refs=["live"])
    pinned = FactorGridResult(
        grid_z=np.array([[7.0]], dtype=np.float32),
        grid_x=np.array([0.0]), grid_y=np.array([0.0]),
        factor_name="砂厚", algorithm_id="idw", crs="EPSG:32650", unit="m",
        source_refs=["pin"])
    store_live_factor_grid(task.id, live)
    artifact = write_grid_artifact(pinned, tmp_path, "pin")

    class _PinCatalog:
        def get_version(self, version_id):
            return type("V", (), {"id": version_id})()

        def resolve_path(self, version):
            return artifact

    resolved = fusion_inputs_from_document(
        doc, {"砂厚": f"factor:{task.id}:ver_old"}, catalog=_PinCatalog())
    assert float(resolved[task.id].grid_z[0, 0]) == pytest.approx(7.0)


def test_raw_snapshot_editable_false(qtbot, tmp_path):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

    project = ProjectDocument.new("Conv", region="T")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    layer = doc.edit_controller.create_layer("RAW", "polygon")
    doc.stage_controller.state.set_membership(
        LayerMembershipRecord(layer_id=str(layer.id), role=LayerRole.INITIAL_FACIES_SOURCE)
    )
    allowed, _reason = doc.edit_controller.can_edit_layer(layer.id)
    assert allowed is False
    snapshots = doc.edit_controller.snapshot_layers()
    raw = next((s for s in snapshots if s.id == layer.id), None)
    assert raw is not None
    assert (raw.metadata or {}).get("editable") == "false"
