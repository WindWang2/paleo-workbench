"""Toolbar labels must map preview-voxel indices through downsample factor."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()


def test_preview_to_survey_coords_applies_ds_factor():
    from geoviz_seismic.seismic_view import SeismicView

    # Minimal stand-in: only the fields _preview_to_survey_coords reads
    view = SeismicView.__new__(SeismicView)
    view._ds_factor = (6, 4, 8)
    view._meta = SimpleNamespace(
        iline_start=4165,
        iline_step=1,
        xline_start=1315,
        xline_step=1,
        t0_ms=0.0,
        dt_ms=2.0,
    )
    view._renderer_3d = SimpleNamespace(_il_pos=64, _xl_pos=51, _t_pos=75)

    il, xl, t_ms = view._preview_to_survey_coords("inline", 64)
    assert il == 4165 + 64 * 6
    assert xl == 1315 + 51 * 4

    il, xl, t_ms = view._preview_to_survey_coords("crossline", 51)
    assert xl == 1315 + 51 * 4
    assert il == 4165 + 64 * 6

    il, xl, t_ms = view._preview_to_survey_coords("time", 75)
    assert t_ms == 75 * 8 * 2.0  # sample * ft * dt → 1200 ms


def test_preview_to_survey_coords_identity_when_no_downsample():
    from geoviz_seismic.seismic_view import SeismicView

    view = SeismicView.__new__(SeismicView)
    view._ds_factor = (1, 1, 1)
    view._meta = SimpleNamespace(
        iline_start=100,
        iline_step=1,
        xline_start=200,
        xline_step=1,
        t0_ms=0.0,
        dt_ms=4.0,
    )
    view._renderer_3d = SimpleNamespace(_il_pos=10, _xl_pos=20, _t_pos=30)

    il, xl, t_ms = view._preview_to_survey_coords("inline", 10)
    assert il == 110 and xl == 220
    _, _, t_ms = view._preview_to_survey_coords("time", 30)
    assert t_ms == 120.0
