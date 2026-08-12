from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from paleo_workbench.project.models import FactorMapTask, ProjectDocument


GENERATOR_VERSION = "mock-factor-v1"


def resolve_default_target_horizon(project: ProjectDocument) -> str:
    """Consumer hook: stratigraphy → correlation framework → horizon key."""
    from paleo_workbench.workflow.correlation_lifecycle import (
        resolve_correlation_target_horizon,
    )

    return resolve_correlation_target_horizon(project)


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_mock_factor_map(
    project: ProjectDocument,
    target_horizon: str,
    factor_type: str,
    seed: int,
) -> FactorMapTask:
    # Prefer selected correlation/horizon identity when caller passes empty horizon.
    horizon = (target_horizon or "").strip() or resolve_default_target_horizon(project)
    target_horizon = horizon
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
