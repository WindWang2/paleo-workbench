"""V10 M-A：qgis_runtime 包（发现/加载/proj 数据/健康面）——host-side。

桥缺席（本套件默认环境）时这些测试钉死「诚实降级」：unavailable 报告
原因，绝不把探测不到的能力报告成健康。桥在场时的真值面由 qgis-marked
的 tests/test_qgis_v10_runtime_foundation.py 覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paleo_workbench.qgis_runtime import loader, paths, proj_data
from paleo_workbench.qgis_runtime.health import (
    QgisRuntimeStatus,
    probe_qgis_runtime,
    reset_runtime_probe_cache,
)


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    reset_runtime_probe_cache()
    yield
    reset_runtime_probe_cache()


def test_paths_resolution_honors_env_overrides(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    (vendor / "output" / "bin").mkdir(parents=True)
    monkeypatch.setenv("PALEO_QGIS_BUILD_DIR", str(vendor))
    resolved = paths.resolve_runtime_paths()
    assert resolved.vendor_root == vendor
    assert resolved.vendor_bin == vendor / "output" / "bin"
    assert resolved.vendor_proj_data == vendor / "output" / "share" / "proj"


def test_paths_missing_vendor_is_none(monkeypatch):
    monkeypatch.delenv("PALEO_QGIS_BUILD_DIR", raising=False)
    # repo-relative default 在干净环境不存在时诚实 None（不虚构路径）
    resolved = paths.resolve_runtime_paths()
    if resolved.vendor_root is not None:
        pytest.skip("repo-relative vendor present on this machine")
    assert resolved.vendor_bin is None


def test_deps_prefix_has_no_machine_specific_absolute_path():
    """deps 前缀默认值不得含开发者本机绝对路径（#1263）。

    旧实现 ``C:\\Users\\<developer>\\paleo-qgis-deps`` 只在作者机器上成立：
    换机/换账号时静默返回 None，真实病因（deps 前缀缺失）被掩盖成"桥不可
    导入"。本测试把"生产路径真源不含用户目录字面量"钉死。
    """
    import inspect

    source = inspect.getsource(paths)
    for marker in ("C:\\Users", "C:/Users", "/home/", "/Users/"):
        assert marker not in source, f"paths.py 含机器相关路径字面量: {marker}"


def test_deps_prefix_falls_back_to_repo_relative_convention(monkeypatch, tmp_path):
    """无 env override 时走仓库内 build/qgis-deps 约定（不在则 None + 警告）。"""
    monkeypatch.delenv("PALEO_QGIS_DEPS_DIR", raising=False)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    assert paths.deps_prefix() is None  # 干净目录：诚实 None
    deps = tmp_path.joinpath(*paths._DEPS_BUILD_SUBDIR)
    deps.mkdir(parents=True)
    assert paths.deps_prefix() == deps



def test_recipe_selection_env(monkeypatch):
    monkeypatch.delenv("PALEO_QGIS_CONDA_QT", raising=False)
    assert loader.resolve_recipe() is loader.LoadRecipe.VENDOR
    monkeypatch.setenv("PALEO_QGIS_CONDA_QT", "1")
    assert loader.resolve_recipe() is loader.LoadRecipe.CONDA_QT


def test_loader_report_is_honest_without_vendor(monkeypatch, tmp_path):
    monkeypatch.delenv("PALEO_QGIS_BUILD_DIR", raising=False)
    report = loader.prepare_bridge_load(force=True)
    if report.paths.vendor_bin is None:
        assert any("PALEO_QGIS_BUILD_DIR" in w for w in report.warnings)
    assert report.prepared is True  # idempotent、不抛


def test_proj_data_deploys_from_deps_into_vendor(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    (vendor / "output" / "bin").mkdir(parents=True)
    deps = tmp_path / "deps" / "Library"
    (deps / "share" / "proj").mkdir(parents=True)
    (deps / "share" / "proj" / "proj.db").write_bytes(b"projdb")
    monkeypatch.setenv("PALEO_QGIS_BUILD_DIR", str(vendor))
    monkeypatch.setenv("PALEO_QGIS_DEPS_DIR", str(tmp_path / "deps"))
    resolved = paths.resolve_runtime_paths()
    found, source = proj_data.locate_proj_db(resolved)
    assert found is not None and source == "deps"
    report = proj_data.ensure_proj_data(resolved, recipe=loader.LoadRecipe.VENDOR)
    assert report.deployed is True
    deployed = vendor / "output" / "share" / "proj" / "proj.db"
    assert deployed.read_bytes() == b"projdb"
    # 第二次：vendor-relative 已可达，不再部署
    again = proj_data.ensure_proj_data(resolved, recipe=loader.LoadRecipe.VENDOR)
    assert again.deployed is False
    assert again.source == "vendor-relative"


def test_proj_data_deploy_can_be_disabled(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    (vendor / "output" / "bin").mkdir(parents=True)
    deps = tmp_path / "deps" / "Library"
    (deps / "share" / "proj").mkdir(parents=True)
    (deps / "share" / "proj" / "proj.db").write_bytes(b"projdb")
    monkeypatch.setenv("PALEO_QGIS_BUILD_DIR", str(vendor))
    monkeypatch.setenv("PALEO_QGIS_DEPS_DIR", str(tmp_path / "deps"))
    monkeypatch.setenv("PALEO_QGIS_PROVISION_PROJ", "0")
    resolved = paths.resolve_runtime_paths()
    report = proj_data.ensure_proj_data(resolved, recipe=loader.LoadRecipe.VENDOR)
    assert report.deployed is False
    assert not (vendor / "output" / "share" / "proj" / "proj.db").exists()


def test_health_without_bridge_reports_unavailable_with_reasons(monkeypatch):
    # 强制加载报告指向空目录 → 桥不可导入 → unavailable + 原因，不抛
    monkeypatch.setattr(loader, "_PREPARED", True)
    status = probe_qgis_runtime()
    if status.qgis_available:
        pytest.skip("bridge importable in this environment")
    assert isinstance(status, QgisRuntimeStatus)
    assert status.unavailable_reasons
    assert any("qgis_render_bridge" in r for r in status.unavailable_reasons)
    assert status.canvas_crs_available is False
    assert status.recipe  # 报告使用了哪个配方


def test_health_status_dict_roundtrip_shape():
    status = QgisRuntimeStatus(qgis_available=False, recipe="vendor")
    data = status.as_dict()
    for key in (
        "qgis_available", "qgis_version", "bridge_version", "proj_available",
        "proj_db_path", "gdal_available", "provider_count", "providers",
        "crs_probes", "canvas_crs_available", "transform_available",
        "snapping_available", "topology_available", "degraded_reasons",
        "unavailable_reasons",
    ):
        assert key in data
    import json

    json.dumps(data)  # UI 可序列化消费


def test_crs_chain_runtime_capable_fails_safe_without_bridge():
    # 无桥环境：runtime_crs_capable() 必须是 False（不虚构能力）——
    # digitize 守卫因此保持 V9「未知不比对」语义。
    try:
        import qgis_render_bridge  # noqa: F401
        pytest.skip("bridge importable in this environment")
    except ImportError:
        pass
    from paleo_workbench.mapping import crs_chain as chain

    assert chain.runtime_crs_capable() is False


# -- #1262：探针失败必须降级到 canvas roundtrip --------------------------------

def test_runtime_facts_failure_yields_none_for_fallback():
    """探针抛异常 → None（可降级），而不是真值 dict（永不降级）。

    旧实现返回 ``{"runtime_facts_error": ...}``，而调用方判定 ``is None``
    → 文档承诺的"探针失败降级走 canvas roundtrip"这一支永不成立。
    """
    from paleo_workbench.qgis_runtime import health

    class _Boom:
        def runtime_facts(self):
            raise RuntimeError("nope")

    assert health._probe_via_runtime_facts(_Boom()) is None


def test_runtime_facts_absent_yields_none():
    from paleo_workbench.qgis_runtime import health

    class _Legacy:
        pass

    assert health._probe_via_runtime_facts(_Legacy()) is None


def test_canvas_roundtrip_reports_transform_available(qapp):
    """roundtrip 路径真探测 transform_available（不再恒 False，#1262）。"""
    from paleo_workbench.qgis_runtime import health

    class _Stack:
        def __init__(self):
            self.crs = ""

        def create_canvas(self):
            return 1

        def destroy_canvas(self, addr):
            return None

        def set_destination_crs(self, addr, authid):
            self.crs = authid

        def canvas_destination_crs(self, addr):
            return self.crs

    facts = health._probe_via_canvas_roundtrip(_Stack())
    assert facts is not None
    assert facts["transform_available"] is True
    assert set(facts["crs_probes"]) == set(health.KEY_CRS_PROBES)

    class _Broken(_Stack):
        def set_destination_crs(self, addr, authid):
            raise RuntimeError("no crs authority")

    broken = health._probe_via_canvas_roundtrip(_Broken())
    assert broken is not None
    assert broken["transform_available"] is False
    assert set(broken["crs_probes"].values()) == {False}


def test_canvas_roundtrip_skipped_without_qapplication(monkeypatch):
    """无 QApplication（headless CLI）→ None：降级诚实，不伪造事实。"""
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.qgis_runtime import health

    monkeypatch.setattr(
        QApplication, "instance", staticmethod(lambda: None))
    assert health._probe_via_canvas_roundtrip(object()) is None

