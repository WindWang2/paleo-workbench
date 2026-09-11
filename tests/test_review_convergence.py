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
