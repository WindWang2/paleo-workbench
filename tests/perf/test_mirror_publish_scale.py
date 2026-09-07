"""§9 mirror-publish benchmarks: 50 / 200 / 500 / 1000 layers.

Goal §9/§15: no-op publish ≈ O(changed items); a single-feature edit ships
one feature, not the layer's full collection; style-only and visibility-only
changes never re-ship feature payloads.  Explicit budgets below are the
acceptance bars for this goal on this class of machine (host-side timing;
the native apply cost is exercised by the qgis-marked suite).

slow-marked (like the other perf suites): opt out of fast CI selections.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.qgis_mirror import (
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)
from tests.perf.timing import print_stress

pytestmark = pytest.mark.slow

LAYERS_BUDGET_MS = {50: 60.0, 200: 240.0, 500: 700.0, 1000: 1600.0}
NOOP_BUDGET_MS = {50: 8.0, 200: 30.0, 500: 80.0, 1000: 180.0}
FEATURES_PER_LAYER = 40


class _CountingStack:
    """Fake stack counting shipped features (host-side payload cost)."""

    def __init__(self):
        self.shipped_features = 0
        self.upserts = 0

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta=""):
        """upsert_mirror_layer(..., data_revision, delta)"""
        self.upserts += 1
        payload = json.loads(delta) if delta else json.loads(geojson)
        if "features" in payload:
            self.shipped_features += len(payload["features"])
        else:
            self.shipped_features += len(payload.get("changed", ()))

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass


def _layer(index: int, revision: int = 1, feature_count: int = FEATURES_PER_LAYER,
           mutated_feature: int | None = None) -> MapLayerSnapshot:
    features = []
    for f in range(feature_count):
        name = "mutated" if f == mutated_feature else "f"
        features.append({
            "id": f"f{index}_{f}",
            "geometry": {"type": "Point", "coordinates": [float(f), float(index % 7)]},
            "properties": {"name": name},
        })
    return MapLayerSnapshot(
        id=f"layer-{index}", name=f"L{index}", layer_type="vector",
        extent=(0, 0, 100, 100), crs="EPSG:32650",
        data_revision=revision, style_revision=1,
        features=tuple(features), style={}, visible=True, opacity=1.0,
        renderer_payload=None,
    )


class _Snap:
    def __init__(self, layers):
        self.layers = tuple(layers)
        self.project_crs = "EPSG:32650"


@pytest.fixture(autouse=True)
def _clean_ledger():
    reset_publish_ledger()
    yield
    reset_publish_ledger()


@pytest.mark.parametrize("count", sorted(LAYERS_BUDGET_MS))
def test_full_first_publish_within_budget(count):
    import time

    stack = _CountingStack()
    layers = [_layer(i) for i in range(count)]
    start = time.perf_counter()
    _, seen, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert not failures and len(seen) == count
    assert stack.shipped_features == count * FEATURES_PER_LAYER
    print_stress("mirror-full-publish", n=count, ms=elapsed_ms)
    assert elapsed_ms < LAYERS_BUDGET_MS[count], (
        f"full publish of {count} layers took {elapsed_ms:.1f} ms "
        f"(budget {LAYERS_BUDGET_MS[count]} ms)")


@pytest.mark.parametrize("count", sorted(NOOP_BUDGET_MS))
def test_noop_publish_within_budget(count):
    import time

    stack = _CountingStack()
    layers = [_layer(i) for i in range(count)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    shipped_before = stack.shipped_features
    start = time.perf_counter()
    _, seen, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert not failures and len(seen) == count
    assert stack.shipped_features == shipped_before  # nothing re-shipped
    print_stress("mirror-noop-publish", n=count, ms=elapsed_ms)
    assert elapsed_ms < NOOP_BUDGET_MS[count], (
        f"no-op publish of {count} layers took {elapsed_ms:.1f} ms "
        f"(budget {NOOP_BUDGET_MS[count]} ms)")


@pytest.mark.parametrize("count", sorted(LAYERS_BUDGET_MS))
def test_single_feature_edit_ships_one_feature(count):
    stack = _CountingStack()
    layers = [_layer(i) for i in range(count)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    stack.shipped_features = 0
    # ONE layer gets one edited feature at a new revision
    layers[3] = _layer(3, revision=2, mutated_feature=11)
    _, _, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    assert not failures
    assert stack.shipped_features == 1, (
        f"single-feature edit shipped {stack.shipped_features} features"
    )


def test_style_only_change_ships_no_features():
    stack = _CountingStack()
    layers = [_layer(i) for i in range(200)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    stack.shipped_features = 0
    restyled = []
    for index, layer in enumerate(layers):
        style = {"fill": "#ff0000"} if index == 5 else {}
        restyled.append(MapLayerSnapshot(
            id=layer.id, name=layer.name, layer_type=layer.layer_type,
            extent=layer.extent, crs=layer.crs,
            data_revision=layer.data_revision,
            style_revision=layer.style_revision + 1,
            features=layer.features, style=style,
            visible=layer.visible, opacity=layer.opacity,
            renderer_payload=None,
        ))
    _, _, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap(restyled))
    assert not failures
    # style change on layer 5: the ledger style token differs ⇒ that layer
    # re-ships (style is applied via the upsert), all others ship nothing.
    assert stack.shipped_features == FEATURES_PER_LAYER


def test_visibility_only_change_ships_no_features():
    stack = _CountingStack()
    layers = [_layer(i) for i in range(500)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap(layers))
    stack.shipped_features = 0
    flipped = [
        MapLayerSnapshot(
            id=layer.id, name=layer.name, layer_type=layer.layer_type,
            extent=layer.extent, crs=layer.crs,
            data_revision=layer.data_revision,
            style_revision=layer.style_revision,
            features=layer.features, style=layer.style,
            visible=(index != 10), opacity=layer.opacity,
            renderer_payload=None,
        )
        for index, layer in enumerate(layers)
    ]
    _, _, failures = mirror_snapshot_to_stack(stack, 0x1, _Snap(flipped))
    assert not failures
    # Only the visibility-flipped layer re-ships (flags ride the upsert);
    # every other layer must not re-ship its payload.
    assert stack.shipped_features == FEATURES_PER_LAYER
