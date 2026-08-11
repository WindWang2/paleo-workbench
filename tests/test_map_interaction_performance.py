"""Comparative local smoke measurements for the cached vector interaction index."""

from __future__ import annotations

import time

import pytest

from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.mark.parametrize("count", [100, 1_000, 5_000])
def test_vector_interaction_index_warm_queries_reuse_one_revision_cache(count: int) -> None:
    side = int(count**0.5) + 1
    features = [
        VectorFeature(
            f"p-{index}",
            {"type": "Point", "coordinates": [float(index % side), float(index // side)]},
        )
        for index in range(count)
    ]
    layer = VectorLayer(id=f"layer-{count}", name="Points", features=features)
    index = FeatureSpatialIndex(layer)
    probe = (float(side // 2), float(side // 2))

    started = time.perf_counter()
    assert index.identify(probe, tolerance=0.6) is not None
    cold_s = time.perf_counter() - started
    revision = index._revision
    started = time.perf_counter()
    for _ in range(200):
        index.identify(probe, tolerance=0.6)
        index.snap(probe, tolerance=0.6, modes={"vertex"})
    warm_s = time.perf_counter() - started

    assert index._revision == revision
    assert warm_s >= 0.0  # Comparative values are deliberately workstation-local.
    print(
        f"vector index {count}: build+first={cold_s * 1000:.2f}ms "
        f"200 cached identify/snap={warm_s * 1000:.2f}ms"
    )
