# Mock 沉积相预测（测井层位相 + 地震相面状）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在编图工作站 Phase 1「①智能预测」加两个 mock 按钮——「运行测井相预测（mock）」（目标层位全部井各生成一条预测沉积相区间）与「运行地震相面预测（mock）」（按目标层位平面范围生成面状沉积相多边形），结果自动叠加显示，中间文件与生成文件全部经 Data Catalog 落盘并建 DataRun 血缘。

**Architecture:** 新模块 `paleo_workbench/prediction/mock_facies.py` 提供两个确定性伪随机 provider（走既有 `start_inference → execute_run → register_result_asset(DERIVED) → materialize_prediction_task → link_run_to_domain_task` 管线）；中间产物由 stage handler 用 `register_result_asset(stage=INTERMEDIATE, run_id)` 挂同一 run；显示零新通道，复用在途叠加动作。另含一个前置小修复：井/震任务分类启发式改判「键存在」为「键值非空」（`materialize_prediction_task` 恒写双键，现逻辑把一切 pipeline 任务误判为 seismic）。

**Tech Stack:** Python 3.12 / PySide6 / numpy；pytest + pytest-qt（`QT_QPA_PLATFORM=offscreen`）；Data Catalog（`DataCatalogService.open` + `CoreCatalogAdapter` + `set_catalog`）。

**Spec:** `docs/superpowers/specs/2026-09-10-mock-facies-prediction-design.md`（已提交 6d15b8e1）。

## Global Constraints

- 诚实标记逐字全集：`adapter_kind="mock"`、`is_mock=True`、`demo=True`、`final_scientific_prediction=False`、`source="synthetic/demo"`、`model_type="mock"`、`probabilities_uncalibrated=True`。两个 provider 输出与 PredictionTask 必须全程携带。
- mock 模型永远 `status="demo"` + `demo_only=True`；不得被 `find_production_model` 返回；不调 `promote_model`。
- mock 产物只写 INTERMEDIATE / DERIVED，绝不写 OUTPUT（OUTPUT 唯一入口是 `assemble_map_product`）。
- 运行命令统一用仓库 venv：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest ...`。
- **提交纪律（本仓库当前有用户 47 个在途未提交文件）**：只 `git add` 本计划新建的未跟踪文件并单独提交；对已跟踪文件的修改（`stage_actions.py`、`factor_layer_products.py`、`providers.py`）**一律不提交**，留给用户的在途分支统一提交。每步 commit 命令严格遵守此规则。
- 不修改在途文件 `paleo_workbench/mapping/well_prediction_surface.py`（untracked）；不修改在途测试 `tests/test_stage_prediction_overlay.py`——其中 `test_phase1_actions_lead_with_prediction_results` 锁定词表前三项，新动作只能插在第 4 位起。
- 井身份：`Well.id` 是身份，regions 必须双写 `well_id` + `well_name`。

---

### Task 1: mock providers 模块 `paleo_workbench/prediction/mock_facies.py`

**Files:**
- Create: `paleo_workbench/prediction/mock_facies.py`
- Modify: `paleo_workbench/prediction/providers.py`（`_install_bundled_providers` 注册两家；函数尾部在 providers.py:480 附近，`:485` 处有 `_install_bundled_providers()` 调用）
- Test: `tests/test_mock_facies_providers.py`（新建）

**Interfaces:**
- Produces（Task 3 依赖的精确名字）:
  - `PROVIDER_MOCK_WELL_FACIES = "mock_well_facies"`、`PROVIDER_MOCK_SEISMIC_FACIES = "mock_seismic_facies"`
  - `MODEL_ID_MOCK_WELL_FACIES = "mock-well-facies-v1"`、`MODEL_ID_MOCK_SEISMIC_FACIES = "mock-seismic-facies-v1"`
  - `MOCK_FACIES_CLASSES = ("扇三角洲", "三角洲前缘", "滨浅湖", "湖相泥")`
  - `class MockWellFaciesProvider` / `class MockSeismicFaciesProvider`，各有 `model_id` / `model_version = "1"` / `demo_only = True` 类属性与 `run(inputs: dict, parameters: dict) -> dict`
  - `ensure_mock_facies_models(service) -> tuple[ModelVersion, ModelVersion]`（well 在前）
  - well provider 读 `parameters["_wells"] = [{"well_id","well_name","td"}]`（空 → `InferenceInputError`）；输出 payload 含 `well_detail`（中间文件内容）与 `result_summary.predicted_regions`
  - seismic provider 读 `parameters["_extent"]=(xmin,ymin,xmax,ymax)`、可选 `_clip_ring`、`_crs`、`grid_n`（默认 80）；无有效 extent → `InferenceInputError`；输出 payload 含 `mock_grid` 与 `result_summary.spatial = {type:"VECTOR_POLYGONS", crs, features:[{"type":"Feature","geometry","properties"}]}`
- Consumes: `paleo_workbench.prediction.providers` 的 `CAPABILITY_FACIES`、`InferenceInputError`、`register_model`/`get_model_version` 等 service API；`paleo_workbench.mapping.geological_pipeline.polygonization.generate_facies_polygon_layer`；`paleo_workbench.workflow.factor_grid_result.FactorGridResult`；`paleo_workbench.mapping.geometry_planar.point_in_ring_scalar_inclusive`

- [ ] **Step 1: 写失败测试** `tests/test_mock_facies_providers.py`

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_mock_facies_providers.py -q`
Expected: FAIL（`Unknown model provider: 'mock_well_facies'` 或 import error）

- [ ] **Step 3: 实现 `paleo_workbench/prediction/mock_facies.py`**

```python
"""Mock 沉积相预测 providers（演示专用，永不进生产）。

两个 provider 均为确定性伪随机生成，输出携带全套诚实标记
（adapter_kind="mock" / is_mock / demo / final_scientific_prediction=False），
MapProduct 凭 source_kind=mock fail-closed 拒收（workflow/map_product.py）。
"""
from __future__ import annotations

import math
import random
from typing import Any

from paleo_workbench.prediction.providers import (
    CAPABILITY_FACIES,
    InferenceInputError,
)

PROVIDER_MOCK_WELL_FACIES = "mock_well_facies"
PROVIDER_MOCK_SEISMIC_FACIES = "mock_seismic_facies"
MODEL_ID_MOCK_WELL_FACIES = "mock-well-facies-v1"
MODEL_ID_MOCK_SEISMIC_FACIES = "mock-seismic-facies-v1"
MOCK_FACIES_GENERATOR_VERSION = "mock-facies-1.0"

#: mock 相类词表（与 CONTEXT ClassMap 示例对齐）。
MOCK_FACIES_CLASSES = ("扇三角洲", "三角洲前缘", "滨浅湖", "湖相泥")

#: 无 td 井的占位区间（mock 规则，随 run parameters 落血缘）。
_FALLBACK_INTERVAL = (600.0, 800.0)

_HONESTY = {
    "is_mock": True,
    "is_replaceable": True,
    "final_scientific_prediction": False,
    "demo": True,
    "source": "synthetic/demo",
    "model_type": "mock",
    "probabilities_uncalibrated": True,
}


class MockWellFaciesProvider:
    """对目标层位的全部井各生成一条预测沉积相区间（mock）。"""

    model_id = MODEL_ID_MOCK_WELL_FACIES
    model_version = "1"
    demo_only = True

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        seed = int(parameters.get("seed", 0) or 0)
        horizon = str(parameters.get("target_horizon") or "")
        wells = parameters.get("_wells") or []
        if not wells:
            raise InferenceInputError(
                "mock 测井相预测需要至少一口井（_wells 为空）")
        rng = random.Random(seed)
        regions: list[dict[str, Any]] = []
        detail: list[dict[str, Any]] = []
        for index, well in enumerate(wells):
            td = well.get("td")
            if isinstance(td, (int, float)) and math.isfinite(td) and td > 0:
                top, bottom = round(0.6 * float(td), 2), round(0.8 * float(td), 2)
            else:
                top, bottom = _FALLBACK_INTERVAL
            draw = rng.random()
            facies = MOCK_FACIES_CLASSES[
                min(int(draw * len(MOCK_FACIES_CLASSES)), len(MOCK_FACIES_CLASSES) - 1)
            ]
            probability = round(0.55 + rng.random() * 0.35, 3)
            region = {
                "region_id": f"mock_well_region_{index + 1}",
                "well_id": str(well.get("well_id") or ""),
                "well_name": str(well.get("well_name") or ""),
                "stratigraphic_unit": horizon,
                "horizon": horizon,
                "top": top,
                "bottom": bottom,
                "facies": facies,
                "probability": probability,
            }
            regions.append(region)
            detail.append({**region, "rng_draw": round(draw, 6)})
        mean_p = round(
            sum(item["probability"] for item in regions) / len(regions), 3)
        return {
            "adapter_kind": "mock",
            "generator_version": MOCK_FACIES_GENERATOR_VERSION,
            "demo": True,
            "source": "synthetic/demo",
            "result_summary": {
                "predicted_regions": regions,
                "target_horizon": horizon,
                **_HONESTY,
            },
            "probability_summary": {"mean_probability": mean_p},
            "review_areas": [r for r in regions if r["probability"] < 0.7],
            "seed": seed,
            # 中间文件内容：stage handler 弹出并登记为 INTERMEDIATE 版本。
            "well_detail": detail,
        }


class MockSeismicFaciesProvider:
    """按目标层位平面范围生成面状沉积相多边形（mock，最近邻斑块）。"""

    model_id = MODEL_ID_MOCK_SEISMIC_FACIES
    model_version = "1"
    demo_only = True

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        import numpy as np

        seed = int(parameters.get("seed", 0) or 0)
        horizon = str(parameters.get("target_horizon") or "")
        extent = parameters.get("_extent")
        if not extent or len(extent) < 4:
            raise InferenceInputError(
                "mock 地震相面预测需要有效平面范围（_extent 缺失）")
        xmin, ymin, xmax, ymax = (float(v) for v in extent[:4])
        values = (xmin, ymin, xmax, ymax)
        if not all(math.isfinite(v) for v in values) or xmax <= xmin or ymax <= ymin:
            raise InferenceInputError(
                f"mock 地震相面预测的平面范围无效：{extent!r}")
        crs = str(parameters.get("_crs") or "")
        grid_n = max(2, int(parameters.get("grid_n", 80) or 80))
        ring = parameters.get("_clip_ring") or None

        rng = random.Random(seed)
        anchors = [
            (
                rng.uniform(xmin, xmax),
                rng.uniform(ymin, ymax),
                rng.randrange(len(MOCK_FACIES_CLASSES)),
            )
            for _ in range(12)
        ]
        grid_x = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
        grid_y = np.linspace(ymin, ymax, grid_n, dtype=np.float64)
        xs = np.array([a[0] for a in anchors], dtype=np.float64)
        ys = np.array([a[1] for a in anchors], dtype=np.float64)
        classes = np.array([a[2] for a in anchors], dtype=np.int16)
        dx = grid_x[None, :, None] - xs[None, None, :]
        dy = grid_y[:, None, None] - ys[None, None, :]
        nearest = np.argmin(dx * dx + dy * dy, axis=-1)
        grid_z = classes[nearest].astype(np.float32)
        if ring:
            from paleo_workbench.mapping.geometry_planar import (
                point_in_ring_scalar_inclusive,
            )

            cleaned = [
                (float(x), float(y)) for x, y, *_ in ring
                if math.isfinite(float(x)) and math.isfinite(float(y))
            ]
            if len(cleaned) >= 4:
                mask = np.ones(grid_z.shape, dtype=bool)
                for row, y in enumerate(grid_y):
                    for col, x in enumerate(grid_x):
                        if not point_in_ring_scalar_inclusive(
                                float(x), float(y), cleaned):
                            mask[row, col] = False
                grid_z = np.where(mask, grid_z, np.float32(np.nan))

        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        grid = FactorGridResult(
            grid_z=grid_z,
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name="地震相面预测（mock）",
            algorithm_id="mock_nearest_neighbor",
            algorithm_parameters={
                "method": "mock_nearest_neighbor",
                "anchors": len(anchors),
                "grid_n": grid_n,
            },
            crs=crs or None,
        )
        n_class = len(MOCK_FACIES_CLASSES)
        layer = generate_facies_polygon_layer(
            grid,
            thresholds=[i + 0.5 for i in range(n_class - 1)],
            facies_names=list(MOCK_FACIES_CLASSES),
            clip_ring=ring,
            name="地震相面预测（mock）",
        )
        features: list[dict[str, Any]] = []
        for record in layer.features or ():
            if not isinstance(record, dict):
                continue
            geometry = record.get("geometry")
            if not isinstance(geometry, dict):
                continue
            if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            properties = dict(record.get("properties") or {})
            properties.setdefault(
                "facies", properties.get("facies_name") or "")
            properties["horizon"] = horizon
            properties["probability"] = round(0.55 + rng.random() * 0.35, 3)
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": properties,
            })
        if not features:
            raise InferenceInputError(
                "mock 地震相面预测未产出任何相区多边形（范围过小？）")
        return {
            "adapter_kind": "mock",
            "generator_version": MOCK_FACIES_GENERATOR_VERSION,
            "demo": True,
            "source": "synthetic/demo",
            "result_summary": {
                "spatial": {
                    "type": "VECTOR_POLYGONS",
                    "crs": crs,
                    "features": features,
                },
                "target_horizon": horizon,
                **_HONESTY,
            },
            "probability_summary": {
                "mean_probability": round(
                    sum(f["properties"]["probability"] for f in features)
                    / len(features), 3),
            },
            "review_areas": [],
            "seed": seed,
            # 中间文件内容：stage handler 弹出并写 .factor_grid.npz 登记
            # 为 INTERMEDIATE 版本。
            "mock_grid": {
                "grid_z": grid_z.tolist(),
                "grid_x": grid_x.tolist(),
                "grid_y": grid_y.tolist(),
                "names": list(MOCK_FACIES_CLASSES),
                "extent": [xmin, ymin, xmax, ymax],
                "crs": crs,
                "grid_n": grid_n,
            },
        }


def ensure_mock_facies_models(service):
    """幂等注册两个 mock 模型（均 status="demo"、demo_only=True）。

    仓库零生产模型：本函数只补登记，绝不晋升；`find_production_model`
    对 demo_only 版本永远不可见。返回 (well_version, seismic_version)。
    """
    from paleo_workbench.prediction.providers import (
        _ensure_model_version,
        _existing_model,
    )

    if _existing_model(service, MODEL_ID_MOCK_WELL_FACIES) is None:
        service.register_model(
            model_id=MODEL_ID_MOCK_WELL_FACIES,
            model_name="测井层位沉积相预测（mock）",
            model_type="mock",
            capability=CAPABILITY_FACIES,
            provider=PROVIDER_MOCK_WELL_FACIES,
            status="demo",
            metadata={"source": "synthetic/demo", "demo_only": True},
        )
    well_version = _ensure_model_version(
        service, MODEL_ID_MOCK_WELL_FACIES, "1",
        deterministic=True, demo_only=True, status="demo",
        metadata={"source": "synthetic/demo"},
    )
    if _existing_model(service, MODEL_ID_MOCK_SEISMIC_FACIES) is None:
        service.register_model(
            model_id=MODEL_ID_MOCK_SEISMIC_FACIES,
            model_name="地震相面状沉积相预测（mock）",
            model_type="mock",
            capability=CAPABILITY_FACIES,
            provider=PROVIDER_MOCK_SEISMIC_FACIES,
            status="demo",
            metadata={"source": "synthetic/demo", "demo_only": True},
        )
    seismic_version = _ensure_model_version(
        service, MODEL_ID_MOCK_SEISMIC_FACIES, "1",
        deterministic=True, demo_only=True, status="demo",
        metadata={"source": "synthetic/demo"},
    )
    return well_version, seismic_version
```

- [ ] **Step 4: 在 `providers.py` 的 `_install_bundled_providers` 内（tiled onnx 那段之后）注册**

```python
    from paleo_workbench.prediction.mock_facies import (
        PROVIDER_MOCK_SEISMIC_FACIES,
        PROVIDER_MOCK_WELL_FACIES,
        MockSeismicFaciesProvider,
        MockWellFaciesProvider,
    )

    PROVIDER_BY_NAME.setdefault(PROVIDER_MOCK_WELL_FACIES, MockWellFaciesProvider)
    PROVIDER_BY_NAME.setdefault(PROVIDER_MOCK_SEISMIC_FACIES, MockSeismicFaciesProvider)
```

注意：不用 try/except 包裹（本仓库模块，导入错误必须暴露）；`mock_facies` 顶层只 import `providers` 的常量（在 `providers.py:485` 调用点之前已定义），惰性 import 无循环风险。

- [ ] **Step 5: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_mock_facies_providers.py tests/test_inference_service.py -q`
Expected: 全 PASS（含既有 inference 套件无回归）

- [ ] **Step 6: Commit（仅新文件）**

```bash
git add paleo_workbench/prediction/mock_facies.py tests/test_mock_facies_providers.py
git commit -m "feat(prediction): mock well-horizon + seismic-areal facies providers (demo-only, honest flags)"
# providers.py 的修改不提交（工作区在途分支统一处理）
```

---

### Task 2: 井/震分类启发式修复（值非空判定）

**Files:**
- Modify: `paleo_workbench/ui/workstation/stage_actions.py:378-396`（`StageActionDispatcher._classify_prediction_task`）
- Modify: `paleo_workbench/mapping/factor_layer_products.py:547-561`（`classify_prediction_task`）
- Test: `tests/test_prediction_task_classification.py`（新建）

**Interfaces:**
- Produces: 两个分类器的新语义——只有「键存在 **且对应值非空**」才参与分类；空值键回退到任务名判定。签名不变（`-> str`，返回 `"well"|"seismic"|"unknown"`）。
- Consumes: 无（纯行为修复）。

背景（为什么必须先修）：`materialize_prediction_task`（`prediction/inference_service.py:717-724`）**恒写双键** `well_log_resource_ids`/`seismic_resource_ids`（值可为空列表）；现分类器只查键存在性且 `"seis"` 在前，导致一切经管线产生的任务都判成 seismic——Task 3 的测井 mock 任务会叠不到井点层。

- [ ] **Step 1: 写失败测试** `tests/test_prediction_task_classification.py`

```python
"""井/震预测任务分类：键存在不算数，键值非空才算（pipeline 恒写双键）。"""
from __future__ import annotations

from paleo_workbench.mapping.factor_layer_products import classify_prediction_task
from paleo_workbench.project.models import PredictionTask
from paleo_workbench.ui.workstation.stage_actions import StageActionDispatcher


def _task(refs, name=""):
    return PredictionTask(name=name, input_refs=refs)


def _both(task):
    return (
        classify_prediction_task(task),
        StageActionDispatcher._classify_prediction_task(task),
    )


def test_pipeline_well_task_classifies_well():
    # materialize_prediction_task 恒写双键；seismic 值为空列表
    task = _task({"well_log_resource_ids": ["res_a"], "seismic_resource_ids": []})
    assert _both(task) == ("well", "well")


def test_pipeline_seismic_task_classifies_seismic():
    task = _task({"well_log_resource_ids": [], "seismic_resource_ids": ["seis1"]})
    assert _both(task) == ("seismic", "seismic")


def test_legacy_single_key_shapes_still_work():
    assert _both(_task({"well_log_resource_ids": ["res_a"]})) == ("well", "well")
    assert _both(_task({"seismic_resource_ids": ["seis1"]})) == ("seismic", "seismic")


def test_empty_values_fall_back_to_name():
    assert _both(_task(
        {"well_log_resource_ids": [], "seismic_resource_ids": []},
        name="测井相预测（mock）· Sq1",
    )) == ("well", "well")
    assert _both(_task({}, name="地震相面预测")) == ("seismic", "seismic")
    assert _both(_task({}, name="")) == ("unknown", "unknown")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_prediction_task_classification.py -q`
Expected: FAIL（`test_pipeline_well_task_classifies_well` 得 `("seismic", "seismic")`）

- [ ] **Step 3: 修 `stage_actions.py:378-396`**

在 `_classify_prediction_task` 中，精确替换这两行：

```python
        refs = getattr(task, "input_refs", None) or {}
        keys = " ".join(str(key).lower() for key in refs.keys())
```

为（只保留值非空的键参与分类，其余名称回退段原样不动；docstring 末尾追加一句「materialize_prediction_task 恒写双键（值可为空列表），只看键名会把 pipeline 任务误判为 seismic」）：

```python
        refs = getattr(task, "input_refs", None) or {}
        keys = " ".join(
            str(key).lower() for key, value in refs.items() if value
        )
```

- [ ] **Step 4: 修 `factor_layer_products.py:547-561`**

精确替换：

```python
    refs = getattr(task, "input_refs", None) or {}
    keys = " ".join(str(key).lower() for key in refs.keys()) if isinstance(refs, Mapping) else ""
```

为：

```python
    refs = getattr(task, "input_refs", None) or {}
    keys = (
        " ".join(str(key).lower() for key, value in refs.items() if value)
        if isinstance(refs, Mapping)
        else ""
    )
```

- [ ] **Step 5: 跑测试确认通过 + 既有套件无回归**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_prediction_task_classification.py tests/test_stage_prediction_overlay.py tests/test_well_prediction_surface.py -q`
Expected: 全 PASS

- [ ] **Step 6: Commit（仅新文件）**

```bash
git add tests/test_prediction_task_classification.py
git commit -m "test(prediction): pin value-nonempty well/seismic task classification"
# stage_actions.py / factor_layer_products.py 的修改不提交
```

---

### Task 3: 阶段动作接线（两个按钮 + handler + 中间文件登记 + 自动叠加）

**Files:**
- Modify: `paleo_workbench/ui/workstation/stage_actions.py`（词表 :52-60、门禁 :96-113、dispatch :120-138、新增 handler 挂在 Phase 1 段 `:256` 前后）
- Test: `tests/test_stage_prediction_mock_actions.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `ensure_mock_facies_models` / provider 输出形状；Task 2 的分类语义；既有 `start_inference(service, *, model_version_id, input_version_ids, parameters, operation)`（inference_service.py:246）、`execute_run(service, run.id)`（:332，provider 抛错时先把 run 置 failed 再抛出——实现时以 :332-503 函数体为准）、`materialize_prediction_task(...)`（:674）、`link_run_to_domain_task(service, run_id, task_id)`（:660）、`resolve_prediction_inputs(project, service)`（:96）；`get_catalog_service()`（catalog/runtime.py:52，None = 无编目）；既有 `add_well_prediction_overlay()` / `add_seismic_prediction_overlay()`。
- Produces: 词表新增 `run_well_facies_mock` / `run_seismic_facies_mock`；dispatcher 方法 `run_well_facies_mock()` / `run_seismic_facies_mock()`；辅助 `_mock_run_parameters(project, horizon, *, kind)` 与 `_register_mock_intermediates(service, run_id, payload, *, kind)`。

- [ ] **Step 1: 写失败测试** `tests/test_stage_prediction_mock_actions.py`

```python
"""智能预测阶段：两个 mock 生成按钮（fallback 画布 + 真 catalog）。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import WellEntity, WorkArea
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.stage_actions import stage_context_actions

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


def _project() -> ProjectDocument:
    project = ProjectDocument.new("mock 预测")
    project.coordinate.project_crs = "EPSG:32650"
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.wells.extend([
        WellEntity(id="well_a", name="A", project_x=0.0, project_y=0.0, td=1200.0),
        WellEntity(id="well_b", name="B", project_x=10.0, project_y=0.0),
    ])
    project.resources.extend([
        ResourceItem(id="res_a", name="A", path="a.las", type="well_log", format="las"),
        ResourceItem(id="res_b", name="B", path="b.las", type="well_log", format="las"),
    ])
    project.stratigraphy.target_horizon = "Sq1"
    return project


@pytest.fixture
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    try:
        yield service
    finally:
        reset_catalog()
        service.close()


def test_actions_listed_after_overlay_actions():
    ids = [action_id for action_id, _ in stage_context_actions("facies_calibration")]
    assert ids[:3] == [
        "add_seismic_prediction_overlay",
        "add_well_prediction_overlay",
        "well_prediction_point_to_surface",
    ]
    assert "run_well_facies_mock" in ids and "run_seismic_facies_mock" in ids


def test_dispatch_mock_requires_horizon(qtbot, monkeypatch, catalog):
    project = _project()
    project.stratigraphy.target_horizon = ""
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert any("编图层位" in text for text in messages)
    assert not project.prediction_tasks


def test_run_well_facies_mock_end_to_end(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert len(project.prediction_tasks) == 1
    task = project.prediction_tasks[0]
    assert task.adapter_kind == "mock"
    assert task.result_summary["is_mock"] is True
    assert task.result_summary["final_scientific_prediction"] is False
    regions = task.result_summary["predicted_regions"]
    assert len(regions) == 2
    assert {r["stratigraphic_unit"] for r in regions} == {"Sq1"}
    assert task.input_refs["well_log_resource_ids"] == ["res_a", "res_b"]
    # 血缘：run 完成且三向链接
    run = catalog.get_run(task.model_metadata["run_id"])
    assert run.status == "completed"
    assert run.parameters.get("_domain_task_id") == task.id
    assert task.model_metadata["prediction_version_id"] in run.output_version_ids
    # 中间文件：同 run 的 INTERMEDIATE 版本
    stages = {
        version.stage
        for version in catalog.document.versions
        if version.id in set(run.output_version_ids)
    }
    assert DataStage.DERIVED in stages and DataStage.INTERMEDIATE in stages
    # 自动叠加：井点层出现
    ids = doc.stage_controller.state.layers_with_role(LayerRole.WELL_FACIES_PREDICTION)
    assert ids


def test_run_seismic_facies_mock_end_to_end(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_seismic_facies_mock")
    assert len(project.prediction_tasks) == 1
    task = project.prediction_tasks[0]
    spatial = task.result_summary.get("spatial") or {}
    assert spatial.get("type") == "VECTOR_POLYGONS"
    features = spatial.get("features") or []
    assert features
    for feature in features:
        for ring in feature["geometry"]["coordinates"]:
            for x, y in ring:
                assert -3 <= x <= 13 and -3 <= y <= 3  # 工区 bbox 附近
    run = catalog.get_run(task.model_metadata["run_id"])
    stages = {
        version.stage
        for version in catalog.document.versions
        if version.id in set(run.output_version_ids)
    }
    assert DataStage.DERIVED in stages and DataStage.INTERMEDIATE in stages
    ids = doc.stage_controller.state.layers_with_role(
        LayerRole.SEISMIC_FACIES_PREDICTION)
    assert ids


def test_repeat_runs_create_distinct_tasks(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert len(project.prediction_tasks) == 2
    assert project.prediction_tasks[0].id != project.prediction_tasks[1].id


def test_run_mock_without_catalog_graceful(qtbot, monkeypatch):
    reset_catalog()
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert not project.prediction_tasks
    assert any("编目" in text for text in messages)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stage_prediction_mock_actions.py -q`
Expected: FAIL（`未知阶段动作：run_well_facies_mock` / 词表断言失败）

- [ ] **Step 3: 改 `STAGE_CONTEXT_ACTIONS`（stage_actions.py:52-60）**——在第 3 项后插入（**不得**动前三项，在途测试锁定）：

```python
    "facies_calibration": (
        ("add_seismic_prediction_overlay", "叠加地震相预测"),
        ("add_well_prediction_overlay", "叠加测井相预测"),
        ("well_prediction_point_to_surface", "测井点到面"),
        ("run_well_facies_mock", "运行测井相预测（mock）"),
        ("run_seismic_facies_mock", "运行地震相面预测（mock）"),
        ("load_initial_facies", "加载初始相图"),
        ("create_facies_draft", "创建解释草稿"),
        ("stage_save", "保存阶段成果"),
    ),
```

- [ ] **Step 4: `_REQUIRES_HORIZON` 加入两个 id**（stage_actions.py:96-113 的 frozenset 内加 `"run_well_facies_mock",` 与 `"run_seismic_facies_mock",`）；dispatch 映射表（:120-138）加：

```python
            "run_well_facies_mock": self.run_well_facies_mock,
            "run_seismic_facies_mock": self.run_seismic_facies_mock,
```

- [ ] **Step 5: 实现 handler**（放在 Phase 1 段，`add_well_prediction_overlay` 之前；完整代码）：

```python
    # -- Phase 1：mock 预测生成（生产 → 落编目 → 自动叠加） ---------------------

    def run_well_facies_mock(self) -> None:
        """对目标层位的全部井生成 mock 测井沉积相，并叠加井点显示。"""
        self._run_mock_prediction(kind="well")

    def run_seismic_facies_mock(self) -> None:
        """对目标层位平面范围生成 mock 面状沉积相，并叠加相区显示。"""
        self._run_mock_prediction(kind="seismic")

    def _run_mock_prediction(self, *, kind: str) -> None:
        from paleo_workbench.catalog.runtime import get_catalog_service

        service = get_catalog_service()
        if service is None:
            self.composite.status_message.emit(
                "数据编目不可用——无法运行 mock 预测（预测结果必须落编目建血缘）")
            return
        project = self.project
        horizon = self._mapping_horizon()
        import secrets

        from paleo_workbench.prediction.inference_service import (
            execute_run,
            link_run_to_domain_task,
            materialize_prediction_task,
            resolve_prediction_inputs,
            start_inference,
        )
        from paleo_workbench.prediction.mock_facies import (
            ensure_mock_facies_models,
        )
        from paleo_workbench.prediction.providers import InferenceInputError

        well_version, seismic_version = ensure_mock_facies_models(service)
        model_version = well_version if kind == "well" else seismic_version
        try:
            parameters = self._mock_run_parameters(project, horizon, kind=kind)
        except InferenceInputError as exc:
            self.composite.status_message.emit(str(exc))
            return
        parameters["seed"] = secrets.randbelow(2**31)
        operation = "well_facies_mock" if kind == "well" else "seismic_facies_mock"
        input_ids = resolve_prediction_inputs(project, service)
        run = start_inference(
            service,
            model_version_id=model_version.id,
            input_version_ids=input_ids,
            parameters=parameters,
            operation=operation,
        )
        try:
            outcome = execute_run(service, run.id)
        except Exception as exc:
            # execute_run 已把 run 置 failed（诚实失败）；此处只负责可见性。
            self.composite.status_message.emit(f"mock 预测失败：{exc}")
            return
        payload = dict(outcome.get("result") or {})
        self._register_mock_intermediates(service, run.id, payload, kind=kind)
        resources = getattr(project, "resources", None) or []
        task = materialize_prediction_task(
            project,
            payload,
            name_prefix=(
                "测井相预测（mock）" if kind == "well" else "地震相面预测（mock）"),
            workflow=operation,
            target_horizon=horizon,
            well_log_resource_ids=[
                str(r.id) for r in resources
                if getattr(r, "type", "") == "well_log"
            ],
            seismic_resource_ids=[
                str(r.id) for r in resources
                if getattr(r, "type", "") == "seismic"
            ],
            run_id=run.id,
            output_version_id=str(
                getattr(outcome.get("output_version"), "id", "") or ""),
        )
        project.prediction_tasks.append(task)
        try:
            link_run_to_domain_task(service, run.id, task.id)
        except Exception:
            task.model_metadata["link_failed"] = True
            logger.exception("link_run_to_domain_task failed for run %s", run.id)
        summary = dict(task.result_summary or {})
        if kind == "well":
            self.add_well_prediction_overlay()
            count = len(summary.get("predicted_regions") or [])
            self.composite.status_message.emit(
                f"已生成 {count} 口井的预测沉积相（mock，层位 {horizon}），"
                "已叠加井点显示")
        else:
            self.add_seismic_prediction_overlay()
            features = (summary.get("spatial") or {}).get("features") or []
            self.composite.status_message.emit(
                f"已生成面状沉积相（mock，层位 {horizon}）："
                f"{len(features)} 个相区，已叠加显示")

    def _mock_run_parameters(self, project, horizon: str, *, kind: str) -> dict:
        from paleo_workbench.prediction.providers import InferenceInputError

        if kind == "well":
            wells = list(getattr(project, "wells", None) or [])
            if not wells:
                raise InferenceInputError("工程中没有井，无法生成测井相预测")
            return {
                "target_horizon": horizon,
                "_wells": [
                    {
                        "well_id": str(getattr(w, "id", "") or ""),
                        "well_name": str(getattr(w, "name", "") or ""),
                        "td": getattr(w, "td", None),
                    }
                    for w in wells
                ],
            }
        extent, ring = self._mock_areal_extent(project)
        if extent is None:
            raise InferenceInputError(
                "无可用平面范围（工区边界 / 井位 / 地震工区均为空），"
                "无法生成面状沉积相")
        crs = str(
            getattr(getattr(project, "coordinate", None), "project_crs", "")
            or "")
        return {
            "target_horizon": horizon,
            "_extent": extent,
            "_clip_ring": ring,
            "_crs": crs,
            "grid_n": 80,
        }

    @staticmethod
    def _mock_areal_extent(project):
        """mock 面状相的平面范围：工区边界 bbox（带 clip ring）→ 井位 bbox
        +10% padding → 地震工区角点 bbox。返回 ((xmin,ymin,xmax,ymax), ring|None)。"""
        import math

        def _bbox(points):
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return (min(xs), min(ys), max(xs), max(ys))

        boundary = getattr(getattr(project, "workarea", None), "boundary", None) or []
        ring = [
            (float(x), float(y)) for x, y, *_ in boundary
            if math.isfinite(float(x)) and math.isfinite(float(y))
        ]
        if len(ring) >= 3:
            return _bbox(ring), ring
        well_points = [
            (float(w.project_x), float(w.project_y))
            for w in (getattr(project, "wells", None) or [])
            if math.isfinite(float(getattr(w, "project_x", float("nan"))))
            and math.isfinite(float(getattr(w, "project_y", float("nan"))))
        ]
        if well_points:
            xmin, ymin, xmax, ymax = _bbox(well_points)
            pad_x = max((xmax - xmin) * 0.1, 1.0)
            pad_y = max((ymax - ymin) * 0.1, 1.0)
            return (xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y), None
        corners = []
        for survey in (getattr(project, "seismic_surveys", None) or []):
            for point in (getattr(survey, "extent", None) or []):
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if math.isfinite(x) and math.isfinite(y):
                    corners.append((x, y))
        if len(corners) >= 3:
            return _bbox(corners), None
        return None, None

    def _register_mock_intermediates(
            self, service, run_id: str, payload: dict, *, kind: str) -> None:
        """中间文件登记：同 run 的 INTERMEDIATE 版本（用户硬性要求）。

        注意 DERIVED 结果 JSON（execute_run 已落盘）仍含这些数据——此处
        弹出只是为了 task.result_summary 干净；中间版本才是规范留存。
        """
        import json
        import tempfile
        from pathlib import Path

        from paleo_workbench.catalog.models import DataStage

        if kind == "well":
            detail = payload.pop("well_detail", None)
            if not detail:
                return
            fd, tmp = tempfile.mkstemp(
                prefix="mock_well_facies_", suffix=".json")
            try:
                with open(fd, "w", encoding="utf-8") as handle:
                    json.dump({"wells": detail}, handle,
                              ensure_ascii=False, indent=2)
                service.register_result_asset(
                    name="测井相预测（mock）逐井明细",
                    type="prediction_intermediate",
                    format="json",
                    asset_metadata={"kind": "prediction_intermediate"},
                    source_path=tmp,
                    stage=DataStage.INTERMEDIATE,
                    run_id=run_id,
                    version_metadata={
                        "kind": "prediction_intermediate", "mock": True},
                )
            finally:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
            return
        grid = payload.pop("mock_grid", None)
        if not grid:
            return
        import numpy as np

        from paleo_workbench.catalog.grid_artifact import write_grid_artifact
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        result = FactorGridResult(
            grid_z=np.asarray(grid["grid_z"], dtype=np.float32),
            grid_x=np.asarray(grid["grid_x"], dtype=np.float64),
            grid_y=np.asarray(grid["grid_y"], dtype=np.float64),
            factor_name="地震相面预测（mock）中间栅格",
            algorithm_id="mock_nearest_neighbor",
            algorithm_parameters={"grid_n": int(grid.get("grid_n", 80))},
            crs=grid.get("crs") or None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_grid_artifact(result, tmpdir, "mock_seismic_facies")
            service.register_result_asset(
                name="地震相面预测（mock）中间栅格",
                type="prediction_intermediate",
                format="npz",
                asset_metadata={"kind": "prediction_intermediate"},
                source_path=artifact,
                stage=DataStage.INTERMEDIATE,
                run_id=run_id,
                version_metadata={
                    "kind": "prediction_intermediate", "mock": True},
            )
```

- [ ] **Step 6: 跑测试确认通过 + 相关套件无回归**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stage_prediction_mock_actions.py tests/test_stage_prediction_overlay.py tests/test_prediction_task_classification.py tests/test_mock_facies_providers.py tests/test_mapping_stage_ui.py tests/test_inference_service.py -q`
Expected: 全 PASS（注意：test_mapping_stage_ui.py 整套跑有既存顺序依赖段错误——若撞上，按既有结论单跑该文件逐用例确认即可，与本改动无关）

- [ ] **Step 7: Commit（仅新文件）**

```bash
git add tests/test_stage_prediction_mock_actions.py
git commit -m "test(stage): mock facies generation actions e2e (catalog lineage + auto overlay)"
# stage_actions.py 的修改不提交
```

---

## 验证总线（全部任务完成后）

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_mock_facies_providers.py \
  tests/test_prediction_task_classification.py \
  tests/test_stage_prediction_mock_actions.py \
  tests/test_stage_prediction_overlay.py \
  tests/test_well_prediction_surface.py \
  tests/test_inference_service.py \
  tests/test_qgis_layer_groups.py -q
```

然后启动应用实测（`/home/kevin/projects/paleo_project/data/project_area/project_area.paleo.json`）：Phase 1 面板出现两个新按钮 → 设定编图层位 → 点「运行测井相预测（mock）」→ 状态栏报井数、地图出井点层 → 点「运行地震相面预测（mock）」→ 出相区多边形层 → 数据页/编目里能看到 DERIVED + INTERMEDIATE 版本与 run 血缘。

## 风险与备注

- `stage_actions.py`、`factor_layer_products.py`、`providers.py` 的修改混入用户在途脏文件，**全部不提交**，由用户随其分支统一提交（本计划只提交新建文件）。
- DERIVED 结果 JSON 内仍带 `well_detail`/`mock_grid` 副本（execute_run 先于中间登记落盘）——mock 规模无害，真模型接入时如需瘦身再议。
- 地震 mock 的 clip ring 在地理 CRS 下只是平面近似（polygonization 既有 `area_warnings` 语义），与工区既有惯例一致。
- mock 结果图层为 RAW 保护角色（WELL/SEISMIC_FACIES_PREDICTION），不可人工编辑——符合预测层契约。
