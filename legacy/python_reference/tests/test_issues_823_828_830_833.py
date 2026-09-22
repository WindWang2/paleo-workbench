"""Regression tests for the algorithm-correctness batch #823/#828/#830/#833.

#823: compute_coherence_3d normalized its semblance denominator by the
vertical window length L instead of the spatial trace count J, so a fully
continuous body read L/J (0.333 at the default 3x3x3 window) — the value
scaled with window geometry, not geology. C++ kernel, Python fallback and
the "independent" test reference all carried the same error.

#828: the constrained-IDW batch path clamped its weight-sum denominator to
max(wsum, 1e-12) while the scalar sibling divided by the raw sum — at
power>=3 with metric coordinates the far-field constant field decayed from
100 to ~17.7.

#830: the pure-Python marching-cubes fallback let skimage's "No surface
found" RuntimeError escape for in-range but non-crossing iso values,
violating the C++ K-F2 empty-mesh contract; the UI silently toggled the
isosurface off.

#833: native_status() trusted any non-repo-root .so and never compared
__version__, dispatching stale foreign builds as "fresh".
"""

from __future__ import annotations

import types
from pathlib import Path

import numpy as np
import pytest

import paleo_workbench
from paleo_workbench.native_backend import (
    _py_compute_coherence_3d,
    _py_marching_cubes_3d,
    _repo_root,
    native_backend,
)
from paleo_workbench.viz.seismic_3d_api import (
    compute_coherence_3d,
    marching_cubes_3d,
)

try:
    import seismic_3d_core  # noqa: F401
    _HAS_CPP_MODULE = True
except ImportError:  # pragma: no cover — depends on local build
    _HAS_CPP_MODULE = False


# --------------------------------------------------------------------------- #
# #823 — coherence semblance normalization
# --------------------------------------------------------------------------- #
def _identical_trace_volume(ni: int, nx: int, nt: int, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    trace = rng.standard_normal(nt).astype(np.float32)
    return np.tile(trace, (ni, nx, 1))


@pytest.mark.parametrize(
    "iw,xw,sw",
    [(3, 3, 3), (5, 5, 5), (3, 5, 3), (1, 1, 1)],
    ids=["3x3x3", "5x5x5", "3x5x3", "1x1x1"],
)
def test_coherence_fallback_identical_traces_reach_one(iw: int, xw: int, sw: int) -> None:
    """Analytic oracle: semblance of identical traces is exactly 1.0."""
    vol = _identical_trace_volume(8, 8, 14)
    coh = _py_compute_coherence_3d(vol, iw, xw, sw)
    hi, hx = iw // 2, xw // 2
    interior = coh[hi : 8 - hi, hx : 8 - hx, :]
    np.testing.assert_allclose(interior, 1.0, atol=1e-6)


@pytest.mark.skipif(not _HAS_CPP_MODULE, reason="seismic_3d_core not built")
@pytest.mark.parametrize("iw,xw,sw", [(3, 3, 3), (5, 5, 5)])
def test_coherence_native_identical_traces_reach_one(iw: int, xw: int, sw: int) -> None:
    vol = _identical_trace_volume(8, 8, 14)
    coh = seismic_3d_core.compute_coherence_3d(
        vol, inline_window=iw, crossline_window=xw, sample_window=sw
    )
    hi, hx = iw // 2, xw // 2
    np.testing.assert_allclose(coh[hi : 8 - hi, hx : 8 - hx, :], 1.0, atol=1e-6)


def test_coherence_public_api_identical_traces_reach_one() -> None:
    vol = _identical_trace_volume(8, 8, 14)
    coh = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=3)
    np.testing.assert_allclose(coh[1:-1, 1:-1, :], 1.0, atol=1e-6)


def test_coherence_is_scale_invariant() -> None:
    """Amplitude must not change semblance (it is a normalized ratio)."""
    rng = np.random.default_rng(11)
    vol = rng.standard_normal((7, 7, 12)).astype(np.float32)
    a = _py_compute_coherence_3d(vol, 3, 3, 3)
    b = _py_compute_coherence_3d(vol * 7.5, 3, 3, 3)
    np.testing.assert_allclose(a[1:-1, 1:-1, :], b[1:-1, 1:-1, :], atol=1e-6)


def test_coherence_noise_mean_is_below_identical() -> None:
    """Uncorrelated noise must score clearly below a perfectly continuous
    body: E[semblance] ≈ 1/J (1/9 for 3x3), nowhere near the old L/J=0.333
    ceiling that made noise and continuity indistinguishable."""
    rng = np.random.default_rng(21)
    vol = rng.standard_normal((9, 9, 16)).astype(np.float32)
    coh = _py_compute_coherence_3d(vol, 3, 3, 3)
    assert float(np.mean(coh[1:-1, 1:-1, :])) < 0.25


@pytest.mark.skipif(not _HAS_CPP_MODULE, reason="seismic_3d_core not built")
def test_coherence_native_fallback_parity_random_volume() -> None:
    rng = np.random.default_rng(31)
    vol = rng.standard_normal((6, 6, 10)).astype(np.float32)
    native = seismic_3d_core.compute_coherence_3d(vol, 3, 3, 3)
    fallback = _py_compute_coherence_3d(vol, 3, 3, 3)
    # rtol is loose where coherence is near zero (division of two small
    # running sums); the absolute agreement is what parity means here.
    np.testing.assert_allclose(native, fallback, rtol=1e-4, atol=1e-6)


# --------------------------------------------------------------------------- #
# #828 — constrained IDW batch denominator floor
# --------------------------------------------------------------------------- #
def _batch_constant_field(power: float) -> np.ndarray:
    from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

    _ensure_haiyou_engine()
    from drawing.single_factor.fast_grid import interpolate_idw_grid_batch

    xs = np.linspace(-20000.0, 20000.0, 9)
    ys = np.linspace(-20000.0, 20000.0, 9)
    corners = [
        (-20000.0, -20000.0, 100.0),
        (20000.0, -20000.0, 100.0),
        (-20000.0, 20000.0, 100.0),
        (20000.0, 20000.0, 100.0),
    ]
    well_array = np.asarray(corners, dtype=float)
    mask = np.ones((len(ys), len(xs)), dtype=bool)
    return interpolate_idw_grid_batch(
        xs, ys, well_array, mask,
        search_radius=1e9, power=power, min_points=1, max_points=4,
        density_weights=np.array([]),
    )


def test_constrained_idw_batch_constant_field_exact_at_power3() -> None:
    """A constant field is the analytic fixed point of IDW at ANY power."""
    grid = _batch_constant_field(3.0)
    finite = grid[np.isfinite(grid)]
    assert finite.size > 0
    np.testing.assert_allclose(finite, 100.0, rtol=1e-9)


def test_constrained_idw_batch_far_field_matches_analytic_idw() -> None:
    """Far-field batch values must equal the analytic IDW formula — an
    independent oracle, not the sibling implementation (#828: the clamped
    denominator decayed these cells by wsum/1e-12)."""
    from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

    _ensure_haiyou_engine()
    from drawing.single_factor.fast_grid import interpolate_idw_grid_batch

    wells = [
        (-20000.0, -20000.0, 10.0),
        (20000.0, -20000.0, 20.0),
        (-20000.0, 20000.0, 30.0),
    ]
    well_array = np.asarray(wells, dtype=float)
    point = (3000.0, -1500.0)
    weights = np.array(
        [1.0 / float(np.hypot(point[0] - w[0], point[1] - w[1])) ** 3.0 for w in wells]
    )
    analytic = float(np.sum(weights * well_array[:, 2]) / weights.sum())

    gx = np.array([point[0]])
    gy = np.array([point[1]])
    mask = np.ones((1, 1), dtype=bool)
    batch = interpolate_idw_grid_batch(
        gx, gy, well_array, mask,
        search_radius=1e9, power=3.0, min_points=1, max_points=3,
        density_weights=np.array([]),
    )
    assert float(batch[0, 0]) == pytest.approx(analytic, rel=1e-9)


# --------------------------------------------------------------------------- #
# #830 — marching cubes fallback boundary contract
# --------------------------------------------------------------------------- #
def _binary_volume() -> np.ndarray:
    vol = np.zeros((8, 8, 8), dtype=np.float32)
    vol[2:6, 2:6, 2:6] = 1.0
    return vol


def test_marching_cubes_fallback_constant_equal_level_returns_empty() -> None:
    vol = np.ones((6, 6, 6), dtype=np.float32)
    verts, faces = _py_marching_cubes_3d(vol, isovalue=1.0)
    assert verts.shape == (0, 3) and faces.shape == (0, 3)


def test_marching_cubes_fallback_level_at_max_returns_empty() -> None:
    # Constant volume at its max has no strict crossing → empty mesh per K-F2.
    # The legacy skimage fallback also raised at binary iso==max (hence the
    # earlier assertion of empty), but the watertight MT fallback matches the
    # C++ kernel: a binary 0/1 volume at iso 1.0 still has a strict 0/1
    # crossing on boundary cubes and yields a closed surface (#886 parity).
    vol = np.ones((6, 6, 6), dtype=np.float32)
    verts, faces = _py_marching_cubes_3d(vol, isovalue=1.0)
    assert verts.shape == (0, 3) and faces.shape == (0, 3)


def test_marching_cubes_fallback_level_at_min_never_raises() -> None:
    """skimage's tie handling at level==min differs from the C++ mesh (the
    known topology divergence tracked separately); the #830 contract is that
    the fallback never ESCAPES with RuntimeError."""
    vol = _binary_volume()
    verts, faces = _py_marching_cubes_3d(vol, isovalue=0.0)
    assert verts.ndim == 2 and verts.shape[1] == 3
    assert faces.ndim == 2 and faces.shape[1] == 3


def test_marching_cubes_fallback_binary_at_iso_one_returns_empty() -> None:
    """Binary 0/1 volume at iso 1.0: MT fallback matches C++ (watertight mesh).

    The pre-#886 skimage fallback raised RuntimeError here and the guard mapped
    it to an empty mesh. The watertight MT kernel preserves the strict 0/1
    crossing (like native) and emits a closed surface (#886 parity)."""
    from collections import Counter

    vol = _binary_volume()
    verts, faces = _py_marching_cubes_3d(vol, isovalue=1.0)
    assert verts.shape[0] > 0 and faces.shape[0] > 0
    # Must be watertight like the sphere case (#886)
    keys = np.round(verts.astype(np.float64), decimals=4)
    _uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    faces_u = inv[faces]
    edge_count: Counter = Counter()
    for a, b, c in faces_u:
        for e in ((a, b), (b, c), (c, a)):
            edge_count[tuple(sorted((int(e[0]), int(e[1]))))] += 1
    assert edge_count and all(v == 2 for v in edge_count.values())


def test_marching_cubes_fallback_crossing_level_still_produces_mesh() -> None:
    vol = _binary_volume()
    verts, faces = _py_marching_cubes_3d(vol, isovalue=0.5)
    assert verts.shape[0] > 0 and faces.shape[0] > 0


@pytest.mark.parametrize("level", [1.0, 2.0])
def test_marching_cubes_public_api_boundary_levels_return_empty(level: float) -> None:
    """The dispatched path honors the empty-mesh contract on any backend:
    constant==level and out-of-range levels yield empty meshes (levels where
    the backends' tie topology legitimately differ are covered above)."""
    vol = np.ones((5, 5, 5), dtype=np.float32)
    verts, faces = marching_cubes_3d(vol, isovalue=level)
    assert verts.shape == (0, 3) and faces.shape == (0, 3)


# --------------------------------------------------------------------------- #
# #833 — native loader freshness gate
# --------------------------------------------------------------------------- #
def _fake_native_module(path: Path, version: str | None) -> types.ModuleType:
    mod = types.ModuleType("fake_native_module")
    mod.__file__ = str(path)
    if version is not None:
        mod.__version__ = version
    return mod


def _patch_feature(monkeypatch, feature: str, mod) -> None:
    from paleo_workbench import native_backend as nb

    modules = dict(nb._NATIVE_MODULES)
    modules[feature] = mod
    monkeypatch.setattr(nb, "_NATIVE_MODULES", modules)
    monkeypatch.setattr(nb, "_STALE_WARNED", set())


def test_native_status_foreign_module_without_version_is_stale(
    monkeypatch, tmp_path
) -> None:
    """The audit case: a sibling-worktree build with no __version__ must not
    pass as fresh (#833)."""
    mod = _fake_native_module(tmp_path / "seismic_3d_core.so", None)
    _patch_feature(monkeypatch, "seismic_3d", mod)
    from paleo_workbench import native_backend as nb

    assert nb.native_status("seismic_3d") == "stale"
    with pytest.warns(UserWarning, match="no build metadata"):
        assert native_backend.is_accelerated("seismic_3d") is False


def test_native_status_version_mismatch_is_stale(monkeypatch, tmp_path) -> None:
    mod = _fake_native_module(tmp_path / "seismic_3d_core.so", "0.0.1-old")
    _patch_feature(monkeypatch, "seismic_3d", mod)
    from paleo_workbench import native_backend as nb

    assert nb.native_status("seismic_3d") == "stale"
    with pytest.warns(UserWarning, match="predates the current package"):
        assert native_backend.is_accelerated("seismic_3d") is False


def test_native_status_matching_version_outside_repo_is_fresh(monkeypatch, tmp_path) -> None:
    """Editable installs / wheels land outside the tree but carry the right
    version — they must stay fresh."""
    mod = _fake_native_module(
        tmp_path / "seismic_3d_core.so", paleo_workbench.__version__
    )
    _patch_feature(monkeypatch, "seismic_3d", mod)
    from paleo_workbench import native_backend as nb

    assert nb.native_status("seismic_3d") == "fresh"


def test_native_status_in_repo_module_without_version_is_stale(monkeypatch) -> None:
    """#938-1 tightening: ALL native modules now carry build metadata, so a
    module without ``__version__`` is stale even when the binary sits in-tree
    (geo-viz-engine/native). The pre-#938 contract trusted such binaries —
    that trust was the "fresh 误判" the #938 batch closed."""
    in_tree = _repo_root() / "geo-viz-engine" / "native" / "map_edit_core" / "map_edit_core.so"
    mod = _fake_native_module(in_tree, None)
    _patch_feature(monkeypatch, "map_edit", mod)
    from paleo_workbench import native_backend as nb

    assert nb.native_status("map_edit") == "stale"
    monkeypatch.setattr(nb, "_HAS_MAP_EDIT_CPP", True)
    assert native_backend.is_accelerated("map_edit") is False


def test_repo_root_resolution_is_cached(monkeypatch) -> None:
    """#833 perf note: dispatch() must not re-resolve paths every call."""
    from paleo_workbench import native_backend as nb

    calls = {"n": 0}
    original = Path.resolve

    def counting_resolve(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(nb, "_REPO_ROOT_CACHE", None)
    with monkeypatch.context() as m:
        m.setattr(Path, "resolve", counting_resolve)
        first = nb._repo_root()
        assert calls["n"] >= 1
        calls["n"] = 0
        for _ in range(50):
            assert nb._repo_root() is first
        assert calls["n"] == 0
