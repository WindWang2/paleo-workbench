# Review package: Task 5 (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated from current Task 5 files. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/workflow/factors.py
paleo_workbench/prediction/__init__.py
paleo_workbench/prediction/adapters.py
tests/test_mock_outputs.py

## Implementer report
# Task 5 Report: Deterministic Factor Map And Prediction Mock Services

## Scope

- Implemented `paleo_workbench/workflow/factors.py`
- Implemented `paleo_workbench/prediction/__init__.py`
- Implemented `paleo_workbench/prediction/adapters.py`
- Added `tests/test_mock_outputs.py`

## TDD Evidence

### RED

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py -v
```

Result:

- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.prediction'`

### GREEN

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py -v
```

Result:

- `2 passed in 0.09s`

## Required Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py tests/test_workflow_service.py tests/test_project_models.py tests/test_project_manager.py tests/test_resource_scanner.py -v
```

Result:

- `15 passed in 0.12s`

## Git Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Failed as expected: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded: `Task 5 complete; root commit pending repository repair`

## Self-Review

- Deterministic generators include `seed`, `generator_version`, and `input_snapshot_hash`.
- Mock prediction output is explicitly marked replaceable and non-final.
- Changes are limited to the Task 5 owned files plus this report.

## Commit

- None created, because root git is invalid.


## paleo_workbench/workflow/factors.py
     1	from __future__ import annotations
     2	
     3	import hashlib
     4	import json
     5	import random
     6	from typing import Any
     7	
     8	from paleo_workbench.project.models import FactorMapTask, ProjectDocument
     9	
    10	
    11	GENERATOR_VERSION = "mock-factor-v1"
    12	
    13	
    14	def _snapshot_hash(payload: dict[str, Any]) -> str:
    15	    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    16	    return hashlib.sha256(encoded).hexdigest()
    17	
    18	
    19	def create_mock_factor_map(
    20	    project: ProjectDocument,
    21	    target_horizon: str,
    22	    factor_type: str,
    23	    seed: int,
    24	) -> FactorMapTask:
    25	    rng = random.Random(seed)
    26	    sample_points = [
    27	        {
    28	            "well": f"A{i + 1}",
    29	            "x": round(114.0 + rng.random() * 0.3, 6),
    30	            "y": round(22.5 + rng.random() * 0.3, 6),
    31	            "value": round(10.0 + rng.random() * 40.0, 3),
    32	        }
    33	        for i in range(8)
    34	    ]
    35	    snapshot = {
    36	        "target_horizon": target_horizon,
    37	        "factor_type": factor_type,
    38	        "seed": seed,
    39	        "generator_version": GENERATOR_VERSION,
    40	        "sample_points": sample_points,
    41	    }
    42	    task = FactorMapTask(
    43	        name=f"{target_horizon} {factor_type}",
    44	        target_horizon=target_horizon,
    45	        factor_type=factor_type,
    46	        method="mock",
    47	        parameters={"sample_points": sample_points},
    48	        status="complete",
    49	        source_kind="mock",
    50	        input_snapshot_hash=_snapshot_hash(snapshot),
    51	        generator_version=GENERATOR_VERSION,
    52	        seed=seed,
    53	    )
    54	    project.factor_map_tasks.append(task)
    55	    return task

## paleo_workbench/prediction/__init__.py
     1	from paleo_workbench.prediction.adapters import MockPredictionAdapter
     2	
     3	__all__ = ["MockPredictionAdapter"]

## paleo_workbench/prediction/adapters.py
     1	from __future__ import annotations
     2	
     3	import hashlib
     4	import json
     5	import random
     6	from typing import Any
     7	
     8	from paleo_workbench.project.models import PredictionTask, ProjectDocument
     9	
    10	
    11	GENERATOR_VERSION = "mock-prediction-v1"
    12	
    13	
    14	def _snapshot_hash(payload: dict[str, Any]) -> str:
    15	    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    16	    return hashlib.sha256(encoded).hexdigest()
    17	
    18	
    19	class MockPredictionAdapter:
    20	    adapter_kind = "mock"
    21	    schema_version = "1.0"
    22	
    23	    def run(
    24	        self,
    25	        project: ProjectDocument,
    26	        factor_map_ids: list[str],
    27	        seed: int,
    28	    ) -> PredictionTask:
    29	        rng = random.Random(seed)
    30	        facies = ["三角洲前缘砂体", "水下分流河道砂体", "分流间湾泥", "滨岸砂体"]
    31	        predicted = [
    32	            {
    33	                "region_id": f"mock_region_{i + 1}",
    34	                "facies": facies[i % len(facies)],
    35	                "probability": round(0.55 + rng.random() * 0.35, 3),
    36	            }
    37	            for i in range(4)
    38	        ]
    39	        snapshot = {
    40	            "factor_map_ids": factor_map_ids,
    41	            "seed": seed,
    42	            "generator_version": GENERATOR_VERSION,
    43	            "schema_version": self.schema_version,
    44	        }
    45	        task = PredictionTask(
    46	            name="Mock sedimentary facies prediction",
    47	            adapter_kind=self.adapter_kind,
    48	            input_factor_map_ids=factor_map_ids,
    49	            result_summary={
    50	                "predicted_regions": predicted,
    51	                "is_mock": True,
    52	                "is_replaceable": True,
    53	                "final_scientific_prediction": False,
    54	            },
    55	            probability_summary={
    56	                "mean_probability": round(
    57	                    sum(item["probability"] for item in predicted) / len(predicted),
    58	                    3,
    59	                ),
    60	            },
    61	            evidence_contribution=[
    62	                {"name": "sand_thickness", "weight": 0.45},
    63	                {"name": "target_horizon", "weight": 0.30},
    64	                {"name": "neighbor_wells", "weight": 0.25},
    65	            ],
    66	            review_areas=[item for item in predicted if item["probability"] < 0.7],
    67	            status="complete",
    68	            adapter_schema_version=self.schema_version,
    69	            input_snapshot_hash=_snapshot_hash(snapshot),
    70	            generator_version=GENERATOR_VERSION,
    71	            seed=seed,
    72	        )
    73	        project.prediction_tasks.append(task)
    74	        return task

## tests/test_mock_outputs.py
     1	from paleo_workbench.prediction.adapters import MockPredictionAdapter
     2	from paleo_workbench.project.models import ProjectDocument
     3	from paleo_workbench.workflow.factors import create_mock_factor_map
     4	
     5	
     6	def test_mock_factor_map_is_deterministic():
     7	    project_a = ProjectDocument.new("A")
     8	    project_b = ProjectDocument.new("B")
     9	
    10	    task_a = create_mock_factor_map(project_a, "ZJ2", "sand_thickness", seed=42)
    11	    task_b = create_mock_factor_map(project_b, "ZJ2", "sand_thickness", seed=42)
    12	
    13	    assert task_a.parameters["sample_points"] == task_b.parameters["sample_points"]
    14	    assert task_a.input_snapshot_hash == task_b.input_snapshot_hash
    15	    assert task_a.source_kind == "mock"
    16	
    17	
    18	def test_mock_prediction_is_deterministic():
    19	    project = ProjectDocument.new("Demo")
    20	    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    21	    adapter = MockPredictionAdapter()
    22	
    23	    first = adapter.run(project, [factor.id], seed=7)
    24	    second = adapter.run(project, [factor.id], seed=7)
    25	
    26	    assert first.result_summary == second.result_summary
    27	    assert first.probability_summary == second.probability_summary
    28	    assert first.adapter_schema_version == "1.0"
