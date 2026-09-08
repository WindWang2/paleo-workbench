"""Scalar DATA mirrors (v7 §5): FactorGridResult → single-band float32
GeoTIFF for real QGIS raster rendering.

Keyed by data_revision ONLY — restyling must never rewrite scientific
values.  GDAL-dependent tests skip without osgeo (same policy as the RGBA
mirror); classification/style logic is pure numpy and always runs.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.scalar_data_mirror import (
    ScalarDataMirror,
    scalar_data_mirror_ready,
)
from paleo_workbench.mapping.scalar_style import (
    ScalarStyleSpec,
    classify_breaks,
    equal_interval_breaks,
    natural_breaks,
    quantile_breaks,
    ramp_items_for_spec,
)

GRID = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
GRID_NODATA = np.array([[0.0, np.nan], [2.0, 3.0]], dtype=np.float32)


def _gdal_available() -> bool:
    try:
        from osgeo import gdal  # noqa: F401

        return True
    except ImportError:
        return False


def _read_band(band, width: int, height: int):
    """Read a float32 band without the optional _gdal_array bridge."""
    import numpy as np
    from osgeo import gdal

    raw = band.ReadRaster(0, 0, width, height, buf_type=gdal.GDT_Float32)
    return np.frombuffer(raw, dtype=np.float32).reshape(height, width)


# ---------------------------------------------------------------------------
# Style spec (pure, always runs)


def test_style_spec_defaults_and_validation():
    spec = ScalarStyleSpec(ramp_name="viridis")
    assert spec.mode == "continuous"
    assert spec.opacity == 1.0
    assert spec.reverse is False
    with pytest.raises(ValueError):
        ScalarStyleSpec(mode="nonsense")
    with pytest.raises(ValueError):
        ScalarStyleSpec(classification="nonsense")
    with pytest.raises(ValueError):
        ScalarStyleSpec(n_classes=1)


def test_equal_interval_breaks():
    breaks, labels = equal_interval_breaks(0.0, 10.0, n=5)
    assert breaks == pytest.approx([0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
    assert len(labels) == 6  # n classes → n+1 bin edges


def test_quantile_breaks_from_values():
    values = np.linspace(0.0, 100.0, 101)
    breaks, _labels = quantile_breaks(values, n=4)
    assert breaks[0] == pytest.approx(0.0)
    assert breaks[-1] == pytest.approx(100.0)
    assert len(breaks) == 5


def test_natural_breaks_monotone():
    rng = np.random.default_rng(42)
    values = np.concatenate([rng.normal(0, 1, 200), rng.normal(50, 1, 200)])
    breaks, _labels = natural_breaks(values, n=3, sample=400)
    # well-separated bimodal data legitimately collapses to fewer classes;
    # the contract is monotone edges spanning [min, max].
    assert len(breaks) >= 2
    assert all(b <= nb for b, nb in zip(breaks, breaks[1:]))
    assert breaks[0] == pytest.approx(float(values.min()), abs=1.0)
    assert breaks[-1] == pytest.approx(float(values.max()), abs=1.0)


def test_classify_breaks_dispatch_and_explicit():
    spec = ScalarStyleSpec(classification="explicit", explicit_breaks=[0, 1, 2, 3])
    breaks, _ = classify_breaks(spec, values=GRID.ravel(), vmin=0.0, vmax=3.0)
    assert breaks == pytest.approx([0, 1, 2, 3])
    spec_eq = ScalarStyleSpec(classification="equal_interval", n_classes=3)
    breaks, _ = classify_breaks(spec_eq, values=GRID.ravel(), vmin=0.0, vmax=3.0)
    assert breaks == pytest.approx([0.0, 1.0, 2.0, 3.0])


def test_manual_range_overrides_stats():
    spec = ScalarStyleSpec(manual_range=(0.5, 2.5))
    breaks, _ = classify_breaks(
        spec, values=GRID.ravel(), vmin=0.0, vmax=3.0, n=2)
    assert breaks[0] == pytest.approx(0.5)
    assert breaks[-1] == pytest.approx(2.5)


def test_ramp_items_continuous_and_classified_reverse():
    from paleo_workbench.mapping.color_ramps import get_color_ramp

    ramp = get_color_ramp("viridis")
    spec = ScalarStyleSpec(ramp_name="viridis")
    items = ramp_items_for_spec(spec, ramp, (0.0, 10.0), mode="continuous")
    assert items and items[0]["value"] == pytest.approx(0.0)
    assert items[-1]["value"] == pytest.approx(10.0)
    assert all(len(item["color"]) == 3 for item in items)

    reversed_spec = ScalarStyleSpec(ramp_name="viridis", reverse=True)
    straight = ramp_items_for_spec(spec, ramp, (0.0, 10.0), mode="continuous")
    flipped = ramp_items_for_spec(reversed_spec, ramp, (0.0, 10.0), mode="continuous")
    assert flipped[0]["color"] == straight[-1]["color"]
    assert flipped[-1]["color"] == straight[0]["color"]

    classified = ramp_items_for_spec(spec, ramp, (0.0, 10.0), mode="classified",
                                     breaks=[0.0, 5.0, 10.0])
    assert classified[0]["value"] == pytest.approx(0.0)


def test_spec_serialization_roundtrip():
    spec = ScalarStyleSpec(
        ramp_name="water_depth", mode="classified",
        classification="quantile", n_classes=6, reverse=True, opacity=0.8,
        manual_range=(1.0, 9.0), unit_label="m",
    )
    data = spec.to_dict()
    restored = ScalarStyleSpec.from_dict(data)
    assert restored == spec


# ---------------------------------------------------------------------------
# Data mirror (GDAL-gated)


def test_mirror_ready_probe_honest():
    status = scalar_data_mirror_ready()
    assert set(status) >= {"gdal", "reason"}
    assert status["gdal"] == _gdal_available()


@pytest.mark.skipif(not _gdal_available(), reason="requires osgeo.gdal")
def test_data_mirror_writes_float32_with_nodata():
    mirror = ScalarDataMirror()
    source = mirror.ensure(
        layer_id="factor-1", grid=GRID, extent=(0.0, 0.0, 2.0, 2.0),
        crs="EPSG:32650", data_revision=3,
    )
    try:
        from osgeo import gdal

        dataset = gdal.Open(source)
        assert dataset is not None
        assert dataset.RasterCount == 1
        band = dataset.GetRasterBand(1)
        assert band.DataType == gdal.GDT_Float32
        nodata = band.GetNoDataValue()
        assert nodata is not None and np.isnan(nodata)
        array = _read_band(band, 2, 2)
        assert array.dtype == np.float32
        np.testing.assert_allclose(array, GRID)
        gt = dataset.GetGeoTransform()
        assert gt[0] == pytest.approx(0.0)
        assert gt[3] == pytest.approx(2.0)
        assert gt[1] == pytest.approx(1.0)
        assert gt[5] == pytest.approx(-1.0)
        assert "UTM ZONE 50N" in (dataset.GetProjection() or "").upper() or \
            "32650" in dataset.GetProjection()
    finally:
        mirror.clear()


@pytest.mark.skipif(not _gdal_available(), reason="requires osgeo.gdal")
def test_data_mirror_keyed_by_data_revision_only():
    mirror = ScalarDataMirror()
    first = mirror.ensure("factor-1", GRID, (0, 0, 2, 2), None, data_revision=1)
    again = mirror.ensure("factor-1", GRID, (0, 0, 2, 2), None, data_revision=1)
    assert first == again  # style-agnostic reuse
    changed = mirror.ensure("factor-1", GRID * 2, (0, 0, 2, 2), None, data_revision=2)
    assert changed != first
    assert mirror.materialization_count == 2
    mirror.clear()


@pytest.mark.skipif(not _gdal_available(), reason="requires osgeo.gdal")
def test_data_mirror_preserves_nan_nodata():
    mirror = ScalarDataMirror()
    source = mirror.ensure("factor-2", GRID_NODATA, (0, 0, 2, 2), None, 1)
    try:
        from osgeo import gdal

        dataset = gdal.Open(source)
        array = _read_band(dataset.GetRasterBand(1), 2, 2)
        dataset = None
        assert np.isnan(array[0, 1])
        assert array[0, 0] == pytest.approx(0.0)
    finally:
        mirror.clear()


@pytest.mark.skipif(not _gdal_available(), reason="requires osgeo.gdal")
def test_data_mirror_rejects_bad_extent():
    mirror = ScalarDataMirror()
    with pytest.raises(ValueError):
        mirror.ensure("factor-3", GRID, (1, 1, 0, 2), None, 1)  # xmax < xmin
    mirror.clear()
