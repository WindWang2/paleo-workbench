"""Deprecated path: survey builders live in geoviz facade (package independence)."""

from __future__ import annotations

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz import horizon_corners_from_dat, survey_corners_from_segy  # noqa: E402

__all__ = ["horizon_corners_from_dat", "survey_corners_from_segy"]
