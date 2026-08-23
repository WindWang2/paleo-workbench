"""Host-side QGIS geometry encoding cache tests (bridge not required)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from paleo_workbench.mapping import map_render_backend as backend_module
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)


def _snapshot(*, data_revision: int = 1, style_revision: int = 1) -> MapRenderSnapshot:
    features = tuple(
        {
            "id": f"point-{index}",
            "geometry": {"type": "Point", "coordinates": [float(index), float(index % 7)]},
            "properties": {"group": str(index % 3)},
        }
        for index in range(100)
    )
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="points",
                name="Points",
                layer_type="vector",
                extent=(0.0, 0.0, 100.0, 10.0),
                crs="EPSG:3857",
                data_revision=data_revision,
                style_revision=style_revision,
                features=features,
                style={"fill": "#55b6ff"},
            ),
        ),
    )


def test_style_only_snapshot_reuses_encoded_geometry(monkeypatch) -> None:
    calls = 0
    original = backend_module._geometry_to_wkt

    def counted(geometry):
        nonlocal calls
        calls += 1
        return original(geometry)

    monkeypatch.setattr(backend_module, "_geometry_to_wkt", counted)
    backend = QgisMapRenderBackend()
    cache = backend._vector_feature_payloads
    initial = _snapshot()
    first = backend_module._qgis_snapshot(
        initial, vector_feature_payloads=cache, encoding_stats=backend
    )
    assert calls == 100

    styled_layer = replace(
        initial.layers[0], style_revision=2, style={"fill": "#e03131"}
    )
    styled = backend_module._qgis_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(styled_layer,)),
        vector_feature_payloads=cache,
        encoding_stats=backend,
    )

    assert calls == 100
    assert styled[0]["features"] is first[0]["features"]
    assert backend.native_encoding_diagnostics() == {
        "cached_vector_layers": 1,
        "feature_encoding_cache_hits": 1,
        "feature_encoding_cache_misses": 1,
        "feature_payload_reuse_hits": 0,
        "feature_payload_reencode_misses": 100,
    }


def test_single_feature_data_edit_reencodes_only_that_feature(monkeypatch) -> None:
    calls = 0
    original = backend_module._geometry_to_wkt

    def counted(geometry):
        nonlocal calls
        calls += 1
        return original(geometry)

    monkeypatch.setattr(backend_module, "_geometry_to_wkt", counted)
    backend = QgisMapRenderBackend()
    cache = backend._vector_feature_payloads
    first = _snapshot()
    backend_module._qgis_snapshot(
        first,
        vector_feature_payloads=cache,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
    )
    changed_feature = dict(first.layers[0].features[0])
    changed_feature["geometry"] = {"type": "Point", "coordinates": [999.0, 999.0]}
    changed_layer = replace(
        first.layers[0],
        data_revision=2,
        features=(changed_feature, *first.layers[0].features[1:]),
    )
    backend_module._qgis_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(changed_layer,)),
        vector_feature_payloads=cache,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
    )

    assert calls == 101
    assert backend.native_encoding_diagnostics()["feature_encoding_cache_misses"] == 2
    assert backend.native_encoding_diagnostics()["feature_payload_reuse_hits"] == 99


# --------------------------------------------------------------------------- #
# #932 — incremental feature-delta shipping
# --------------------------------------------------------------------------- #


def _mutate(snapshot: MapRenderSnapshot) -> MapRenderSnapshot:
    """One moved vertex on point-1, one removed (point-50), one added."""
    layer = snapshot.layers[0]
    features = []
    for feature in layer.features:
        fid = feature["id"]
        if fid == "point-50":
            continue
        if fid == "point-1":
            features.append(
                {
                    "id": fid,
                    "geometry": {"type": "Point", "coordinates": [999.0, 999.0]},
                    "properties": feature["properties"],
                }
            )
            continue
        features.append(feature)
    features.append(
        {
            "id": "point-new",
            "geometry": {"type": "Point", "coordinates": [42.0, 42.0]},
            "properties": {"group": "new"},
        }
    )
    return MapRenderSnapshot(
        project_crs=snapshot.project_crs,
        layers=(
            replace(
                layer,
                features=tuple(features),
                data_revision=layer.data_revision + 1,
            ),
        ),
    )


def test_single_feature_edit_ships_delta_not_full_payload() -> None:
    """#932: a single-feature edit must not re-ship the layer's features."""
    backend = QgisMapRenderBackend()
    shipped: dict[str, int] = {}

    first = backend_module._qgis_snapshot(
        _snapshot(data_revision=1),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
        shipped_revisions=shipped,
    )
    assert len(first[0]["features"]) == 100
    shipped["points"] = 1  # mirror holds revision 1

    edited = backend_module._qgis_snapshot(
        _mutate(_snapshot(data_revision=1)),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
        shipped_revisions=shipped,
    )
    layer = edited[0]
    assert "delta" in layer, "single-feature edit did not ship a delta"
    delta = layer["delta"]
    assert layer["features"] == ()
    assert delta["base_revision"] == 1
    changed_ids = {f["id"] for f in delta["changed_features"]}
    assert changed_ids == {"point-1", "point-new"}
    assert delta["removed_ids"] == ["point-50"]
    # The full payload stays cached for future full reships.
    assert len(backend._vector_feature_payloads["points"][1]) == 100
    assert backend._feature_delta_ships == 1


def test_delta_skipped_when_mirror_base_unknown() -> None:
    """No shipped-revision record (fresh process) ⇒ full ship, no delta."""
    backend = QgisMapRenderBackend()
    backend_module._qgis_snapshot(
        _snapshot(data_revision=1),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
    )
    edited = backend_module._qgis_snapshot(
        _mutate(_snapshot(data_revision=1)),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
        shipped_revisions={},
    )
    assert "delta" not in edited[0]
    assert len(edited[0]["features"]) == 100


def test_force_full_overrides_delta() -> None:
    backend = QgisMapRenderBackend()
    shipped = {"points": 1}
    backend_module._qgis_snapshot(
        _snapshot(data_revision=1),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
        shipped_revisions=shipped,
    )
    edited = backend_module._qgis_snapshot(
        _mutate(_snapshot(data_revision=1)),
        vector_feature_payloads=backend._vector_feature_payloads,
        vector_feature_entries=backend._vector_feature_entries,
        encoding_stats=backend,
        shipped_revisions=shipped,
        force_full_ids={"points"},
    )
    assert "delta" not in edited[0]
    assert len(edited[0]["features"]) == 100


def test_set_native_snapshot_recovers_from_stale_delta() -> None:
    """A stale-mirror error from the bridge triggers one full reship (#932)."""
    backend = QgisMapRenderBackend()

    class FakeBridge:
        def __init__(self):
            self.calls = []

        def set_layer_snapshot(self, layers, crs):
            self.calls.append([dict(layer) for layer in layers])
            if any("delta" in layer for layer in self.calls[-1]):
                raise RuntimeError("stale mirror for feature delta on layer points")

    bridge = FakeBridge()
    backend._bridge = bridge
    snapshot = _snapshot(data_revision=1)
    backend._set_native_snapshot(snapshot)
    backend._set_native_snapshot(_mutate(snapshot))
    assert len(bridge.calls) == 3  # full, delta (rejected), full retry
    assert "delta" in bridge.calls[1][0]
    assert "delta" not in bridge.calls[2][0]
    assert len(bridge.calls[2][0]["features"]) == 100
    assert backend._qgis_shipped_revisions["points"] == 2


@pytest.mark.qgis
def test_feature_delta_updates_mirror_in_place_on_qgis_path():
    """#932 (bridge integration): a single-feature edit updates the live QGIS
    mirror via the delta channel — no full re-parse, correct final geometry."""
    import numpy as np
    import pytest

    from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend

    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("bridge not built")
    backend.initialize()
    try:
        base = _snapshot(data_revision=1)
        backend.set_layer_snapshot(base)
        edited = _mutate(base)
        backend.set_layer_snapshot(edited)
        diagnostics = backend._bridge.diagnostics()
        assert diagnostics["feature_deltas"] == 1, diagnostics
        assert diagnostics["delta_changed_features"] == 2  # moved + added
        assert diagnostics["delta_removed_features"] == 1
        # The mirror now holds the edited feature set: render and probe the
        # moved point location (999, 999) for ink where the old (1, 1) was not.
        frame = backend._bridge.render_sync((0.0, 0.0, 1000.0, 1000.0), 200, 200, 96.0)
        arr = np.frombuffer(frame["rgba"], dtype=np.uint8).reshape(200, 200, 4)
        x = int(999.0 / 1000.0 * 199)
        y = int((1000.0 - 999.0) / 1000.0 * 199)
        window = arr[max(0, y - 6):y + 6, max(0, x - 6):x + 6]
        assert int((window[..., 3] > 0).sum()) > 0, "moved vertex not rendered"
    finally:
        backend.shutdown()
