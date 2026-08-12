"""Host-side QGIS geometry encoding cache tests (bridge not required)."""

from __future__ import annotations

from dataclasses import replace

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
