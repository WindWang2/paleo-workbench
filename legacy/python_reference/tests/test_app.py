"""Health/status API must report the installed package, not scaffold literals."""

from __future__ import annotations

import importlib.metadata

from src.api.routes import get_health_status, get_system_info


def _expected_version() -> str:
    try:
        return importlib.metadata.version("paleo-workbench")
    except importlib.metadata.PackageNotFoundError:
        from paleo_workbench import __version__

        return __version__


def test_health():
    res = get_health_status()
    assert res["status"] == "healthy"
    assert res["service"] == "paleo-workbench"
    assert res["branch"]


def test_health_branch_comes_from_env(monkeypatch):
    monkeypatch.setenv("PALEO_WORKBENCH_BRANCH", "fix/p3-s7")
    res = get_health_status()
    assert res["branch"] == "fix/p3-s7"


def test_system_info():
    info = get_system_info()
    assert info["version"] == _expected_version()
    assert info["version"] != "1.0.0"
