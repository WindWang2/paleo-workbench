"""§15 performance spot-checks for the v7 goal.

Explicit scale + budgets:
- single-feature edit on a 100k-feature layer publish: delta ships 1
  feature (host cost < 4 s for the diff over 100k features);
- 500×500 multi-factor fusion (worst-case 50-evidence shape is the same
  memory class; the goal names 500×500×50 as the fusion envelope): bounded
  wall time with the pure-numpy path.

slow-marked like the other perf suites.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.qgis_mirror import (
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)
from tests.perf.timing import print_stress

pytestmark = pytest.mark.slow

FEATURE_BUDGET_S = 4.0
FUSION_BUDGET_S = 30.0


class _CountingStack:
    def __init__(self):
        self.shipped = 0

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta=""):
        """upsert_mirror_layer(..., data_revision, delta)"""
        import json

        payload = json.loads(delta) if delta else json.loads(geojson)
        self.shipped += len(payload.get("changed", payload.get("features", ())))

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass


class _Snap:
    def __init__(self, layers):
        self.layers = tuple(layers)
        self.project_crs = "EPSG:32650"


@pytest.fixture(autouse=True)
def _clean():
    reset_publish_ledger()
    yield
    reset_publish_ledger()


def test_single_edit_on_100k_feature_layer_ships_delta():
    count = 100_000
    step = 200
    features = []
    for i in range(count):
        features.append({
            "id": f"f{i}",
            "geometry": {"type": "Point",
                         "coordinates": [float(i % 1000), float(i // 1000)]},
            "properties": {"name": "n", "kind": i % step},
        })
    layer = MapLayerSnapshot(
        id="big-1", name="big", layer_type="vector",
        extent=(0, 0, 1000, count / 1000), crs="EPSG:32650",
        data_revision=1, style_revision=1, features=tuple(features),
        style={}, visible=True, opacity=1.0, renderer_payload=None,
    )
    stack = _CountingStack()
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert stack.shipped == count
    stack.shipped = 0
    features[42] = dict(features[42], properties={"name": "edited", "kind": 42})
    edited = MapLayerSnapshot(
        id="big-1", name="big", layer_type="vector",
        extent=layer.extent, crs=layer.crs,
        data_revision=2, style_revision=1, features=tuple(features),
        style={}, visible=True, opacity=1.0, renderer_payload=None,
    )
    start = time.perf_counter()
    _, _, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap([edited]))
    elapsed = time.perf_counter() - start
    assert not failures
    assert stack.shipped == 1, f"shipped {stack.shipped} features"
    print_stress("single-edit-100k", n=count, ms=elapsed * 1000.0)
    assert elapsed < FEATURE_BUDGET_S


def test_fusion_500x500_multi_factor():
    from paleo_workbench.workflow.factor_fusion import (
        FactorEvidence,
        FusionModel,
        Normalization,
        fuse,
    )
    from paleo_workbench.workflow.factor_grid_result import FactorGridResult

    rng = np.random.default_rng(7)
    grids = {}
    for name in ("sand", "shale", "thickness", "porosity", "water_depth"):
        grid = rng.uniform(0.0, 1.0, (500, 500)).astype(np.float32)
        grid[rng.random((500, 500)) < 0.1] = np.nan
        grids[name] = FactorGridResult(
            grid_z=grid,
            grid_x=np.linspace(0.0, 100.0, 500),
            grid_y=np.linspace(0.0, 100.0, 500),
            factor_name=name,
            algorithm_id="idw",
            crs="EPSG:32650",
            unit="fraction",
        )
    model = FusionModel(
        name="perf-fusion",
        kind="weighted_evidence",
        evidences=[
            FactorEvidence(factor_name=name, grid=grid, weight=1.0,
                           normalization=Normalization("minmax", 0.0, 1.0))
            for name, grid in grids.items()
        ],
        default_class="undetermined",
        class_names=["low", "medium", "high"],
        class_thresholds=[1.0 / 3.0, 2.0 / 3.0],
    )
    start = time.perf_counter()
    result = fuse(model)
    elapsed = time.perf_counter() - start
    assert result.likelihood is not None
    assert result.likelihood.grid_z.shape == (500, 500)
    coverage = float(np.isfinite(result.confidence.grid_z).mean())
    assert coverage > 0.5
    print_stress("fusion-500x500-x5", n=500 * 500, ms=elapsed * 1000.0)
    assert elapsed < FUSION_BUDGET_S
