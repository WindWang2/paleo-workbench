"""mock 沉积相预测 providers：形状 / 确定性 / 诚实标记 / 输入校验。"""
from __future__ import annotations

import pytest

from paleo_workbench.prediction.providers import InferenceInputError, get_provider

WELLS = [
    {"well_id": "well_a", "well_name": "A1", "td": 1200.0},
    {"well_id": "well_b", "well_name": "A2", "td": None},
    {"well_id": "well_c", "well_name": "A3", "td": 900.0},
]
EXTENT = (328.15, 1264.18, 12843.24, 15882.8)  # 工区米制范围（仿真实工程）


def _well_payload(seed=7):
    provider = get_provider("mock_well_facies")
    return provider.run({}, {"seed": seed, "target_horizon": "Sq1", "_wells": WELLS})


def _seismic_payload(seed=7):
    provider = get_provider("mock_seismic_facies")
    return provider.run({}, {
        "seed": seed, "target_horizon": "Sq1", "_extent": EXTENT,
        "_crs": "EPSG:4326 / WGS84", "grid_n": 40,
    })


def test_well_provider_deterministic_and_shaped():
    first, second = _well_payload(7), _well_payload(7)
    assert first == second
    regions = first["result_summary"]["predicted_regions"]
    assert len(regions) == len(WELLS)
    for region, well in zip(regions, WELLS):
        assert region["well_id"] == well["well_id"]
        assert region["well_name"] == well["well_name"]
        assert region["stratigraphic_unit"] == "Sq1"
        assert region["top"] < region["bottom"]
        assert 0.5 <= region["probability"] <= 1.0
    # td=None 的井走占位区间
    assert regions[1]["top"] == 600.0 and regions[1]["bottom"] == 800.0
    # td=1200 → [0.6*td, 0.8*td]
    assert regions[0]["top"] == pytest.approx(720.0)
    assert regions[0]["bottom"] == pytest.approx(960.0)


def test_well_provider_honesty_flags():
    payload = _well_payload()
    summary = payload["result_summary"]
    assert payload["adapter_kind"] == "mock"
    assert payload["demo"] is True and payload["source"] == "synthetic/demo"
    assert summary["is_mock"] is True
    assert summary["final_scientific_prediction"] is False
    assert summary["probabilities_uncalibrated"] is True
    assert summary["model_type"] == "mock"
    assert payload["well_detail"]  # 中间文件内容（逐井明细）


def test_well_provider_requires_wells():
    with pytest.raises(InferenceInputError):
        get_provider("mock_well_facies").run({}, {"seed": 1, "_wells": []})


def test_seismic_provider_polygons_inside_extent_and_deterministic():
    first, second = _seismic_payload(7), _seismic_payload(7)
    assert first == second
    spatial = first["result_summary"]["spatial"]
    assert spatial["type"] == "VECTOR_POLYGONS"
    assert spatial["crs"] == "EPSG:4326 / WGS84"
    features = spatial["features"]
    assert features, "mock 面状相必须产出多边形"
    xmin, ymin, xmax, ymax = EXTENT
    for feature in features:
        assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
        assert feature["properties"].get("facies")
        for ring in feature["geometry"]["coordinates"]:
            for x, y in ring:
                assert xmin - 1e-6 <= x <= xmax + 1e-6
                assert ymin - 1e-6 <= y <= ymax + 1e-6
                # 避开 demo 固定方块（spatial_result 脏数据探测器）
                assert abs(x - 114.0) > 0.2 or abs(y - 22.5) > 0.2
    grid = first["mock_grid"]
    assert len(grid["grid_z"]) == 40 and len(grid["grid_z"][0]) == 40
    assert grid["names"]


def test_seismic_provider_requires_extent():
    with pytest.raises(InferenceInputError):
        get_provider("mock_seismic_facies").run({}, {"seed": 1})


def test_ensure_mock_facies_models_idempotent_and_never_production(tmp_path):
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.prediction.mock_facies import (
        MODEL_ID_MOCK_SEISMIC_FACIES, MODEL_ID_MOCK_WELL_FACIES,
        ensure_mock_facies_models,
    )
    from paleo_workbench.prediction.providers import CAPABILITY_FACIES

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    try:
        well_v, seismic_v = ensure_mock_facies_models(service)
        again_w, again_s = ensure_mock_facies_models(service)
        assert (well_v.id, seismic_v.id) == (again_w.id, again_s.id)
        for version in (well_v, seismic_v):
            assert version.demo_only is True and version.status == "demo"
        production = service.find_production_model(CAPABILITY_FACIES)
        production_ids = {getattr(production, "model_id", None)}
        assert MODEL_ID_MOCK_WELL_FACIES not in production_ids
        assert MODEL_ID_MOCK_SEISMIC_FACIES not in production_ids
    finally:
        service.close()
