"""§12 — Stage-3 computational fusion production entry (goal qgis-geolayer-cartography-v7).

Covers ``workflow.integrated_compilation`` — the first production caller of
``workflow.factor_fusion`` (audit P1-9) — and the ``run_fusion`` stage action:

* deterministic defaults (equal weights, 低/中/高 equal-thirds classes,
  per-factor finite-range minmax) recorded in qc, never silently applied;
* ``run_integrated_fusion`` output equivalence with a direct ``fuse()`` run
  and model-provenance round-trip;
* honest degraded registration (no catalog / register=False) and real
  catalog registration through the single write path;
* error paths: zero factor entries, unresolvable task listing (honest, never
  a partial evidence set), weight and normalisation validation;
* action-level wiring (fallback canvas composite): descriptor-only scalar
  memberships + polygon-seeded integrated draft, no-catalog degradation,
  never overwriting an existing draft.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    store_live_factor_grid,
)
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.factor_fusion import FusionModel, fuse
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.integrated_compilation import (
    DEFAULT_FUSION_CLASS_NAMES,
    DEFAULT_FUSION_CLASS_THRESHOLDS,
    build_fusion_model,
    fusion_inputs_from_document,
    run_integrated_fusion,
)

# ---------------------------------------------------------------------------
# fixtures — aligned grids with declared units (shared geometry)
# ---------------------------------------------------------------------------

_GX = np.array([0.0, 1.0])
_GY = np.array([0.0, 1.0])
_SAND = np.array([[10.0, 60.0], [70.0, 20.0]], dtype=np.float32)
_WATER = np.array([[5.0, 45.0], [55.0, 8.0]], dtype=np.float32)


def _grid(values, *, factor_name, unit, refs=()) -> FactorGridResult:
    return FactorGridResult(
        grid_z=np.asarray(values, dtype=np.float32),
        grid_x=_GX,
        grid_y=_GY,
        factor_name=factor_name,
        algorithm_id="idw",
        crs="EPSG:32650",
        unit=unit,
        source_refs=list(refs),
    )


def _sand_grid(refs=()) -> FactorGridResult:
    return _grid(_SAND, factor_name="砂地比", unit="%", refs=refs)


def _water_grid(refs=()) -> FactorGridResult:
    return _grid(_WATER, factor_name="古水深", unit="m", refs=refs)


_EVIDENCE = {"砂地比": "factor:t1:v1", "古水深": "factor:t2:v2"}
_RESULTS = {"t1": _sand_grid(), "t2": _water_grid()}


def _document_with_factor_tasks(refs=("s@v1", "w@v1")) -> tuple[ProjectDocument, dict[str, str]]:
    """Project with two complete factor tasks whose grids live in the session cache."""
    document = ProjectDocument.new("融合测试")
    evidence: dict[str, str] = {}
    for key, grid in (("t1", _sand_grid(refs[:1])), ("t2", _water_grid(refs[1:]))):
        task = FactorMapTask(
            name=grid.factor_name, target_horizon="T2",
            factor_type=grid.factor_name, method="idw",
            status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real",
        )
        task.id = key  # deterministic ids so evidence values are stable in assertions
        document.factor_map_tasks.append(task)
        store_live_factor_grid(key, grid)
        evidence[grid.factor_name] = f"factor:{key}:v1"
    return document, evidence


@pytest.fixture(autouse=True)
def _clear_live_grids():
    yield
    for task_id in ("t1", "t2", "e2e-t1", "e2e-t2"):
        clear_live_factor_grid(task_id)


# ---------------------------------------------------------------------------
# build_fusion_model — deterministic defaults + validation
# ---------------------------------------------------------------------------


def test_build_fusion_model_defaults_are_deterministic():
    model = build_fusion_model(_EVIDENCE, _RESULTS)
    assert model.kind == "weighted_evidence"
    assert len(model.evidences) == 2
    assert all(ev.weight == 1.0 for ev in model.evidences)  # equal-weight default
    assert model.class_names == list(DEFAULT_FUSION_CLASS_NAMES)
    assert model.class_thresholds == pytest.approx(list(DEFAULT_FUSION_CLASS_THRESHOLDS))
    names = [ev.factor_name for ev in model.evidences]
    assert names == sorted(names) or set(names) == {"砂地比", "古水深"}
    # per-factor finite-range minmax: bounds are each grid's own [min, max]
    for ev in model.evidences:
        assert ev.normalization.kind == "minmax"
        assert ev.normalization.low == pytest.approx(float(ev.grid.grid_z.min()))
        assert ev.normalization.high == pytest.approx(float(ev.grid.grid_z.max()))
    # deterministic: same evidence content → same fingerprint
    assert build_fusion_model(_EVIDENCE, _RESULTS).fingerprint() == model.fingerprint()


def test_build_fusion_model_explicit_weights_and_classes_flow_through():
    model = build_fusion_model(
        _EVIDENCE, _RESULTS,
        weights={"t1": 3.0, "t2": 1.0},
        class_names=["低", "高"],
        class_thresholds=[0.5],
    )
    assert {ev.factor_name: ev.weight for ev in model.evidences} == {
        "砂地比": 3.0, "古水深": 1.0}
    assert model.class_names == ["低", "高"]
    assert model.class_thresholds == [0.5]


def test_build_fusion_model_rejects_zero_factor_entries():
    with pytest.raises(ValueError, match="factor"):
        build_fusion_model({"阶段1草稿": "draft:L1", "约束": "constraints:current"}, {})
    # a factor entry whose task has no loaded grid is never silently dropped
    with pytest.raises(ValueError, match="不在已加载网格中"):
        build_fusion_model({"缺失": "factor:tX:v1"}, _RESULTS)


def test_build_fusion_model_rejects_bad_weights():
    with pytest.raises(ValueError, match="正数"):
        build_fusion_model(_EVIDENCE, _RESULTS, weights={"t1": 0.0, "t2": 1.0})
    with pytest.raises(ValueError, match="未知任务"):
        build_fusion_model(_EVIDENCE, _RESULTS, weights={"t1": 1.0, "bogus": 1.0})
    with pytest.raises(ValueError, match="缺少任务"):
        build_fusion_model(_EVIDENCE, _RESULTS, weights={"t1": 1.0})


def test_build_fusion_model_rejects_degenerate_default_normalizations():
    constant = _grid(np.full((2, 2), 42.0), factor_name="常数", unit="m")
    with pytest.raises(ValueError, match="常数网格"):
        build_fusion_model({"c": "factor:tc:v1"}, {"tc": constant})
    empty = _grid(np.full((2, 2), np.nan), factor_name="空", unit="m")
    with pytest.raises(ValueError, match="没有有限值"):
        build_fusion_model({"e": "factor:te:v1"}, {"te": empty})


def test_build_fusion_model_class_scheme_must_be_consistent():
    with pytest.raises(ValueError, match="同时提供"):
        build_fusion_model(_EVIDENCE, _RESULTS, class_names=["低", "高"])
    with pytest.raises(ValueError, match="len\\(class_names\\)-1"):
        build_fusion_model(
            _EVIDENCE, _RESULTS, class_names=["低", "中", "高"],
            class_thresholds=[0.5],
        )


# ---------------------------------------------------------------------------
# fusion_inputs_from_document — honest resolution
# ---------------------------------------------------------------------------


def test_fusion_inputs_from_document_resolves_live_grids():
    document, evidence = _document_with_factor_tasks()
    resolved = fusion_inputs_from_document(document, evidence)
    assert set(resolved) == {"t1", "t2"}
    assert resolved["t1"].factor_name == "砂地比"
    assert resolved["t1"].unit == "%"


def test_fusion_inputs_from_document_lists_unresolvable_tasks():
    document, evidence = _document_with_factor_tasks()
    evidence["神秘因子"] = "factor:t_missing:v9"
    with pytest.raises(ValueError, match="t_missing"):
        fusion_inputs_from_document(document, evidence)
    # task exists but has no grid anywhere (no live cache, no artifact,
    # no legacy inline parameters) → honest listing, never partial evidence
    document2, _ = _document_with_factor_tasks()
    task = FactorMapTask(
        name="空任务", target_horizon="T2", factor_type="空任务",
        method="idw", status=FACTOR_TASK_STATUS_COMPLETE,
    )
    document2.factor_map_tasks.append(task)
    clear_live_factor_grid("t1")
    clear_live_factor_grid("t2")
    with pytest.raises(ValueError, match="空任务"):
        fusion_inputs_from_document(
            document2, {"a": "factor:t1:v1", "空任务": f"factor:{task.id}:v1"})


# ---------------------------------------------------------------------------
# run_integrated_fusion — summary, fuse() equivalence, registration
# ---------------------------------------------------------------------------


def test_run_integrated_fusion_matches_fuse_and_records_defaults():
    document, evidence = _document_with_factor_tasks()
    summary = run_integrated_fusion(document, evidence, None, register=False)

    # Equivalent direct run: same model construction + fuse().
    factor_results = fusion_inputs_from_document(document, evidence)
    model = build_fusion_model(evidence, factor_results)
    expected = fuse(model)

    assert summary["n_factors"] == 2
    assert summary["class_names"] == list(DEFAULT_FUSION_CLASS_NAMES)
    assert summary["qc"]["class_counts"] == expected.qc["class_counts"]
    assert summary["qc"]["classified_cells"] == expected.qc["classified_cells"]
    assert (
        summary["likelihood_descriptor"]["metadata"]["statistics"]
        == expected.likelihood.statistics.to_dict()
    )
    assert summary["variance_available"] is False
    assert summary["variance_descriptor"] is None
    # sensitivity rides along (leave-one-factor-out honesty record)
    assert summary["sensitivity"]["supported"] is True
    assert set(summary["sensitivity"]["factors"]) == {"砂地比", "古水深"}

    # nothing silently defaulted: policies recorded in qc
    defaults = summary["qc"]["defaults"]
    assert defaults["weights"] == {"policy": "equal", "value": 1.0}
    assert defaults["classes"]["policy"] == "default_equal_thirds"
    assert defaults["classes"]["class_names"] == list(DEFAULT_FUSION_CLASS_NAMES)
    assert defaults["normalization"]["policy"] == "per_factor_finite_range"

    # model provenance round-trips (grids supplied at runtime, never serialised)
    payload = model.to_dict()
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    restored = FusionModel.from_dict(
        payload, grids={ev.factor_name: ev.grid for ev in model.evidences})
    assert fuse(restored).likelihood.statistics.to_dict() == (
        expected.likelihood.statistics.to_dict()
    )


def test_run_integrated_fusion_descriptors_follow_scalar_grid_conventions():
    document, evidence = _document_with_factor_tasks()
    summary = run_integrated_fusion(document, evidence, None, register=False)
    for key, quantity in (
        ("likelihood_descriptor", "fusion_likelihood"),
        ("confidence_descriptor", "fusion_confidence"),
    ):
        descriptor = summary[key]
        assert descriptor["geometry_kind"] == "raster"
        assert descriptor["role"] is LayerRole.ANALYSIS_AID
        assert descriptor["metadata"]["layer_type"] == "scalar_grid"
        assert descriptor["metadata"]["quantity"] == quantity
        assert descriptor["layer_id"].startswith(f"{quantity}:")
        fusion_meta = descriptor["metadata"]["fusion"]
        assert fusion_meta["fusion_kind"] == "weighted_evidence"
        assert fusion_meta["class_names"] == list(DEFAULT_FUSION_CLASS_NAMES)
        assert fusion_meta["evidence_count"] == 2
    # grid arrays never cross into descriptors
    assert "grid_z" not in json.dumps(
        summary["likelihood_descriptor"]["payload"]["descriptor"], ensure_ascii=False)
    # classification polygons exist for seeding the integrated draft
    assert summary["classification_features"]
    assert summary["qc"]["classification"]["feature_count"] == len(
        summary["classification_features"])
    for geometry, properties in summary["classification_features"]:
        assert geometry.get("type") == "Polygon"
        assert str(properties.get("facies") or "") in DEFAULT_FUSION_CLASS_NAMES


def test_run_integrated_fusion_catalogless_is_honest():
    document, evidence = _document_with_factor_tasks()
    explicit = run_integrated_fusion(document, evidence, None, register=False)
    assert explicit["registered"] is False
    assert explicit["catalog_version_id"] == ""
    assert explicit["qc"]["registration"]["reason"] == "register=False"

    no_service = run_integrated_fusion(document, evidence, None, register=True)
    assert no_service["registered"] is False
    assert "catalog" in str(no_service["qc"]["registration"]["reason"])


def test_run_integrated_fusion_registers_through_catalog(tmp_path):
    from paleo_workbench.catalog import DataCatalogService

    project_file = tmp_path / "proj" / "fusion.paleo.json"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_file)
    try:
        (tmp_path / "sand.npz").write_bytes(b"sand")
        (tmp_path / "wd.npz").write_bytes(b"wd")
        sand = svc.import_raw(tmp_path / "sand.npz", name="sand.npz", type="factor_map")
        wd = svc.import_raw(tmp_path / "wd.npz", name="wd.npz", type="factor_map")
        document, evidence = _document_with_factor_tasks(refs=(sand.id, wd.id))
        summary = run_integrated_fusion(document, evidence, svc)
        assert summary["registered"] is True
        version_id = summary["catalog_version_id"]
        assert version_id
        assert summary["qc"]["catalog_version_id"] == version_id
        version = svc.get_version(version_id)
        assert version.run_id, "fused output must carry a DataRun"
        run = next(r for r in svc.document.runs if r.id == version.run_id)
        assert run.operation == "factor_fusion"
        assert sorted(run.input_version_ids) == sorted([sand.id, wd.id])
        assert run.parameters["model"]["kind"] == "weighted_evidence"
        # sensitivity + defaults ride the run provenance (nothing silent)
        assert run.parameters["qc"]["defaults"]["weights"]["policy"] == "equal"
        assert "sensitivity_leave_one_factor_out" in run.parameters
        # confidence surface ships as the sibling version
        assert summary["confidence_descriptor"]["metadata"]["artifact_version_id"]
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# stage action (fallback canvas composite; dispatcher test pattern from
# tests/test_mapping_stage_e2e.py)
# ---------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication([])


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def _fusion_project():
    """Two complete factor tasks (live grids) + factor evidence in the set."""
    document = ProjectDocument.new("融合 E2E")
    evidence: dict[str, str] = {}
    values = {
        "砂地比": np.array([[0.0, 100.0], [100.0, 0.0]], dtype=np.float32),
        "古水深": np.array([[100.0, 0.0], [0.0, 100.0]], dtype=np.float32),
    }
    units = {"砂地比": "%", "古水深": "m"}
    for index, (name, grid_values) in enumerate(values.items(), start=1):
        task = FactorMapTask(
            name=name, target_horizon="T2", factor_type=name, method="idw",
            status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real",
        )
        task.id = f"e2e-t{index}"
        document.factor_map_tasks.append(task)
        store_live_factor_grid(task.id, _grid(grid_values, factor_name=name, unit=units[name]))
        evidence[name] = f"factor:{task.id}:v1"
    return document, evidence


def test_stage_action_run_fusion_degraded_mode_seeds_draft(qtbot, monkeypatch):
    document, evidence = _fusion_project()
    doc = _composite(qtbot, monkeypatch, document)
    state = doc.stage_controller.state
    state.compilation_input_set.update(evidence)
    monkeypatch.setattr(
        "paleo_workbench.catalog.runtime.get_catalog_service", lambda: None)
    messages: list[str] = []
    doc.status_message.connect(messages.append)

    doc.stage_actions.run_fusion()

    assert any("融合完成" in message for message in messages)
    assert any("未注册目录" in message for message in messages)  # honest degradation
    # descriptor-only scalar registrations (idempotent layer ids, ANALYSIS_AID)
    likelihood_ids = [
        layer_id for layer_id in state.memberships
        if str(layer_id).startswith("fusion_likelihood:")
    ]
    assert likelihood_ids, "likelihood descriptor must be registered as a membership"
    assert all(state.membership(lid).role is LayerRole.ANALYSIS_AID
               for lid in likelihood_ids)
    assert any(str(layer_id).startswith("fusion_confidence:")
               for layer_id in state.memberships)
    # polygon simplification exists → seeded editable integrated draft
    draft_ids = state.layers_with_role(LayerRole.INTEGRATED_FACIES)
    assert draft_ids
    draft = doc.edit_controller.layer(draft_ids[0])
    assert len(list(draft.features())) >= 1
    assert state.maturity_of(f"integrated:{draft_ids[0]}") == "draft"

    # second run: idempotent registrations, draft preserved (never overwritten)
    features_before = len(list(draft.features()))
    doc.stage_actions.run_fusion()
    assert len([
        lid for lid in state.memberships
        if str(lid).startswith("fusion_likelihood:")
    ]) == 1  # no duplicate registrations
    assert any("已有综合解释草稿" in message for message in messages)
    assert len(list(draft.features())) == features_before


def test_stage_action_run_fusion_requires_factor_evidence(qtbot, monkeypatch):
    document, _ = _fusion_project()
    doc = _composite(qtbot, monkeypatch, document)
    state = doc.stage_controller.state
    messages: list[str] = []
    doc.status_message.connect(messages.append)

    doc.stage_actions.run_fusion()
    assert any("证据集为空" in message for message in messages)

    state.compilation_input_set["阶段1草稿"] = "draft:L9"
    doc.stage_actions.run_fusion()
    assert any("没有单因素证据" in message for message in messages)


def test_stage_action_run_fusion_reports_unresolvable_evidence(qtbot, monkeypatch):
    document, _ = _fusion_project()
    doc = _composite(qtbot, monkeypatch, document)
    doc.stage_controller.state.compilation_input_set["幽灵"] = "factor:ghost:v1"
    monkeypatch.setattr(
        "paleo_workbench.catalog.runtime.get_catalog_service", lambda: None)
    messages: list[str] = []
    doc.status_message.connect(messages.append)

    doc.stage_actions.run_fusion()
    assert any("融合失败" in message and "ghost" in message for message in messages)
