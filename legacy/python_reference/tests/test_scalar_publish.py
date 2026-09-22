"""Scalar publish payload tests (v7 §5) — pure Python with fakes.

The bridge-dependent renderer round-trip is covered by qgis-marked tests
(test_scalar_qgis_roundtrip.py) once the bridge is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

import paleo_workbench.mapping.qgis_mirror as qgis_mirror
from paleo_workbench.mapping import scalar_publish
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.qgis_mirror import mirror_snapshot_to_stack
from paleo_workbench.mapping.scalar_data_mirror import ScalarDataMirror
from paleo_workbench.mapping.scalar_publish import (
    raster_source_qgis_payload,
    scalar_spec_from_layer_style,
)
from paleo_workbench.mapping.scalar_style import ScalarStyleSpec


class _FakeScalar:
    """Stands in for the native ScalarGridLayer (exposes grid_array)."""

    def __init__(self, grid):
        self._grid = np.asarray(grid, dtype=np.float32)

    def grid_array(self):
        return self._grid

    def rasterize(self):  # RGBA fallback interface
        h, w = self._grid.shape
        return np.zeros((h, w, 4), dtype=np.uint8)


@dataclass
class _Snap:
    project_crs: str = "EPSG:32650"
    layers: tuple = ()


def _scalar_layer(grid=None, style=None, revision=1):
    grid = grid if grid is not None else np.array(
        [[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
    return MapLayerSnapshot(
        id="factor-1", name="砂地比", layer_type="scalar_grid",
        extent=(0.0, 0.0, 2.0, 2.0), crs="EPSG:32650",
        data_revision=revision, style_revision=revision,
        features=(), style=style or {}, visible=True, opacity=1.0,
        renderer_payload=_FakeScalar(grid),
    )


def test_spec_from_layer_style_nested_and_legacy():
    nested = {"scalar_style": {"ramp_name": "water_depth", "mode": "classified",
                               "classification": "quantile", "n_classes": 4}}
    spec = scalar_spec_from_layer_style(nested)
    assert spec.ramp_name == "water_depth"
    assert spec.mode == "classified"

    legacy = {"color_ramp": "warm_cool", "color_range": [1.0, 9.0]}
    spec = scalar_spec_from_layer_style(legacy)
    assert spec.ramp_name == "coolwarm"
    assert spec.manual_range == (1.0, 9.0)
    assert spec.mode == "continuous"


def test_build_payload_unavailable_without_bridge(monkeypatch):
    """No bridge ⇒ None (caller falls back to RGBA) — never fake success."""
    layer = _scalar_layer()
    monkeypatch.setattr(
        scalar_publish, "scalar_style_pipeline_ready",
        lambda: {"ready": False, "bridge": False, "gdal": True,
                 "reason": "bridge missing"})
    assert scalar_publish.build_scalar_qgis_payload(layer, ScalarDataMirror()) is None


def test_build_payload_unavailable_without_grid_getter():
    import dataclasses

    layer = dataclasses.replace(_scalar_layer(), renderer_payload=object())
    from unittest.mock import patch

    with patch.object(scalar_publish, "scalar_style_pipeline_ready",
                      return_value={"ready": True, "bridge": True, "gdal": True,
                                    "reason": ""}):
        assert scalar_publish.build_scalar_qgis_payload(
            layer, ScalarDataMirror()) is None


def test_raster_source_payload_passthrough():
    layer = MapLayerSnapshot(
        id="ref-1", name="basemap", layer_type="raster_source",
        extent=(0, 0, 1, 1), crs="", data_revision=1, style_revision=1,
        features=(), style={}, visible=True, opacity=1.0,
        renderer_payload="D:/data/basemap.tif",
    )
    payload = raster_source_qgis_payload(layer)
    assert payload["source_path"] == "D:/data/basemap.tif"
    assert payload["renderer_xml"] == ""

    empty = MapLayerSnapshot(
        id="ref-2", name="x", layer_type="raster_source", extent=(0, 0, 1, 1),
        crs="", data_revision=1, style_revision=1, features=(), style={},
        visible=True, opacity=1.0, renderer_payload="",
    )
    assert raster_source_qgis_payload(empty) is None


class _RecordingStack:
    """Fake QgisMapStack capturing mirror calls."""

    def __init__(self):
        self.raster_upserts = []
        self.vector_upserts = 0
        self.removed_except = None
        self.order = None
        self.refreshed = 0

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_raster_mirror_layer(self, doc_id, name, source_path, crs,
                                   renderer_xml, visible, opacity,
                                   is_reference=False):
        self.raster_upserts.append((doc_id, name, source_path, renderer_xml))
        return f"qgis-{doc_id}"

    def upsert_mirror_layer(self, *args, **kwargs):
        self.vector_upserts += 1
        return "qgis-vec"

    def remove_mirror_layers_except(self, seen):
        self.removed_except = list(seen)

    def set_mirror_layer_order(self, order):
        self.order = list(order)

    def refresh_canvas(self, canvas):
        self.refreshed += 1


def test_mirror_snapshot_skips_scalar_when_pipeline_unavailable(monkeypatch):
    """Scalar layer without the data pipeline: honest failure entry, layer
    NOT silently dropped from the seen list bookkeeping."""
    layer = _scalar_layer()
    monkeypatch.setattr(qgis_mirror, "_scalar_data_cache", lambda: None)
    stack = _RecordingStack()
    _, seen, failures = mirror_snapshot_to_stack(
        stack, 0x1, _Snap(layers=(layer,)))
    assert seen == []
    assert failures and "unavailable" in failures[0]
    assert stack.raster_upserts == []


def test_mirror_snapshot_raster_source_upserts(monkeypatch):
    layer = MapLayerSnapshot(
        id="ref-1", name="basemap", layer_type="raster_source",
        extent=(0, 0, 1, 1), crs="EPSG:4326", data_revision=1,
        style_revision=1, features=(), style={}, visible=True, opacity=0.7,
        renderer_payload="D:/data/basemap.tif",
    )
    stack = _RecordingStack()
    _, seen, _ = mirror_snapshot_to_stack(stack, 0x1, _Snap(layers=(layer,)))
    assert seen == ["ref-1"]
    assert stack.raster_upserts[0][2] == "D:/data/basemap.tif"
    assert stack.removed_except == ["ref-1"]


def test_scalar_spec_roundtrip_preserved_in_style():
    spec = ScalarStyleSpec(ramp_name="porosity", mode="classified",
                           classification="natural_breaks", n_classes=6)
    restored = ScalarStyleSpec.from_dict(spec.to_dict())
    assert restored == spec
