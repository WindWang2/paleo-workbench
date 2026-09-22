"""Deep-audit regressions (2026-08-14): mapping interaction, render backend,
interpretation lifecycle, and the mapping-page action-state source of truth."""

from __future__ import annotations

import sys
import types

import pytest

from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


# --- F12: polygon holes use even-odd semantics -----------------------------------


def _layer_with_hole() -> VectorLayer:
    return VectorLayer(
        id="polys",
        name="Polys",
        features=[
            VectorFeature(
                "donut",
                {
                    "type": "Polygon",
                    "coordinates": [
                        # Outer ring 0..10, hole 4..6.
                        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
                    ],
                },
            ),
            VectorFeature(
                "other",
                {
                    "type": "Polygon",
                    "coordinates": [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
                },
            ),
        ],
    )


def test_identify_excludes_points_inside_polygon_hole() -> None:
    index = FeatureSpatialIndex(_layer_with_hole())

    # Inside the outer ring, inside the hole → NOT inside the feature.
    assert index.identify((5, 5), tolerance=0.0) is None
    # Body of the donut (inside outer, outside hole) → hit.
    assert index.identify((2, 5), tolerance=0.0) == "donut"
    assert index.identify((8, 8), tolerance=0.0) == "donut"
    # Unrelated polygon still identifies.
    assert index.identify((25, 5), tolerance=0.0) == "other"


def test_identify_hole_boundary_still_hits_feature() -> None:
    index = FeatureSpatialIndex(_layer_with_hole())

    # The hole ring is still feature boundary geometry: a click on it (within
    # tolerance) must identify the polygon, not fall through.
    assert index.identify((5.0, 4.05), tolerance=0.5) == "donut"


# --- F13: snapshot set before the QGIS bridge exists must not be dropped ----------


class _StubBridge:
    """Minimal stand-in for the optional native qgis_render_bridge."""

    version = "stub"

    def __init__(self) -> None:
        self.render_active = False
        self.snapshots: list[tuple[list, str]] = []
        self.render_requests: list[int] = []
        self._pending_frame: dict | None = None

    def initialize(self) -> None:
        pass

    def set_layer_snapshot(self, layers, crs) -> None:
        self.snapshots.append((list(layers), crs))

    def request_render(self, extent, width, height, dpi, generation) -> None:
        self.render_requests.append(int(generation))
        self._pending_frame = {
            "generation": int(generation),
            "width": int(width),
            "height": int(height),
            "stride": int(width) * 4,
            "rgba": bytes([200, 40, 40] * (int(width) * int(height))),
            "render_ms": 0.5,
        }

    def take_completed_frame(self):
        frame = self._pending_frame
        self._pending_frame = None
        return frame

    def render_sync(self, extent, width, height, dpi):
        return {
            "generation": 1,
            "width": int(width),
            "height": int(height),
            "stride": int(width) * 4,
            "rgba": bytes([200, 40, 40] * (int(width) * int(height))),
            "render_ms": 0.5,
        }

    def cancel_render(self) -> None:
        self._pending_frame = None

    def shutdown(self) -> None:
        pass


@pytest.fixture()
def stub_qgis_bridge(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "qgis_render_bridge", types.SimpleNamespace(QgisRenderBridge=_StubBridge)
    )
    return _StubBridge


def _vector_snapshot() -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="facies",
                name="Facies",
                layer_type="vector",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "facies-1",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[2.0, 2.0], [18.0, 2.0], [18.0, 18.0], [2.0, 18.0], [2.0, 2.0]]
                            ],
                        },
                        "properties": {"facies": "shoreface"},
                    },
                ),
                style={"fill": "#d9a441", "stroke": "#593d16"},
            ),
        ),
    )


def test_qgis_backend_delivers_snapshot_set_before_initialize(stub_qgis_bridge) -> None:
    backend = QgisMapRenderBackend()
    assert backend.is_available

    # Snapshot arrives before initialize()/request_render() created the bridge.
    backend.set_layer_snapshot(_vector_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(64, 48)
    backend.set_dpi(96.0)

    generation = backend.request_render()
    try:
        frame = backend.take_completed_frame()
        assert frame is not None, "async path must not render a blank stale frame"
        assert frame.generation == generation
        bridge = backend._bridge
        assert bridge is not None
        # The pending snapshot reached the native bridge before the render call.
        assert bridge.snapshots, "snapshot set pre-initialize was silently dropped"
        assert len(bridge.snapshots[0][0]) == 1
        assert bridge.snapshots[0][1] == "EPSG:3857"
        assert bridge.render_requests
    finally:
        backend.shutdown()


def test_qgis_backend_redelivers_snapshot_after_shutdown(stub_qgis_bridge) -> None:
    backend = QgisMapRenderBackend()
    backend.initialize()
    backend.shutdown()

    # Reuse after shutdown: bridge is gone, snapshot must queue again.
    backend.set_layer_snapshot(_vector_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(32, 32)

    generation = backend.request_render()
    try:
        frame = backend.take_completed_frame()
        assert frame is not None
        assert frame.generation == generation
        assert backend._bridge is not None
        assert backend._bridge.snapshots, "snapshot after shutdown was silently dropped"
    finally:
        backend.shutdown()


# --- F14: classify_stale semantics unchanged by the dead-code removal ------------


def test_classify_stale_semantics_after_dead_code_removal():
    from paleo_workbench.project.models import HorizonInterpretationRef
    from paleo_workbench.viz.interpretation_lifecycle import classify_stale

    ref = HorizonInterpretationRef(
        id="i1",
        name="Top H2",
        horizon_key="H2",
        vertical_domain="time",
        source_version_ids=["src_a"],
    )
    assert classify_stale(ref, current_source_version_ids=["src_a"]) == "current"
    assert classify_stale(ref, current_source_version_ids=["src_b"]) == "stale"
    assert classify_stale(ref, current_vertical_domain="depth") == "stale"
    assert classify_stale(ref) == "current"
    # The CRS kwarg stays accepted; drift is not classifiable from the ref.
    assert classify_stale(ref, current_crs="EPSG:32650") == "current"


# --- F18: _sync_action_state counts session-only polygons ------------------------


def test_sync_action_state_counts_session_only_selected_polygons(qtbot):
    from paleo_workbench.project.models import PaleoMapDocument
    from paleo_workbench.ui.pages.mapping_page import MappingPage

    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-merge", name="Merge Map", linked_target_horizon="H1")
    page.update_state([document], project_crs="EPSG:3857")

    authoring = page._authoring_document
    assert authoring is not None
    layer = authoring.active_layer
    session = layer.start_editing()
    polygons = (
        VectorFeature(
            "p1",
            {"type": "Polygon", "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]},
        ),
        VectorFeature(
            "p2",
            {"type": "Polygon", "coordinates": [[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]},
        ),
    )
    for feature in polygons:
        session.add_feature(feature)
    # Selection follows the edit session's working set, so both polygons are
    # selectable even though neither is committed to the layer store yet.
    layer.set_selection(("p1", "p2"))
    assert layer.selection == {"p1", "p2"}

    page._sync_action_state()

    # merge_selected_polygons operates on the session; the gate must see both.
    assert page.action_controller.actions["merge"].isEnabled()
    assert page.action_controller.actions["split"].isEnabled()
    assert page.action_controller.actions["delete_selected"].isEnabled()
