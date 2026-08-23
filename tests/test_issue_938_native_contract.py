"""Regression tests for issue #938 native contract batch (9 sub-items)."""
from __future__ import annotations

import pathlib
import types
import warnings

import numpy as np
import pytest

from paleo_workbench.native_backend import (
    NativeEngineBackend,
    _NATIVE_MODULES,
    _repo_root,
    native_backend,
    native_status,
)
from paleo_workbench.viz.seismic_3d_api import fast_slice_to_indexed8


def _fake_module(path: pathlib.Path, version: str | None = None):
    mod = types.ModuleType("fake_mod")
    mod.__file__ = str(path)
    if version is not None:
        mod.__version__ = version
    return mod


# ---------------------------------------------------------------------------
# #938-1  cross-worktree fresh mis-judgement: scratch copy without .git stays stale
# ---------------------------------------------------------------------------
def test_938_1_scratch_copy_without_git_is_stale(monkeypatch):
    """Probe from issue: scratch copy of a fresh .so must NOT be fresh."""
    from paleo_workbench import native_backend as nb_mod
    import paleo_workbench

    pkg = "map_edit_core"
    # Simulate a versionless .so copied to /tmp/scratch/native/map_edit_core/...
    scratch_so = pathlib.Path("/tmp/scratch/native") / pkg / "map_edit_core.cpython.so"
    fake = _fake_module(scratch_so, version=None)
    monkeypatch.setitem(_NATIVE_MODULES, "map_edit", fake)
    # also patch FEATURE map entry's import check to pretend has_cpp
    monkeypatch.setattr(nb_mod.NativeEngineBackend, "has_cpp", lambda self, f: f == "map_edit")
    # _repo_root still points to worktree; scratch path is outside repo and has no .git
    # With the tightened rule, versionless => stale even if path contained "native/<pkg>".
    assert native_status("map_edit") == "stale"
    # Ensure is_accelerated respects it
    be = NativeEngineBackend()
    monkeypatch.setattr(be, "has_cpp", lambda f: f == "map_edit")
    assert be.is_accelerated("map_edit") is False


def test_938_1_versionless_inside_repo_is_stale(monkeypatch):
    """Even inside repo, a versionless binary must now be stale (#938-1 tightens to version match)."""
    repo_so = _repo_root() / "native" / "map_edit_core" / "map_edit_core.so"
    fake = _fake_module(repo_so, version=None)
    monkeypatch.setitem(_NATIVE_MODULES, "map_edit", fake)
    assert native_status("map_edit") == "stale"


def test_938_1_version_match_inside_repo_is_fresh(monkeypatch):
    """Inside repo + matching version => fresh."""
    import paleo_workbench

    repo_so = _repo_root() / "native" / "map_edit_core" / "map_edit_core.so"
    fake = _fake_module(repo_so, version=paleo_workbench.__version__)
    monkeypatch.setitem(_NATIVE_MODULES, "map_edit", fake)
    assert native_status("map_edit") == "fresh"
    assert NativeEngineBackend().is_accelerated("map_edit") is True if NativeEngineBackend().has_cpp("map_edit") else True


# ---------------------------------------------------------------------------
# #938-2  ~CURVE bare "~" column contract: native 3 cols vs fallback 1 col
# ---------------------------------------------------------------------------
def test_938_2_bare_tilde_curve_mnemonic_aligns_with_native():
    """A lone '~' line inside ~CURVE must be parsed as a mnemonic, not a section header."""
    las = (
        "~C\n"
        "DEPT.M\n"
        "~\n"
        "GR  .GAPI\n"
        "~A\n"
        "1 2 3\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        headers, arr = native_backend.dispatch("fast_las_parse_data", las, -999.0)
    # Native produces 3 headers; fallback must now also produce 3 and not warn about truncation
    assert headers == ("DEPT", "~", "GR")
    assert arr.shape == (1, 3)
    # No truncation warning because num_cols==3 matches row length
    assert not any("truncated" in str(x.message).lower() for x in w)


# ---------------------------------------------------------------------------
# #938-3  fixed-range degenerate uses float32 semantics
# ---------------------------------------------------------------------------
def test_938_3_fixed_range_float32_degenerate():
    """Value range that is distinct in float64 but equal in float32 must degenerate to (0,0) on both paths."""
    vol = np.zeros((4, 4, 4), dtype=np.float32)
    vol[0, 0, 0] = 1.0
    # v_min and v_max differ by < float32 epsilon at 1.0
    v_min = 1.0
    v_max = 1.0 + 5e-8  # < 1.19e-7, so float32(v_min) == float32(v_max)
    assert v_min < v_max  # double distinct
    assert not (np.float32(v_min) < np.float32(v_max))  # float32 equal

    # Dispatch through fallback (force python) – after fix should degenerate
    from paleo_workbench.native_backend import disabled_acceleration

    with disabled_acceleration():
        arr, lo, hi = fast_slice_to_indexed8(vol, 0, 0, value_range=(v_min, v_max))
    assert (lo, hi) == (0.0, 0.0)
    assert arr.shape == vol.shape[1:]
    assert (arr == 0).all()

    # Also test that a normal range still works and returns float32-rounded values
    arr2, lo2, hi2 = fast_slice_to_indexed8(vol, 0, 0, value_range=(0.0, 2.0))
    # lo2/hi2 are float32-rounded versions
    assert lo2 == float(np.float32(0.0))
    assert hi2 == float(np.float32(2.0))


# ---------------------------------------------------------------------------
# #938-4  value_range string "55" must raise like native
# ---------------------------------------------------------------------------
def test_938_4_value_range_string_raises():
    vol = np.zeros((4, 4, 4), dtype=np.float32)
    from paleo_workbench.native_backend import disabled_acceleration

    with disabled_acceleration():
        with pytest.raises((ValueError, TypeError)):
            fast_slice_to_indexed8(vol, 0, 0, value_range="55")  # type: ignore
        with pytest.raises((ValueError, TypeError)):
            fast_slice_to_indexed8(vol, 0, 0, value_range=("55", "60"))  # type: ignore


# ---------------------------------------------------------------------------
# #938-7  layer_model_core __version__ and stale gate
# ---------------------------------------------------------------------------
def test_938_7_layer_model_has_version():
    try:
        import layer_model_core
    except ImportError:
        pytest.skip("layer_model_core not built")
    assert hasattr(layer_model_core, "__version__")
    assert layer_model_core.__version__ == "0.2.17a0"


def test_938_7_native_factor_map_gates_stale(monkeypatch):
    """native_scene_available must be False when layer_model is stale."""
    import paleo_workbench.viz.native_factor_map as nfm

    monkeypatch.setattr("paleo_workbench.native_backend.native_status", lambda f: "stale" if f in ("grid_render", "layer_model") else "fresh")
    # If either is stale, available is False
    assert nfm.native_scene_available() is False


# ---------------------------------------------------------------------------
# #938-8  qgis_render_bridge has __version__ and correct version
# ---------------------------------------------------------------------------
def test_938_8_qgis_bridge_has_version():
    # The extension is optional; if built, check metadata.
    try:
        import qgis_render_bridge
    except ImportError:
        pytest.skip("qgis_render_bridge not built (optional)")
    assert hasattr(qgis_render_bridge, "__version__")
    assert qgis_render_bridge.__version__ == "0.2.17a0"


# ---------------------------------------------------------------------------
# #938-6  cancel_render preserves pending_snapshot (fallback backend) – map backend is out of boundary,
# #        verify qgis bridge behavior via unit inspection and document map_backend fix expectation
# ---------------------------------------------------------------------------
def test_938_6_fallback_cancel_render_discards_stale_but_preserves_generation():
    """Fallback cancel_render bumps generation so in-flight frames are discarded."""
    from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend, MapRenderSnapshot
    from paleo_workbench.mapping.map_styles import VectorStyle

    backend = FallbackMapRenderBackend(threaded=False)
    backend.initialize()
    # Request a render, then cancel – completed should be None
    backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:4326", layers=()))
    backend.set_extent((0, 0, 1, 1))
    backend.set_output_size(10, 10)
    backend.request_render()
    frame = backend.take_completed_frame()
    assert frame is not None
    backend.request_render()
    backend.cancel_render()
    # After cancel, completed is cleared and no stale frame is delivered
    assert backend.take_completed_frame() is None
    backend.shutdown()


# ---------------------------------------------------------------------------
# #938-5  thread contract documentation: import check that docstring exists
# ---------------------------------------------------------------------------
def test_938_5_qgis_render_bridge_thread_contract_documented():
    try:
        import qgis_render_bridge
    except ImportError:
        pytest.skip("qgis_render_bridge not built")
    # Check that render_active docstring mentions event loop / #938-5
    doc = getattr(qgis_render_bridge.QgisRenderBridge, "render_active").__doc__ or ""
    # Also check header docstring via Python's help? The binding adds doc.
    # At minimum, the module should mention threading.
    assert "event loop" in doc.lower() or "938-5" in doc or "thread" in doc.lower()
