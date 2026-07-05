from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from paleo_workbench.project.models import PredictionTask, ProjectDocument


GENERATOR_VERSION = "mock-prediction-v1"


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MockPredictionAdapter:
    adapter_kind = "mock"
    schema_version = "1.0"

    def run(
        self,
        project: ProjectDocument,
        factor_map_ids: list[str],
        seed: int,
    ) -> PredictionTask:
        rng = random.Random(seed)
        facies = ["三角洲前缘砂体", "水下分流河道砂体", "分流间湾泥", "滨岸砂体"]
        predicted = [
            {
                "region_id": f"mock_region_{i + 1}",
                "facies": facies[i % len(facies)],
                "probability": round(0.55 + rng.random() * 0.35, 3),
            }
            for i in range(4)
        ]
        snapshot = {
            "factor_map_ids": factor_map_ids,
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "schema_version": self.schema_version,
        }
        task = PredictionTask(
            name="Mock sedimentary facies prediction",
            adapter_kind=self.adapter_kind,
            input_factor_map_ids=factor_map_ids,
            result_summary={
                "predicted_regions": predicted,
                "is_mock": True,
                "is_replaceable": True,
                "final_scientific_prediction": False,
            },
            probability_summary={
                "mean_probability": round(
                    sum(item["probability"] for item in predicted) / len(predicted),
                    3,
                ),
            },
            evidence_contribution=[
                {"name": "sand_thickness", "weight": 0.45},
                {"name": "target_horizon", "weight": 0.30},
                {"name": "neighbor_wells", "weight": 0.25},
            ],
            review_areas=[item for item in predicted if item["probability"] < 0.7],
            status="complete",
            adapter_schema_version=self.schema_version,
            input_snapshot_hash=_snapshot_hash(snapshot),
            generator_version=GENERATOR_VERSION,
            seed=seed,
        )
        project.prediction_tasks.append(task)
        return task
