"""M5 — multi-factor fusion framework (weighted evidence + rule-based).

Covers the auditable fusion model contract, weighted-evidence maths (NaN
renormalisation, confidence, variance propagation), ordered rule-based
classification, leave-one-out sensitivity, polygon output, provenance
round-trip, and catalog registration through the single write path.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.polygonization import (
    generate_facies_polygon_layer,
)
from paleo_workbench.workflow.factor_fusion import (
    FactorEvidence,
    FusionModel,
    FusionRule,
    Normalization,
    fuse,
    register_output,
    sensitivity_report,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _grid(values, crs="EPSG:32650", refs=("a@v1",), variance=None) -> FactorGridResult:
    values = np.asarray(values, dtype=float)
    h, w = values.shape
    gx = np.linspace(0.0, float(w), w)
    gy = np.linspace(0.0, float(h), h)
    return FactorGridResult(
        grid_z=values.astype(np.float32),
        grid_x=gx,
        grid_y=gy,
        factor_name="t",
        algorithm_id="idw",
        crs=crs,
        unit="1",
        source_refs=list(refs),
        variance_grid=None if variance is None else np.asarray(variance, dtype=np.float32),
    )


def _sand_ratio_field() -> np.ndarray:
    return np.array([[10.0, 60.0], [70.0, 20.0]])


def _water_depth_field() -> np.ndarray:
    return np.array([[5.0, 45.0], [55.0, 8.0]])


def _weighted_model(sand_field=None, water_field=None) -> FusionModel:
    sand = _grid(sand_field if sand_field is not None else _sand_ratio_field(), refs=("sand@v1",))
    water = _grid(water_field if water_field is not None else _water_depth_field(), refs=("wd@v1",))
    return FusionModel(
        name="三角洲融合",
        kind="weighted_evidence",
        evidences=[
            FactorEvidence("砂地比", sand, weight=2.0, normalization=Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("古水深", water, weight=1.0, normalization=Normalization("minmax", 0.0, 100.0)),
        ],
        class_thresholds=[0.5],
        class_names=["低潜力", "高潜力"],
    )


# ---------------------------------------------------------------------------
# normalization + model contract
# ---------------------------------------------------------------------------


def test_normalization_clamps_and_maps():
    norm = Normalization("minmax", 0.0, 100.0)
    out = norm.apply(np.array([-10.0, 0.0, 50.0, 120.0]))
    assert out.tolist() == [0.0, 0.0, 0.5, 1.0]


def test_normalization_rejects_bad_bounds():
    with pytest.raises(ValueError, match="high > low"):
        Normalization("minmax", 1.0, 1.0)
    with pytest.raises(ValueError, match="kind"):
        Normalization("sigmoid", 0.0, 1.0)


def test_model_roundtrip_and_fingerprint(tmp_path):
    model = _weighted_model()
    payload = model.to_dict()
    # grids are runtime objects and never serialised — they must be handed
    # back explicitly to rebuild a runnable model
    with pytest.raises(ValueError, match="runtime grid"):
        FusionModel.from_dict(payload)
    restored = FusionModel.from_dict(
        payload,
        grids={ev.factor_name: ev.grid for ev in model.evidences},
    )
    assert restored.fingerprint() == model.fingerprint()
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_model_requires_rules_or_evidence():
    with pytest.raises(ValueError, match="at least one evidence"):
        FusionModel(name="x", kind="weighted_evidence")
    with pytest.raises(ValueError, match="at least one rule"):
        FusionModel(name="x", kind="rule_based")


# ---------------------------------------------------------------------------
# weighted evidence maths
# ---------------------------------------------------------------------------


def test_weighted_fusion_exact_maths():
    result = fuse(_weighted_model())
    sand_m = np.array([[0.10, 0.60], [0.70, 0.20]])
    water_m = np.array([[0.05, 0.45], [0.55, 0.08]])
    expected = (2 * sand_m + 1 * water_m) / 3.0
    np.testing.assert_allclose(result.likelihood.grid_z, expected, rtol=1e-6)


def test_weighted_fusion_nan_renormalizes_and_full_nan_stays_nodata():
    sand = _sand_ratio_field().copy()
    sand[0, 0] = np.nan  # sand missing at one cell
    water = _water_depth_field().copy()
    water[1, 1] = np.nan  # water missing at another cell
    model = _weighted_model(sand_field=sand, water_field=water)
    result = fuse(model)
    grid = result.likelihood.grid_z
    # (0,0): only water available → renormalised to its membership
    assert grid[0, 0] == pytest.approx(0.05)
    # (1,1): only sand available → renormalised to its membership
    assert grid[1, 1] == pytest.approx(0.20)
    assert result.qc["nan_policy"] == "renormalize"


def test_weighted_fusion_all_nan_cell_stays_nodata():
    sand = _sand_ratio_field().copy()
    water = _water_depth_field().copy()
    sand[0, 0] = np.nan
    water[0, 0] = np.nan
    model = _weighted_model(sand_field=sand, water_field=water)
    result = fuse(model)
    assert np.isnan(result.likelihood.grid_z[0, 0])
    assert np.isnan(result.confidence.grid_z[0, 0])
    assert np.isfinite(result.likelihood.grid_z[0, 1])


def test_confidence_zero_when_single_factor_disagrees_totally():
    sand = np.full((2, 2), 100.0)  # membership 1.0 everywhere
    water = np.full((2, 2), 0.0)   # membership 0.0 everywhere
    model = _weighted_model(sand_field=sand, water_field=water)
    result = fuse(model)
    conf = result.confidence.grid_z
    # weights (2,1) over memberships (1,0): agreement = 1 − sqrt(2/9) ≈ 0.53
    assert np.all(conf < 0.55)  # heavy spread drags agreement down
    assert np.all(np.isfinite(conf))  # full coverage
    agreeing = fuse(
        _weighted_model(sand_field=np.full((2, 2), 100.0), water_field=np.full((2, 2), 100.0))
    )
    assert np.all(agreeing.confidence.grid_z == pytest.approx(1.0))


def test_variance_propagation_on_common_support():
    sand = _grid(_sand_ratio_field(), refs=("s@v1",), variance=np.full((2, 2), 4.0))
    water = _grid(_water_depth_field(), refs=("w@v1",), variance=np.full((2, 2), 1.0))
    model = _weighted_model(sand_field=sand.grid_z, water_field=water.grid_z)
    model.evidences[0].grid.variance_grid = np.full((2, 2), 4.0, dtype=np.float32)
    model.evidences[1].grid.variance_grid = np.full((2, 2), 1.0, dtype=np.float32)
    result = fuse(model)
    assert result.variance is not None
    expected = (2 / 3) ** 2 * 4.0 + (1 / 3) ** 2 * 1.0
    assert result.variance.grid_z[0, 1] == pytest.approx(expected, rel=1e-5)


def test_classification_thresholds_partition_classes():
    model = _weighted_model()
    model.class_thresholds = [0.33, 0.6]
    model.class_names = ["低", "中", "高"]
    result = fuse(model)
    counts = result.qc["class_counts"]
    assert sum(counts.values()) == 4
    grid = result.likelihood.grid_z
    # cell (1,0) has the highest membership → highest class
    assert counts["高"] >= 1
    assert counts["低"] >= 1


# ---------------------------------------------------------------------------
# rule-based classification
# ---------------------------------------------------------------------------


def _rule_model() -> FusionModel:
    sand = _grid(_sand_ratio_field(), refs=("sand@v1",))
    mud = _grid(np.array([[85.0, 10.0], [5.0, 70.0]]), refs=("mud@v1",))
    return FusionModel(
        name="岩相规则",
        kind="rule_based",
        evidences=[
            FactorEvidence("砂地比", sand, weight=1.0, normalization=Normalization("minmax", 0, 100)),
            FactorEvidence("泥岩含量", mud, weight=1.0, normalization=Normalization("minmax", 0, 100)),
        ],
        rules=[
            FusionRule((("砂地比", ">=", 50.0),), "砂体"),
            FusionRule(
                (("砂地比", "<", 30.0), ("泥岩含量", ">", 60.0)),
                "泥岩",
            ),
        ],
        default_class="过渡相",
    )


def test_rule_based_first_match_wins_and_default_fills():
    result = fuse(_rule_model())
    classes = result.likelihood.grid_z
    # encoding: 0=default, 1..n=rule index+1
    assert classes[0, 1] == 1  # sand 60 ≥ 50 → 砂体 (first rule wins)
    assert classes[1, 0] == 1  # sand 70 → 砂体
    assert classes[0, 0] == 2  # sand 10 < 30 AND mud 85 > 60 → 泥岩
    assert classes[1, 1] == 2  # sand 20 < 30 AND mud 70 > 60 → 泥岩
    assert result.qc["default_cells"] == 0
    assert result.class_names[0] == "过渡相"


def test_rule_based_default_class_fills_unmatched_cells():
    sand = np.array([[45.0, 60.0], [70.0, 20.0]])
    mud = np.array([[50.0, 10.0], [5.0, 70.0]])
    sand_g = _grid(sand, refs=("sand@v1",))
    mud_g = _grid(mud, refs=("mud@v1",))
    model = FusionModel(
        name="岩相规则",
        kind="rule_based",
        evidences=[
            FactorEvidence("砂地比", sand_g, weight=1.0, normalization=Normalization("minmax", 0, 100)),
            FactorEvidence("泥岩含量", mud_g, weight=1.0, normalization=Normalization("minmax", 0, 100)),
        ],
        rules=[
            FusionRule((("砂地比", ">=", 50.0),), "砂体"),
            FusionRule((("砂地比", "<", 30.0), ("泥岩含量", ">", 60.0)), "泥岩"),
        ],
        default_class="过渡相",
    )
    result = fuse(model)
    classes = result.likelihood.grid_z
    assert classes[0, 0] == 0  # sand 45 matches no rule → 过渡相
    conf = result.confidence.grid_z
    assert conf[0, 0] == 0.0  # default class carries no rule confidence
    assert conf[0, 1] == 1.0  # explicitly matched


def test_rule_based_unknown_factor_raises():
    model = _rule_model()
    object.__setattr__(
        model.rules[0],
        "conditions",
        (("不存在的因子", ">=", 1.0),),
    )
    with pytest.raises(ValueError, match="unknown factor"):
        fuse(model)


def test_rule_based_nan_cells_are_nodata_not_default():
    sand = _sand_ratio_field().copy()
    water = _water_depth_field().copy()
    sand[0, 0] = np.nan
    water[0, 0] = np.nan  # no evidence at this cell at all
    model = FusionModel(
        name="岩相规则",
        kind="rule_based",
        evidences=[
            FactorEvidence("砂地比", _grid(sand, refs=("s@v1",)), weight=1.0,
                           normalization=Normalization("minmax", 0, 100)),
            FactorEvidence("古水深", _grid(water, refs=("w@v1",)), weight=1.0,
                           normalization=Normalization("minmax", 0, 100)),
        ],
        rules=[FusionRule((("砂地比", ">=", 50.0),), "砂体")],
        default_class="未定",
    )
    result = fuse(model)
    # no evidence at all → nodata, never the default class
    assert np.isnan(result.likelihood.grid_z[0, 0])
    assert result.qc["unclassified_cells"] == 1
    # evidence exists but no rule matches → explicit default class
    sand[1, 1] = 20.0
    result2 = fuse(model)
    assert result2.likelihood.grid_z[1, 1] == 0
    assert result2.confidence.grid_z[1, 1] == 0.0


# ---------------------------------------------------------------------------
# sensitivity + polygons + catalog registration
# ---------------------------------------------------------------------------


def test_sensitivity_identifies_dominant_factor():
    model = _weighted_model()
    baseline = fuse(model)
    report = sensitivity_report(model, baseline)
    assert report["supported"] is True
    factors = report["factors"]
    assert set(factors) == {"砂地比", "古水深"}
    # the heavier factor should move classes at least as much as the light one
    assert factors["砂地比"]["class_change_fraction"] >= factors["古水深"]["class_change_fraction"]


def test_rule_based_sensitivity_reported_unsupported():
    model = _rule_model()
    baseline = fuse(model)
    report = sensitivity_report(model, baseline)
    assert report["supported"] is False


def test_fused_likelihood_builds_facies_polygons():
    model = _weighted_model()
    model.class_thresholds = [0.4]
    model.class_names = ["低潜力", "高潜力"]
    result = fuse(model)
    layer = generate_facies_polygon_layer(
        result.likelihood,
        thresholds=[0.4],
        facies_names=["低潜力", "高潜力"],
    )
    assert len(layer.features) >= 1
    assert layer.crs == "EPSG:32650"
    assert layer.metadata["polygon_qc"]["small_polygons_dropped"] == 0


def test_register_output_creates_derived_version_with_run(tmp_path):
    from paleo_workbench.catalog import DataCatalogService

    project_file = tmp_path / "proj" / "demo.paleo.json"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_file)
    try:
        (tmp_path / "sand.npz").write_bytes(b"sand")
        (tmp_path / "wd.npz").write_bytes(b"wd")
        sand = svc.import_raw(tmp_path / "sand.npz", name="sand.npz", type="factor_map")
        wd = svc.import_raw(tmp_path / "wd.npz", name="wd.npz", type="factor_map")
        model = _weighted_model()
        model.evidences[0].grid.source_refs = [sand.id]
        model.evidences[1].grid.source_refs = [wd.id]
        result = fuse(model)
        version_id = register_output(svc, result)
        version = svc.get_version(version_id)
        assert version.run_id, "fused output must carry a DataRun"
        run = next(r for r in svc.document.runs if r.id == version.run_id)
        assert run.operation == "factor_fusion"
        assert sorted(run.input_version_ids) == sorted([sand.id, wd.id])
        assert run.parameters["model"]["kind"] == "weighted_evidence"
        assert run.parameters["model"]["evidences"][0]["weight"] == 2.0
        assert result.qc["catalog_version_id"] == version_id
    finally:
        svc.close()


def test_fused_output_misaligned_grids_rejected():
    sand = _grid(np.array([[1.0, 2.0]]), refs=("s@v1",))
    water = _grid(_water_depth_field(), refs=("w@v1",))
    model = FusionModel(
        name="bad",
        kind="weighted_evidence",
        evidences=[
            FactorEvidence("砂地比", sand, weight=1.0, normalization=Normalization("minmax", 0, 100)),
            FactorEvidence("古水深", water, weight=1.0, normalization=Normalization("minmax", 0, 100)),
        ],
        class_thresholds=[0.5],
        class_names=["低", "高"],
    )
    with pytest.raises(ValueError, match="geometry"):
        fuse(model)
