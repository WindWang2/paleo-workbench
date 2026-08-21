"""Style revision + mirror reuse through the host snapshot path (bridge).

Pins the revision contract: editing the authoritative qgis_style payload must
bump style_revision, re-apply styles in place on live mirrors (no feature
rebuild), and leave pan/zoom free of any rebuild work.
"""

from __future__ import annotations

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

from paleo_workbench.mapping import (
    map_document_snapshot as snapshot_module,
)
from paleo_workbench.mapping.map_authoring import MapAuthoringDocument
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.mapping.qgis_style import migrate_legacy_style


def _document() -> MapAuthoringDocument:
    return MapAuthoringDocument(
        document_id="doc",
        project_crs="EPSG:3857",
        records=[
            {
                "id": "f1",
                "kind": "facies",
                "name": "basin",
                "facies": "sandstone",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "properties": {},
            }
        ],
    )


def test_applying_payload_bumps_style_revision() -> None:
    document = _document()
    layer = document.layer("facies")
    before = snapshot_module._stable_revision(layer.style)
    migrated = migrate_legacy_style({"fill": "#ff8800", "stroke": "#000000"}, "Polygon")
    assert migrated is not None
    layer.style["qgis_style"] = migrated.to_dict()
    after = snapshot_module._stable_revision(layer.style)
    assert before != after


def test_backend_reuses_feature_payload_across_style_edits(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:  # pragma: no cover - guarded by module skip
        pytest.skip(QGIS_SKIP_REASON)
    backend.initialize()
    try:
        backend.set_extent((0.0, 0.0, 10.0, 10.0))
        migrated = migrate_legacy_style({"fill": "#6c8ebf"}, "Polygon")
        features = (
            {
                "id": "f1",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [5, 0], [5, 5], [0, 0]]]},
                "properties": {"lithology": "sand"},
            },
        )
        base = {
            "id": "facies",
            "name": "Facies",
            "layer_type": "vector",
            "extent": (0.0, 0.0, 10.0, 10.0),
            "crs": "EPSG:3857",
            "data_revision": 1,
            "style_revision": 1,
            "features": features,
        }
        first = MapLayerSnapshot(style={"fill": "#6c8ebf"}, **base)
        second = MapLayerSnapshot(
            **{**base, "style_revision": 2, "style": {"qgis_style": migrated.to_dict()}}
        )
        backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(first,)))
        backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(second,)))
        diagnostics = backend.native_encoding_diagnostics()
        # The layer payload was encoded once and reused across the style edit.
        assert diagnostics["feature_encoding_cache_misses"] == 1
        assert diagnostics["feature_encoding_cache_hits"] >= 1
    finally:
        backend.shutdown()
