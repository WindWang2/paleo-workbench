"""Tests for SeismicVolumeSource zero-dimension and corrupt SEGY validation barriers (Issue #999)."""

from pathlib import Path
import pytest
from paleo_workbench.viz.seismic_volume_source import (
    SeismicVolumeSource,
    SeismicVolumeMetadata,
    preview_strides,
)


def test_seismic_volume_metadata_validity_properties():
    """Metadata is_valid and is_empty properties correctly check dimensions."""
    valid_meta = SeismicVolumeMetadata(
        path="fake.sgy",
        source_id="id1",
        n_inlines=10,
        n_crosslines=10,
        n_samples=50,
        sample_interval_ms=4.0,
        iline_start=1,
        iline_step=1,
        xline_start=1,
        xline_step=1,
        t0_ms=0.0,
        has_geometry=True,
    )
    assert valid_meta.is_valid is True
    assert valid_meta.is_empty is False

    empty_meta = SeismicVolumeMetadata(
        path="fake.sgy",
        source_id="id2",
        n_inlines=0,
        n_crosslines=0,
        n_samples=0,
        sample_interval_ms=4.0,
        iline_start=1,
        iline_step=1,
        xline_start=1,
        xline_step=1,
        t0_ms=0.0,
        has_geometry=False,
    )
    assert empty_meta.is_valid is False
    assert empty_meta.is_empty is True


def test_preview_strides_with_zero_dimensions():
    """preview_strides returns safe (1, 1, 1) when any dimension is <= 0."""
    assert preview_strides(0, 0, 0) == (1, 1, 1)
    assert preview_strides(-5, 10, 10) == (1, 1, 1)
    assert preview_strides(10, 0, 10) == (1, 1, 1)


def test_corrupt_segy_zero_dimension_validation_barrier(tmp_path: Path):
    """Corrupted/zero-dimension SEGY raises ValueError on slice read instead of crashing in C++."""
    corrupt_file = tmp_path / "corrupt_seismic.sgy"
    corrupt_file.write_bytes(b"not-a-valid-segy-file-header-data")

    src = SeismicVolumeSource(corrupt_file)
    meta = src.metadata()
    assert meta.is_empty

    with pytest.raises(ValueError, match="Cannot read slice from empty or corrupt SEGY"):
        src.read_inline(0)

    with pytest.raises(ValueError, match="Cannot read trace from empty or corrupt SEGY"):
        src.read_trace(0, 0)

    vol, warning = src.read_preview()
    assert vol is None

    vol, strides, warning = src.read_lod_volume_with_strides()
    assert vol is None
    assert strides == (1, 1, 1)
