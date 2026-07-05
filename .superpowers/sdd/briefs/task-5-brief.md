### Task 5: Deterministic Factor Map And Prediction Mock Services

**Files:**
- Create: `paleo_workbench/workflow/factors.py`
- Create: `paleo_workbench/prediction/__init__.py`
- Create: `paleo_workbench/prediction/adapters.py`
- Create: `tests/test_mock_outputs.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `FactorMapTask`, `PredictionTask`
- Produces: `create_mock_factor_map(project, target_horizon, factor_type, seed) -> FactorMapTask`
- Produces: `MockPredictionAdapter.run(project, factor_map_ids, seed) -> PredictionTask`

- [ ] **Step 1: Write failing deterministic mock tests**

Create `tests/test_mock_outputs.py`:

```python
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_mock_factor_map_is_deterministic():
    project_a = ProjectDocument.new("A")
    project_b = ProjectDocument.new("B")

    task_a = create_mock_factor_map(project_a, "ZJ2", "sand_thickness", seed=42)
    task_b = create_mock_factor_map(project_b, "ZJ2", "sand_thickness", seed=42)

    assert task_a.parameters["sample_points"] == task_b.parameters["sample_points"]
    assert task_a.input_snapshot_hash == task_b.input_snapshot_hash
    assert task_a.source_kind == "mock"


def test_mock_prediction_is_deterministic():
    project = ProjectDocument.new("Demo")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    adapter = MockPredictionAdapter()

    first = adapter.run(project, [factor.id], seed=7)
    second = adapter.run(project, [factor.id], seed=7)

    assert first.result_summary == second.result_summary
    assert first.probability_summary == second.probability_summary
    assert first.adapter_schema_version == "1.0"
```

- [ ] **Step 2: Run mock tests to verify they fail**

Run:

```bash
python -m pytest tests/test_mock_outputs.py -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement deterministic factor map service**

Create `paleo_workbench/workflow/factors.py`:

```python
from __future__ import annotations

import hashlib
import json
import random

from paleo_workbench.project.models import FactorMapTask, ProjectDocument


GENERATOR_VERSION = "mock-factor-v1"


def _snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_mock_factor_map(
    project: ProjectDocument,
    target_horizon: str,
    factor_type: str,
    seed: int,
) -> FactorMapTask:
    rng = random.Random(seed)
    sample_points = [
        {
            "well": f"A{i + 1}",
            "x": round(114.0 + rng.random() * 0.3, 6),
            "y": round(22.5 + rng.random() * 0.3, 6),
            "value": round(10.0 + rng.random() * 40.0, 3),
        }
        for i in range(8)
    ]
    snapshot = {
        "target_horizon": target_horizon,
        "factor_type": factor_type,
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "sample_points": sample_points,
    }
    task = FactorMapTask(
        name=f"{target_horizon} {factor_type}",
        target_horizon=target_horizon,
        factor_type=factor_type,
        method="mock",
        parameters={"sample_points": sample_points},
        status="complete",
        source_kind="mock",
        input_snapshot_hash=_snapshot_hash(snapshot),
        generator_version=GENERATOR_VERSION,
        seed=seed,
    )
    project.factor_map_tasks.append(task)
    return task
```

- [ ] **Step 4: Implement mock prediction adapter**

Create `paleo_workbench/prediction/__init__.py`:

```python
from paleo_workbench.prediction.adapters import MockPredictionAdapter

__all__ = ["MockPredictionAdapter"]
```

Create `paleo_workbench/prediction/adapters.py`:

```python
from __future__ import annotations

import hashlib
import json
import random

from paleo_workbench.project.models import PredictionTask, ProjectDocument


GENERATOR_VERSION = "mock-prediction-v1"


def _snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MockPredictionAdapter:
    adapter_kind = "mock"
    schema_version = "1.0"

    def run(self, project: ProjectDocument, factor_map_ids: list[str], seed: int) -> PredictionTask:
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
            adapter_kind="mock",
            input_factor_map_ids=factor_map_ids,
            result_summary={"predicted_regions": predicted},
            probability_summary={"mean_probability": round(sum(p["probability"] for p in predicted) / len(predicted), 3)},
            evidence_contribution=[
                {"name": "sand_thickness", "weight": 0.45},
                {"name": "target_horizon", "weight": 0.30},
                {"name": "neighbor_wells", "weight": 0.25},
            ],
            review_areas=[p for p in predicted if p["probability"] < 0.7],
            status="complete",
            adapter_schema_version=self.schema_version,
            input_snapshot_hash=_snapshot_hash(snapshot),
            generator_version=GENERATOR_VERSION,
            seed=seed,
        )
        project.prediction_tasks.append(task)
        return task
```

- [ ] **Step 5: Run mock output tests**

Run:

```bash
python -m pytest tests/test_mock_outputs.py -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow/factors.py paleo_workbench/prediction tests/test_mock_outputs.py
git commit -m "feat: add deterministic mock factor and prediction services"
```

If root git is still invalid, record checkpoint: `Task 5 complete; root commit pending repository repair`.

---

