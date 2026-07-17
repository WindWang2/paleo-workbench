"""ISS-ENV-01: geoviz import path bootstrap for source checkouts."""

from __future__ import annotations


def test_ensure_geoviz_on_path_makes_geoviz_importable():
    from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, geoviz_bootstrap_status

    assert ensure_geoviz_on_path() is True
    import geoviz

    assert geoviz is not None
    status = geoviz_bootstrap_status()
    assert status["importable"] is True
    assert "requirements-geoviz.txt" in str(status["preferred_install"])


def test_bootstrap_finds_repo_root_with_geoviz_package():
    from paleo_workbench.env_bootstrap import _repo_root

    root = _repo_root()
    assert root is not None
    assert (root / "geo-viz-engine" / "geoviz" / "__init__.py").is_file()


def test_bootstrap_relative_paths_match_pytest_pythonpath():
    """Keep bootstrap path list aligned with pyproject pytest.pythonpath."""
    from paleo_workbench.env_bootstrap import _GEOVIZ_RELATIVE_PATHS

    expected = {
        "geo-viz-engine",
        "geo-viz-engine/packages/geoviz_common",
        "geo-viz-engine/packages/geoviz_paleo_map",
        "geo-viz-engine/packages/geoviz_plots",
        "geo-viz-engine/packages/geoviz_seismic",
        "geo-viz-engine/packages/geoviz_well_log",
        "geo-viz-engine/packages/geoviz_cross_well",
        "geo-viz-engine/packages/geoviz_well_tie",
        "geo-viz-engine/packages/geoviz_map",
    }
    assert set(_GEOVIZ_RELATIVE_PATHS) == expected
