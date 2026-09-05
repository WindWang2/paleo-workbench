"""Installed-state entry point contracts (packaging #440).

Covers the three packaging fixes: (1) a `paleo-workbench` console script and
`paleo_workbench/__main__.py` module entry exist; (2) Qt global state is only
mutated inside main(), not on bare `import paleo_workbench.main`; (3) the
geoviz gate keeps its actionable SystemExit(2) contract from every entry
path — verified with a subprocess against a geoviz-free copy of the package,
deterministically in any checkout state.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_package_ships_module_entry_and_console_script_declaration() -> None:
    assert (REPO_ROOT / "paleo_workbench" / "__main__.py").is_file(), (
        "paleo_workbench/__main__.py must exist for `python -m paleo_workbench`"
    )
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'paleo-workbench = "paleo_workbench.main:main"' in pyproject, (
        "[project.scripts] must register the paleo-workbench console script"
    )


def test_importing_main_does_not_mutate_qt_global_state() -> None:
    """Bare `import paleo_workbench.main` must not change Qt global state."""
    from PySide6.QtGui import QSurfaceFormat

    sentinel = QSurfaceFormat()
    sentinel.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
    sentinel.setVersion(2, 0)
    QSurfaceFormat.setDefaultFormat(sentinel)

    import paleo_workbench.main  # noqa: F401 — must be side-effect free

    current = QSurfaceFormat.defaultFormat()
    assert current.renderableType() == QSurfaceFormat.RenderableType.OpenGLES
    assert current.version() == (2, 0)


def test_main_exits_with_install_guidance_when_geoviz_unavailable(monkeypatch, capsys) -> None:
    import paleo_workbench.main as main_module

    monkeypatch.setattr(
        "paleo_workbench.env_bootstrap.ensure_geoviz_on_path", lambda: False
    )
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "ERROR: cannot import geoviz" in captured.err
    assert "requirements-geoviz.txt" in captured.err


def _geoviz_free_env(tmp_path) -> dict[str, str]:
    env = os.environ.copy()
    # Drop every geoviz/bootstrap source so the entry must fail fast with the
    # SystemExit(2) guidance instead of starting the app.
    for key in ("PYTHONPATH", "PALEO_QGIS_BUILD_DIR", "PALEO_WITH_QGIS_RENDERER"):
        env.pop(key, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Dropping PYTHONPATH is not enough in CI: the geoviz packages are pip
    # installed (editable) into site-packages, so `import geoviz` would still
    # succeed, the gate would pass, and the subprocess would start the GUI
    # event loop and hang until the test times out. Shadow the installed
    # packages with a blocker package that raises ImportError on import —
    # PYTHONPATH precedes site-packages on sys.path, so this reliably makes
    # the subprocess geoviz-free everywhere.
    blocker = tmp_path / "_geoviz_blocker"
    blocker.mkdir(exist_ok=True)
    (blocker / "geoviz.py").write_text(
        'raise ImportError("geoviz blocked by test")\n', encoding="utf-8"
    )
    env["PYTHONPATH"] = str(blocker)
    return env


@pytest.mark.parametrize("command", [["-m", "paleo_workbench"], ["paleo_workbench/main.py"]])
def test_entry_paths_exit_2_with_guidance_without_geoviz(tmp_path, command) -> None:
    """`python -m paleo_workbench` and `python paleo_workbench/main.py` on a
    geoviz-free install must exit 2 with actionable guidance (never a bare
    ModuleNotFoundError from the package layout)."""
    package_copy = tmp_path / "paleo_workbench"
    shutil.copytree(
        REPO_ROOT / "paleo_workbench",
        package_copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    result = subprocess.run(
        [sys.executable, *command],
        cwd=str(tmp_path),
        env=_geoviz_free_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "ERROR: cannot import geoviz" in result.stderr
    assert "requirements-geoviz.txt" in result.stderr


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_entry_point_help_exits_0(flag) -> None:
    """#1191: paleo-workbench --help outputs help without starting GUI."""
    result = subprocess.run(
        [sys.executable, "-m", "paleo_workbench", flag],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "usage: paleo-workbench [OPTIONS]" in result.stdout
    assert "Environment Status:" in result.stdout


def test_entry_point_version_exits_0() -> None:
    """#1191: paleo-workbench --version outputs version and CPython info."""
    result = subprocess.run(
        [sys.executable, "-m", "paleo_workbench", "--version"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "paleo-workbench" in result.stdout
    assert "CPython" in result.stdout


def test_entry_point_diagnostics_exits_0() -> None:
    """#1191: paleo-workbench --diagnostics outputs environment diagnostics."""
    result = subprocess.run(
        [sys.executable, "-m", "paleo_workbench", "--diagnostics"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "=== Paleo Workbench Environment Diagnostics ===" in result.stdout
    assert "Repo Root:" in result.stdout
    assert "GeoViz Core:" in result.stdout

