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
