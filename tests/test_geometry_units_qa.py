"""V6 §15 — CRS-unit honesty for polygon areas / contour lengths (P0-10)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.geological_pipeline.geometry_units import (
    area_unit_label,
    is_geographic_crs,
    polyline_length_with_unit,
    ring_area_with_unit,
)


class TestCrsClassification:
    def test_geographic_detected(self):
        assert is_geographic_crs("EPSG:4326")
        assert is_geographic_crs("WGS84")

    def test_projected_not_geographic(self):
        assert not is_geographic_crs("EPSG:32650")
        assert not is_geographic_crs("EPSG:4547")

    def test_empty_is_not_geographic_but_labels_unknown(self):
        assert not is_geographic_crs("")
        assert is_geographic_crs(None) is False
        assert area_unit_label(None) == "unknown-unit²"


class TestRingAreaUnits:
    def test_projected_keeps_crs_units(self):
        ring = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        area, unit, warning = ring_area_with_unit(ring, "EPSG:32650")
        assert area == pytest.approx(10_000.0)
        assert "32650" in unit
        assert warning is None

    def test_geographic_converts_to_approx_metres_with_warning(self):
        # 0.01° × 0.01° at the equator ≈ (1113.2 m)² ≈ 1.24e6 m²
        ring = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01), (0.0, 0.0)]
        area, unit, warning = ring_area_with_unit(ring, "EPSG:4326")
        assert area == pytest.approx(1_239_200.0, rel=0.02)
        assert "≈m²" in unit
        assert warning and "geographic" in warning

    def test_geographic_at_high_latitude_shrinks(self):
        ring = [(0.0, 60.0), (0.01, 60.0), (0.01, 60.01), (0.0, 60.01), (0.0, 60.0)]
        area, _unit, _w = ring_area_with_unit(ring, "EPSG:4326")
        equator = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01), (0.0, 0.0)]
        area_eq, _u, _w2 = ring_area_with_unit(equator, "EPSG:4326")
        assert area == pytest.approx(area_eq * np.cos(np.radians(60.0)), rel=0.01)

    def test_unknown_crs_labels_unknown(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
        area, unit, warning = ring_area_with_unit(ring, "")
        assert area == pytest.approx(100.0)
        assert unit == "unknown-unit²"
        assert warning and "undeclared" in warning


class TestPolylineLength:
    def test_projected_units(self):
        length, unit, warning = polyline_length_with_unit(
            [(0.0, 0.0), (30.0, 40.0)], "EPSG:32650"
        )
        assert length == pytest.approx(50.0)
        assert warning is None

    def test_geographic_approx_metres(self):
        length, unit, warning = polyline_length_with_unit(
            [(0.0, 0.0), (0.01, 0.0)], "EPSG:4326"
        )
        assert length == pytest.approx(1113.2, rel=0.01)
        assert "≈m" in unit
        assert warning


class TestPolygonizationQc:
    def _grid(self, crs: str):
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        n = 12
        zz = np.full((n, n), 0.5)
        zz[: 6] = 0.2
        # geographic CRS ⇒ coordinates are DEGREES (0..10), not metres
        span = 10.0 if is_geographic_crs(crs) else 1000.0
        return FactorGridResult(
            factor_name="砂岩含量",
            algorithm_id="idw",
            grid_x=np.linspace(0, span, n),
            grid_y=np.linspace(0, span, n),
            grid_z=zz,
            crs=crs,
            unit="1",
        )

    def test_qc_records_thresholds_and_area_unit(self):
        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )

        layer = generate_facies_polygon_layer(self._grid("EPSG:32650"))
        qc = layer.metadata["polygon_qc"]
        assert qc["thresholds_source"] == "data_derived_default"
        assert len(qc["thresholds"]) == 2
        assert qc["area_unit"].startswith("EPSG:32650")
        assert "nodata_cells" in qc and "total_cells" in qc

    def test_features_carry_area_unit(self):
        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )

        layer = generate_facies_polygon_layer(self._grid("EPSG:32650"))
        props = layer.features[0]["properties"]
        assert "area_unit" in props

    def test_geographic_crs_warns(self):
        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )

        layer = generate_facies_polygon_layer(self._grid("EPSG:4326"))
        qc = layer.metadata["polygon_qc"]
        assert any("geographic" in w for w in qc.get("area_warnings", []))
        props = layer.features[0]["properties"]
        # raw deg² stays (conservation) + an explicitly-labelled approximation
        assert props["area_unit"] == "deg²"
        assert "area_approx_m2" in props and props["area_approx_m2"] > 0
