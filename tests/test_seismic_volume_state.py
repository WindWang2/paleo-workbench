"""Unit tests for SeismicVolumeState observer & coordinate mapping (Ticket 01)."""

from __future__ import annotations

import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_seismic.models import BinGridGeometry
from paleo_workbench.viz.seismic_volume_state import SeismicVolumeState


def test_seismic_volume_state_slice_navigation():
    state = SeismicVolumeState(
        inline_range=(100, 500),
        crossline_range=(200, 800),
        sample_range=(0, 1000),
    )

    assert state.inline_idx == 100
    assert state.crossline_idx == 200
    assert state.sample_idx == 0

    seen_events: list[tuple[int, int, int]] = []
    state.slice_changed.connect(lambda il, xl, z: seen_events.append((il, xl, z)))

    state.set_slice(inline=250, crossline=400, sample=500)

    assert state.inline_idx == 250
    assert state.crossline_idx == 400
    assert state.sample_idx == 500
    assert seen_events == [(250, 400, 500)]


def test_seismic_volume_state_coordinate_conversion():
    geom = BinGridGeometry(
        x_origin=500000.0,
        y_origin=3000000.0,
        il_azimuth_deg=0.0,
        il_spacing_m=25.0,
        xl_spacing_m=25.0,
    )
    state = SeismicVolumeState(geometry=geom)

    # Convert IL=10, XL=20 to world Easting/Northing
    east, north = state.grid_to_geographic(10.0, 20.0)
    assert east == pytest.approx(500500.0)
    assert north == pytest.approx(3000250.0)

    # Convert back from Geographic to Grid
    il, xl = state.geographic_to_grid(east, north)
    assert il == pytest.approx(10.0)
    assert xl == pytest.approx(20.0)


def test_seismic_volume_state_deep_interface():
    state = SeismicVolumeState(
        inline_range=(0, 100),
        crossline_range=(0, 100),
        sample_range=(0, 100),
    )

    seen: list[tuple[int, int, int]] = []
    state.slice_changed.connect(lambda il, xl, z: seen.append((il, xl, z)))

    # Test sync_slice method (2-Method interface)
    state.sync_slice(axis=0, index=50)
    state.sync_slice(axis=1, index=60)
    state.sync_slice(axis=2, index=70)

    assert state.inline_idx == 50
    assert state.crossline_idx == 60
    assert state.t_slice_idx == 70
    assert seen[-1] == (50, 60, 70)

    # Test convert_coord 2-Method interface
    east, north = state.convert_coord(10.0, 20.0, mode="grid_to_geo")
    assert east == pytest.approx(500500.0)
    assert north == pytest.approx(3000250.0)

    il, xl = state.convert_coord(east, north, mode="geo_to_grid")
    assert il == pytest.approx(10.0)
    assert xl == pytest.approx(20.0)
