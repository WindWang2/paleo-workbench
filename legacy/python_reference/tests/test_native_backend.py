"""Tests for NativeEngineBackend deep module interface and seam toggling."""
from __future__ import annotations

import types

import numpy as np
import pytest

from paleo_workbench.native_backend import (
    NativeEngineBackend,
    _NATIVE_MODULES,
    _module_origin,
    _repo_root,
    disabled_acceleration,
    install_all_hooks,
    is_accelerated,
    native_backend,
    native_status,
    native_version,
)


def test_native_backend_singleton_instance():
    assert isinstance(native_backend, NativeEngineBackend)


def test_is_accelerated_reflects_cpp_capability():
    for feature in ["seismic_3d", "well_log", "map_edit"]:
        if native_status(feature) == "fresh":
            assert is_accelerated(feature) is native_backend.has_cpp(feature)
        else:
            assert is_accelerated(feature) is False
    assert is_accelerated("no_such_feature") is False


def test_disabled_acceleration_context_manager():
    # Inside disabled_acceleration block, is_accelerated returns False
    with disabled_acceleration():
        assert is_accelerated("seismic_3d") is False
        assert is_accelerated("well_log") is False
        assert is_accelerated("map_edit") is False

    # Outside block, returns original state (stale repo-root binaries stay gated).
    if native_status("seismic_3d") == "fresh":
        assert is_accelerated("seismic_3d") == native_backend.has_cpp("seismic_3d")
    else:
        assert is_accelerated("seismic_3d") is False


def test_dispatch_fast_slice_extract_parity():
    vol = np.arange(8 * 12 * 16, dtype=np.float32).reshape(8, 12, 16)

    # Accelerated or default path
    slice_accel = native_backend.dispatch("fast_slice_extract", vol, axis=0, index=2)

    # Disabled acceleration path
    with disabled_acceleration():
        slice_py = native_backend.dispatch("fast_slice_extract", vol, axis=0, index=2)

    np.testing.assert_array_equal(slice_accel, slice_py)


def test_dispatch_minmax_downsample_parity():
    # Seeded so rare single-backend NaN/tie-break/overflow inputs stay
    # reproducible (#851).
    rng = np.random.default_rng(1)
    depths = np.linspace(100.0, 500.0, 1000, dtype=np.float32)
    values = rng.standard_normal(1000).astype(np.float32)

    d_acc, v_acc = native_backend.dispatch("minmax_downsample", depths, values, 100)
    with disabled_acceleration():
        d_py, v_py = native_backend.dispatch("minmax_downsample", depths, values, 100)

    np.testing.assert_array_equal(d_acc, d_py)
    np.testing.assert_array_equal(v_acc, v_py)


def test_install_all_hooks_idempotent():
    # Must run cleanly without error; a second pass must leave hooks installed
    # exactly when the geoviz provider API is importable (#622 companion, #851).
    install_all_hooks()
    install_all_hooks()
    try:
        import geoviz  # noqa: F401
    except ImportError:
        assert native_backend.hooks_installed() is False
    else:
        assert native_backend.hooks_installed() is True


def test_install_all_hooks_logs_when_providers_missing(monkeypatch, caplog):
    """#622: missing geoviz hook API must warn, not silently return."""
    import builtins
    import logging

    import paleo_workbench.native_backend as nb

    backend = NativeEngineBackend()
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "geoviz":
            raise ImportError("no hook providers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with caplog.at_level(logging.WARNING, logger="paleo_workbench"):
        backend.install_all_hooks()
    assert backend.hooks_installed() is False
    assert any("hook providers missing" in rec.message for rec in caplog.records)


def _fake_module(origin_dir) -> types.ModuleType:
    mod = types.ModuleType("fake_native_module")
    mod.__file__ = str(origin_dir / "fake_native_module.cpython-313-x86_64-linux-gnu.so")
    return mod


def test_module_origin_classifies_repo_root_binary_as_stale(tmp_path):
    """A module resolving from the repository root is a stale committed binary."""
    repo_root = _repo_root()
    root_binary = _fake_module(repo_root)
    assert _module_origin(root_binary) == "repo_root"


def test_module_origin_classifies_installed_and_missing(tmp_path):
    installed = _fake_module(tmp_path / "site-packages" / "native_pkg")
    assert _module_origin(installed) == "installed"
    assert _module_origin(None) == "missing"


def test_native_status_distinguishes_stale_missing_fresh():
    """native_status must tell 'stale' (repo-root committed binary shadowing a
    fresh build) apart from 'missing'; 'fresh' otherwise (packaging #435)."""
    for feature in ("seismic_3d", "well_log", "map_edit", "grid_render"):
        assert native_status(feature) in {"fresh", "stale", "missing"}
    assert native_status("no_such_feature") == "missing"


def test_dispatch_diverts_stale_repo_root_binary_to_fallback(monkeypatch):
    """#520: a repo-root .so is 'stale'; dispatch must not call it."""
    from paleo_workbench import native_backend as nb_mod

    calls: list[str] = []
    fake = _fake_module(_repo_root())
    fake.fast_slice_extract = lambda *a, **k: calls.append("cpp") or "from-stale-cpp"
    monkeypatch.setitem(_NATIVE_MODULES, "seismic_3d", fake)
    monkeypatch.setitem(
        NativeEngineBackend._FUNCTION_MODULE_MAP,
        "fast_slice_extract",
        ("seismic_3d", fake),
    )
    if hasattr(nb_mod, "_STALE_WARNED"):
        monkeypatch.setattr(nb_mod, "_STALE_WARNED", set())

    backend = NativeEngineBackend()
    monkeypatch.setattr(backend, "has_cpp", lambda feature: True)

    vol = np.zeros((2, 3, 4), dtype=np.float32)
    with pytest.warns(UserWarning, match="stale repo-root"):
        out = backend.dispatch("fast_slice_extract", vol, 0, 1)

    assert calls == []
    assert native_status("seismic_3d") == "stale"
    assert backend.is_accelerated("seismic_3d") is False
    np.testing.assert_array_equal(out, vol[1])


def test_native_version_is_string_or_none():
    """Native modules must expose __version__ when freshly built; the API must
    never raise for stale committed binaries or missing modules."""
    for feature in ("seismic_3d", "well_log", "map_edit", "grid_render"):
        version = native_version(feature)
        assert version is None or isinstance(version, str)
    assert native_version("no_such_feature") is None


def test_install_all_hooks_registers_cpp_providers():
    """install_all_hooks() twice must wire the geoviz provider hooks and stay clean."""
    try:
        from geoviz import (
            get_downsample_provider,
            get_isosurface_extractor,
            get_las_parser_provider,
            set_downsample_provider,
            set_isosurface_extractor,
            set_las_parser_provider,
        )
    except ImportError:
        pytest.skip("geoviz not importable in this environment")

    from paleo_workbench.native_backend import _cpp_las_parser_provider, _cpp_minmax_provider

    prev = (
        get_downsample_provider(),
        get_isosurface_extractor(),
        get_las_parser_provider(),
    )
    try:
        install_all_hooks()
        install_all_hooks()
        assert get_downsample_provider() is _cpp_minmax_provider
        assert get_las_parser_provider() is _cpp_las_parser_provider
        assert get_isosurface_extractor() is not None
        assert native_backend.hooks_installed() is True
    finally:
        set_downsample_provider(prev[0])
        set_isosurface_extractor(prev[1])
        set_las_parser_provider(prev[2])


def test_map_edit_core_version_and_acceleration():
    """Verify map_edit_core exports version 0.2.17a0 and is recognized as accelerated."""
    import map_edit_core
    assert hasattr(map_edit_core, "__version__")
    assert map_edit_core.__version__ == "0.2.17a0"
    assert native_version("map_edit") == "0.2.17a0"
    assert native_status("map_edit") == "fresh"
    assert is_accelerated("map_edit") is True


def test_map_edit_core_hit_test_and_snap_parity():
    """Verify snap_point and validate_ring produce identical results between C++ and pure-Python fallback."""
    # Snap test
    candidates = [(0.0, 0.0), (10.0, 10.0), (20.0, 20.0)]
    snap_acc = native_backend.dispatch("snap_point", candidates, 9.8, 10.1, 0.5)
    with disabled_acceleration():
        snap_py = native_backend.dispatch("snap_point", candidates, 9.8, 10.1, 0.5)
    assert snap_acc == (10.0, 10.0)
    assert snap_py == (10.0, 10.0)

    # Validate self-intersecting ring (bowtie)
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    val_acc = native_backend.dispatch("validate_ring", bowtie)
    with disabled_acceleration():
        val_py = native_backend.dispatch("validate_ring", bowtie)
    assert any(i.get("code") == "self_intersection" for i in val_acc)
    assert any(i.get("code") == "self_intersection" for i in val_py)


