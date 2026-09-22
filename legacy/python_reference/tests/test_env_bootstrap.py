"""ISS-ENV-01: geoviz import path bootstrap for source checkouts."""

from __future__ import annotations


def test_ensure_geoviz_on_path_makes_geoviz_importable():
    from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, geoviz_bootstrap_status

    assert ensure_geoviz_on_path() is True
    import geoviz

    assert geoviz is not None
    import geoviz_well_seismic_3d  # noqa: F401 — joint package on bootstrap path

    assert geoviz_well_seismic_3d is not None
    status = geoviz_bootstrap_status()
    assert status["importable"] is True
    assert "requirements-geoviz.txt" in str(status["preferred_install"])


def test_bootstrap_finds_repo_root_with_geoviz_package():
    from paleo_workbench.env_bootstrap import _repo_root

    root = _repo_root()
    assert root is not None
    assert (root / "geo-viz-engine" / "geoviz" / "__init__.py").is_file()


def test_bootstrap_relative_paths_match_pytest_pythonpath():
    """Keep bootstrap package list aligned with pyproject pytest.pythonpath."""
    from paleo_workbench.env_bootstrap import _GEOVIZ_RELATIVE_PATHS

    expected = {
        "geo-viz-engine/packages/geoviz_common",
        "geo-viz-engine/packages/geoviz_paleo_map",
        "geo-viz-engine/packages/geoviz_plots",
        "geo-viz-engine/packages/geoviz_seismic",
        "geo-viz-engine/packages/geoviz_well_log",
        "geo-viz-engine/packages/geoviz_cross_well",
        "geo-viz-engine/packages/geoviz_well_tie",
        "geo-viz-engine/packages/geoviz_well_seismic_3d",
        "geo-viz-engine/packages/geoviz_map",
    }
    assert set(_GEOVIZ_RELATIVE_PATHS) == expected
    assert "geo-viz-engine" not in _GEOVIZ_RELATIVE_PATHS


def test_bootstrap_skips_engine_root_when_stale_so_present(tmp_path, monkeypatch):
    """#627: a committed .so at the engine root must not go on sys.path."""
    import sys

    from paleo_workbench import env_bootstrap as boot

    engine = tmp_path / "geo-viz-engine"
    (engine / "geoviz").mkdir(parents=True)
    (engine / "geoviz" / "__init__.py").write_text("", encoding="utf-8")
    (engine / "stale.cpython-313-x86_64-linux-gnu.so").write_bytes(b"x")
    monkeypatch.setattr(boot, "_repo_root", lambda: tmp_path)
    inserted = str(engine)
    try:
        boot.ensure_geoviz_on_path()
        assert inserted not in sys.path
    finally:
        if inserted in sys.path:
            sys.path.remove(inserted)


def test_load_local_env_reads_ignored_dotenv_without_overriding_real_environment(
    tmp_path, monkeypatch
):
    from paleo_workbench import env_bootstrap as boot

    (tmp_path / ".env").write_text(
        "PALEO_GEOVIZ_API_KEY=ak_from_dotenv\nPALEO_GEOVIZ_MODEL_VERSION_ID=local-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(boot, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(boot, "_LOCAL_ENV_LOADED", False)
    monkeypatch.delenv("PALEO_GEOVIZ_API_KEY", raising=False)
    monkeypatch.setenv("PALEO_GEOVIZ_MODEL_VERSION_ID", "shell-model")

    assert boot.load_local_env() is True
    assert boot.os.environ["PALEO_GEOVIZ_API_KEY"] == "ak_from_dotenv"
    assert boot.os.environ["PALEO_GEOVIZ_MODEL_VERSION_ID"] == "shell-model"


def test_repo_root_resolves_via_paleo_repo_root_env(tmp_path, monkeypatch):
    """#1191: _repo_root resolves via PALEO_REPO_ROOT env var."""
    from paleo_workbench import env_bootstrap as boot

    mock_engine = tmp_path / "geo-viz-engine" / "geoviz"
    mock_engine.mkdir(parents=True)
    (mock_engine / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("PALEO_REPO_ROOT", str(tmp_path))
    assert boot._repo_root() == tmp_path


def test_check_geoviz_subpackages_returns_status_map():
    """#1191: check_geoviz_subpackages reports status of all 9 subpackages."""
    from paleo_workbench.env_bootstrap import (
        _GEOVIZ_PACKAGES,
        check_geoviz_subpackages,
        geoviz_bootstrap_status,
    )

    status = check_geoviz_subpackages()
    assert isinstance(status, dict)
    for pkg in _GEOVIZ_PACKAGES:
        assert pkg in status
        assert isinstance(status[pkg], bool)

    boot_status = geoviz_bootstrap_status()
    assert "subpackages" in boot_status
    assert "missing_subpackages" in boot_status

