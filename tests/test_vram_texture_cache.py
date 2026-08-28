"""VramTextureCache (L2) acceptance tests — issue #1078.

Covers the four acceptance criteria:

1. 重复浏览已见切片 < 16 ms (L2 命中路径, 含基准测试)
2. VRAM 占用有界: 超预算时最久未用纹理被释放, 诊断计数可验证
3. 预算可通过配置调整 (512 MB–2 GiB), 切换 colormap 不触发 L1 重读
4. 多视图共存时共享同一全局预算 (不随视图数线性膨胀)
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_seismic import vram_cache as vram_module
from geoviz_seismic.colormap import ColormapManager
from geoviz_seismic.profile_vd import ProfileVD
from geoviz_seismic.vram_cache import (
    DEFAULT_BUDGET_BYTES,
    MAX_BUDGET_BYTES,
    MIN_BUDGET_BYTES,
    VRAM,
    VramTextureCache,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_global_vram():
    reset_for_tests(VRAM)
    yield
    reset_for_tests(VRAM)


def _release_spy(log: list, key):
    def _release():
        log.append(key)

    return _release


# ---------------------------------------------------------------------------
# Criterion 2 — bounded VRAM with LRU eviction, verified via diagnostics
# ---------------------------------------------------------------------------


def test_lru_eviction_releases_oldest_first():
    cache = VramTextureCache(max_bytes=3 * 100)
    released: list = []
    for i in range(3):
        cache.put(("k", i), content=None, size_bytes=100, kind="slice2d",
                  release=_release_spy(released, ("k", i)))

    # Touch k0 so k1 becomes the globally least-recently-used entry.
    cache.touch(("k", 0))
    cache.put(("k", 3), content=None, size_bytes=100, kind="slice2d",
              release=_release_spy(released, ("k", 3)))

    assert released == [("k", 1)]
    stats = cache.stats()
    assert stats["evictions"] == 1
    assert stats["releases"] == 1
    assert stats["bytes_now"] == 3 * 100
    assert stats["bytes_now"] <= stats["budget_bytes"]
    assert ("k", 1) not in cache
    assert ("k", 0) in cache and ("k", 2) in cache and ("k", 3) in cache


def test_budget_enforced_with_many_entries():
    cache = VramTextureCache(max_bytes=1000)
    released: list = []
    for i in range(30):
        cache.put(("k", i), content=None, size_bytes=100, kind="slice2d",
                  release=_release_spy(released, ("k", i)))
        assert cache.stats()["bytes_now"] <= 1000

    stats = cache.stats()
    assert stats["bytes_now"] <= 1000
    assert stats["evictions"] >= 20
    # Oldest keys evicted, newest resident.
    assert released == [("k", i) for i in range(30 - len(cache))]
    assert ("k", 29) in cache


def test_touch_keeps_on_screen_textures_resident():
    cache = VramTextureCache(max_bytes=200)
    released: list = []
    cache.put(("old",), content=None, size_bytes=100, kind="ortho3d",
              release=_release_spy(released, "old"))
    cache.put(("kept",), content=None, size_bytes=100, kind="ortho3d",
              release=_release_spy(released, "kept"))
    # paint()-time keepalive on the on-screen texture
    cache.touch(("kept",))
    cache.put(("new",), content=None, size_bytes=100, kind="ortho3d",
              release=_release_spy(released, "new"))

    assert released == ["old"]
    assert ("kept",) in cache and ("new",) in cache


def test_oversized_single_entry_stays_resident():
    """A slice larger than the whole budget is displayed, not self-evicted."""
    cache = VramTextureCache(max_bytes=100)
    cache.put(("huge",), content=None, size_bytes=10_000, kind="volume",
              release=_release_spy([], "huge"))
    assert ("huge",) in cache
    assert cache.stats()["bytes_now"] == 10_000


def test_stats_diagnostics_shape():
    cache = VramTextureCache(max_bytes=10_000)
    content = np.zeros((32, 32), dtype=np.uint8)
    cache.put(("a",), content=content, size_bytes=content.nbytes, kind="slice2d")
    assert cache.get(("a",)) is content
    cache.get(("missing",))

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["by_kind"] == {"slice2d": content.nbytes}
    assert stats["entries"] == 1
    assert stats["budget_bytes"] == 10_000
    assert stats["peak_bytes"] == content.nbytes


def test_reregister_updates_size_in_place():
    cache = VramTextureCache(max_bytes=10_000)
    cache.put(("k",), content=None, size_bytes=500, kind="ortho3d")
    # Same key, grown texture (owner reuses its GL name; no release may fire)
    cache.put(("k",), content=None, size_bytes=800, kind="ortho3d",
              release=_release_spy([], "k"))
    assert cache.stats()["bytes_now"] == 800
    assert cache.stats()["releases"] == 0
    assert len(cache) == 1


# ---------------------------------------------------------------------------
# Criterion 3 — configurable budget, colormap switch never touches L1
# ---------------------------------------------------------------------------


def test_budget_default_and_clamp():
    assert DEFAULT_BUDGET_BYTES == 1024 * 1024 * 1024  # 1 GiB default
    assert MIN_BUDGET_BYTES == 512 * 1024 * 1024
    assert MAX_BUDGET_BYTES == 2 * 1024 * 1024 * 1024

    cache = VramTextureCache(max_bytes=None, _use_env=False)
    assert cache.budget_bytes() == DEFAULT_BUDGET_BYTES
    # User-facing configuration is clamped to the contract range.
    assert cache.set_budget(1) == MIN_BUDGET_BYTES
    assert cache.set_budget(10 * 1024**3) == MAX_BUDGET_BYTES
    assert cache.set_budget(1536 * 1024 * 1024) == 1536 * 1024 * 1024


def test_budget_from_env(monkeypatch):
    monkeypatch.setenv("GEOVIZ_VRAM_BUDGET_MB", "768")
    cache = VramTextureCache()
    assert cache.budget_bytes() == 768 * 1024 * 1024

    monkeypatch.setenv("GEOVIZ_VRAM_BUDGET_MB", "8")  # below the floor
    assert VramTextureCache().budget_bytes() == MIN_BUDGET_BYTES

    monkeypatch.setenv("GEOVIZ_VRAM_BUDGET_MB", "not-a-number")
    assert VramTextureCache().budget_bytes() == DEFAULT_BUDGET_BYTES


def test_shrinking_budget_evicts_immediately():
    """A runtime budget cut frees the globally-LRU textures right away."""
    cache = VramTextureCache(max_bytes=10_000)
    released: list = []
    for i in range(3):
        cache.put(("k", i), content=None, size_bytes=100, kind="lut",
                  release=_release_spy(released, ("k", i)))
    # set_budget clamps to the 512 MiB contract floor, so the shrink policy
    # itself is driven through the same internal path set_budget uses.
    cache._max_bytes = 150
    cache._stats.budget_bytes = 150
    cache._apply_budget()
    assert cache.stats()["evictions"] == 2
    assert ("k", 0) not in cache and ("k", 1) not in cache
    assert ("k", 2) in cache
    assert cache.stats()["bytes_now"] == 100


def test_colormap_switch_does_not_renormalize_or_touch_l1(qtbot, monkeypatch):
    """Colormap change recolours the cached index texture; L1/L2 untouched."""
    from geoviz_seismic import seismic_view as sv_module

    view = sv_module.SeismicView(auto_load=False)
    qtbot.addWidget(view)
    rng = np.random.default_rng(7)
    sl = rng.normal(size=(400, 300)).astype(np.float32)
    view._update_profile_panel("inline", 5, sl)

    vd = view._profile_for("inline")._vd
    indexed_before = vd._indexed
    snap_before = vd.indexed_snapshot()
    l2_key = view._l2_texture_key(view._profile_for("inline"), "inline", 5, 0)
    assert l2_key in VRAM

    normalize_calls = []
    real_normalize = ColormapManager.normalize_to_index

    def _counting_normalize(*args, **kwargs):
        normalize_calls.append(1)
        return real_normalize(*args, **kwargs)

    l1_reads: list = []
    real_get = view._cache.get

    def _spying_get(key):
        l1_reads.append(key)
        return real_get(key)

    monkeypatch.setattr(view._cache, "get", _spying_get)
    monkeypatch.setattr(
        ColormapManager, "normalize_to_index", staticmethod(_counting_normalize)
    )

    # Drive the real toolbar wiring (currentTextChanged → panels + colorbar).
    view._cmap_combo.setCurrentText("gray")
    view._cmap_combo.setCurrentText("jet")

    assert normalize_calls == []          # no renormalize: recolour only
    assert vd._indexed is indexed_before  # index texture survives
    assert vd.indexed_snapshot() == snap_before
    assert l2_key in VRAM                 # L2 entry still valid (same key)
    assert l1_reads == []                 # L1 never re-read for a recolour

    # And the next revisit of this slice is still an L2 hit.
    hits_before = VRAM.stats()["hits"]
    view._update_profile_panel("inline", 5, sl)
    assert VRAM.stats()["hits"] == hits_before + 1
    assert normalize_calls == []


def test_wiggle_colormap_switch_keeps_slice_texture():
    """WiggleRenderer.set_colormap re-uploads only the 1-D LUT (mock GL)."""
    from geoviz_seismic.renderer.wiggle_instanced import WiggleTraceRenderer

    renderer = WiggleTraceRenderer()
    try:
        rng = np.random.default_rng(3)
        renderer.set_data(rng.normal(size=(64, 512)).astype(np.float32), mock_gl=True)
        renderer.set_colormap(ColormapManager.get_colormap("seismic"), mock_gl=True)
        slice_tex = renderer.texture.texture_id
        lut_bytes_before = VRAM.stats()["by_kind"].get("lut")

        renderer.set_colormap(ColormapManager.get_colormap("gray"), mock_gl=True)

        # Slice R32F texture untouched; only the LUT changed.
        assert renderer.texture.texture_id == slice_tex
        stats = VRAM.stats()
        assert stats["by_kind"]["wiggle"] == 64 * 512 * 4
        assert stats["by_kind"].get("lut") == lut_bytes_before
    finally:
        renderer.destroy(mock_gl=True)
    assert "wiggle" not in VRAM.stats()["by_kind"]


# ---------------------------------------------------------------------------
# Criterion 4 — one global budget shared by every view
# ---------------------------------------------------------------------------


def test_singleton_shared_across_import_sites():
    from geoviz_seismic import cache as cache_module
    from geoviz_seismic import renderer_3d, seismic_view

    assert cache_module.VRAM is vram_module.VRAM
    assert seismic_view.VRAM is vram_module.VRAM
    assert renderer_3d.VRAM is vram_module.VRAM


def test_two_views_share_one_budget_no_linear_growth(qtbot, monkeypatch):
    """Two SeismicViews share one ledger: identical slices dedup, LRU is global."""
    from geoviz_seismic import seismic_view as sv_module

    slice_px = 100 * 300  # indexed texture content = 1 byte per pixel
    tiny = VramTextureCache(max_bytes=slice_px + slice_px // 2)
    monkeypatch.setattr(sv_module, "VRAM", tiny)
    reset_for_tests(tiny)

    def make_view():
        view = sv_module.SeismicView(auto_load=False)
        qtbot.addWidget(view)
        return view

    view_a, view_b = make_view(), make_view()
    rng = np.random.default_rng(11)
    sl = rng.normal(size=(100, 300)).astype(np.float32)  # content: 30_000 B

    view_a._update_profile_panel("inline", 1, sl)
    view_b._update_profile_panel("inline", 1, sl)
    # Same (generation, slice, position, attr, clip) → ONE texture for both
    # views: memory does not grow with the number of views.
    assert tiny.stats()["entries"] == 1
    assert tiny.stats()["bytes_now"] == slice_px

    view_a._update_profile_panel("inline", 2, sl)
    stats = tiny.stats()
    assert stats["bytes_now"] <= stats["budget_bytes"]
    assert stats["evictions"] == 1  # the globally-LRU slice 1 was released
    assert stats["bytes_now"] == slice_px
    assert stats["entries"] == 1


# ---------------------------------------------------------------------------
# Criterion 1 — repeated slice browsing < 16 ms on the L2 hit path
# ---------------------------------------------------------------------------


def test_profile_revisit_renders_under_16ms(qtbot):
    """The acceptance benchmark: L2-hit rebuild of a seen slice stays <16 ms."""
    vd = ProfileVD()
    vd.resize(900, 700)
    qtbot.addWidget(vd)
    rng = np.random.default_rng(5)
    # 1050x750 ≈ 0.8 M samples — a realistic full-res inline slice.
    data = rng.normal(size=(1050, 750)).astype(np.float32)

    vd.render(data)  # cold: percentile scan + normalize + image build
    snap = vd.indexed_snapshot()
    assert snap is not None
    indexed, clip_range = snap

    durations = []
    for _ in range(9):
        t0 = time.perf_counter()
        vd.render_indexed(data, indexed, clip_range)
        durations.append((time.perf_counter() - t0) * 1000.0)

    median_ms = sorted(durations)[len(durations) // 2]
    assert median_ms < 16.0, f"L2-hit path too slow: median {median_ms:.2f} ms"


def test_seismic_view_repeated_browse_hits_l2(qtbot, monkeypatch):
    """Re-visiting a seen slice via the panel pipeline hits L2, not L1 I/O."""
    from geoviz_seismic import seismic_view as sv_module

    view = sv_module.SeismicView(auto_load=False)
    qtbot.addWidget(view)
    rng = np.random.default_rng(13)
    sl = rng.normal(size=(600, 400)).astype(np.float32).T

    normalize_calls = []
    real_normalize = ColormapManager.normalize_to_index

    def _counting_normalize(*args, **kwargs):
        normalize_calls.append(1)
        return real_normalize(*args, **kwargs)

    l1_reads: list = []
    real_get = view._cache.get

    def _spying_get(key):
        l1_reads.append(key)
        return real_get(key)

    monkeypatch.setattr(view._cache, "get", _spying_get)
    monkeypatch.setattr(
        ColormapManager, "normalize_to_index", staticmethod(_counting_normalize)
    )

    durations = []
    for pos in (7, 8, 7, 8, 7, 8, 7):
        t0 = time.perf_counter()
        view._update_profile_panel("inline", pos, sl)
        durations.append((time.perf_counter() - t0) * 1000.0)

    stats = VRAM.stats()
    assert stats["hits"] >= 4          # every revisit after the first pair hit
    # Two resident positions (7 and 8), 1 byte per pixel each.
    assert stats["by_kind"].get("slice2d") == 2 * 600 * 400
    assert len(normalize_calls) == 2   # one per distinct position
    # The panel pipeline is driven by cached slices: no L1 lookups happen in
    # _update_profile_panel itself (L1 serves _apply_pending_slice instead).
    assert l1_reads == []

    revisits = durations[2:]
    median_ms = sorted(revisits)[len(revisits) // 2]
    assert median_ms < 16.0, f"revisit median {median_ms:.2f} ms exceeds 16 ms"

    # And the displayed result is identical to the cold path.
    vd = view._profile_for("inline")._vd
    cold = ProfileVD()
    qtbot.addWidget(cold)
    cold.render(sl.astype(np.float32, copy=False))
    np.testing.assert_array_equal(vd._indexed, cold._indexed)


# ---------------------------------------------------------------------------
# 3-D integration — orthogonal planes reuse cached index textures
# ---------------------------------------------------------------------------


def test_renderer3d_ortho_slice_reuses_l2_content(qtbot, monkeypatch):
    """Slider revisit of the same plane skips normalize (L2 content hit)."""
    from geoviz_seismic import renderer_3d as r3d_module
    from geoviz_seismic import seismic_view as sv_module

    view = sv_module.SeismicView(auto_load=False)
    qtbot.addWidget(view)
    renderer = view._renderer_3d

    normalize_calls = []
    real_normalize = ColormapManager.normalize_to_index

    def _counting_normalize(*args, **kwargs):
        normalize_calls.append(1)
        return real_normalize(*args, **kwargs)

    monkeypatch.setattr(
        ColormapManager, "normalize_to_index", staticmethod(_counting_normalize)
    )

    rng = np.random.default_rng(17)
    vol = rng.normal(size=(24, 26, 30)).astype(np.float32)
    renderer.load_volume(vol)
    calls_after_load = len(normalize_calls)
    assert calls_after_load >= 3  # inline + crossline + time planes normalized

    key_hits_before = VRAM.stats()["hits"]
    renderer._il_pos = 3
    renderer._update_slice_planes_for({"inline"})
    # Rebuilding the SAME inline position a second time is a pure L2 hit.
    renderer._update_slice_planes_for({"inline"})

    assert len(normalize_calls) == calls_after_load + 1  # only the first rebuild
    assert VRAM.stats()["hits"] > key_hits_before


def test_gl_item_eviction_hooks_make_textures_reuploadable():
    """Eviction releases queue GL deletes and raise the re-upload flags."""
    from geoviz_seismic import renderer_3d as r3d

    item = r3d.GLImageLutItem(np.zeros((4, 4), dtype=np.uint8))
    item.texture = 4242
    item._needUpdate = False
    item._evict_index_texture()
    assert item.texture is None
    assert item._needUpdate is True
    assert 4242 in r3d._PENDING_GL_TEXTURE_DELETES

    item._lut_tex = 99
    item._lut_needs_upload = False
    item._evict_lut_texture()
    assert item._lut_tex is None
    assert item._lut_needs_upload is True
    assert 99 in r3d._PENDING_GL_TEXTURE_DELETES

    vol_item = r3d.DualGLVolumeItem(np.zeros((4, 4, 4, 4), dtype=np.uint8))
    vol_item.texture = 777
    vol_item._needUpload = False
    vol_item._evict_volume_texture()
    assert vol_item.texture is None
    assert vol_item._needUpload is True
    assert 777 in r3d._PENDING_GL_TEXTURE_DELETES

    vol_item._sculpt_horizon_tex = 555
    vol_item._sculpt_needs_upload = False
    vol_item._evict_horizon_texture()
    assert vol_item._sculpt_horizon_tex is None
    assert vol_item._sculpt_needs_upload is True

    vol_item._normal_tex = 333
    vol_item._normal_needs_upload = False
    vol_item._evict_normal_texture()
    assert vol_item._normal_tex is None
    assert vol_item._normal_needs_upload is True


def test_wiggle_texture_eviction_allows_reupload():
    from geoviz_seismic.renderer import wiggle_instanced as wi
    from geoviz_seismic.renderer.wiggle_instanced import WiggleTraceRenderer

    slice_bytes = 64 * 512 * 4  # one R32F slice texture
    tiny = VramTextureCache(max_bytes=slice_bytes)
    original = wi.VRAM
    wi.VRAM = tiny
    try:
        r1, r2 = WiggleTraceRenderer(), WiggleTraceRenderer()
        r1.set_data(
            np.random.default_rng(1).normal(size=(64, 512)).astype(np.float32),
            mock_gl=True,
        )
        assert r1.texture.texture_id is not None
        # A second renderer's texture exceeds the budget → the globally-LRU
        # r1 slice is evicted and its GPU handle explicitly dropped.
        r2.set_data(
            np.random.default_rng(2).normal(size=(64, 512)).astype(np.float32),
            mock_gl=True,
        )
        assert tiny.stats()["evictions"] == 1
        assert r1.texture.texture_id is None  # explicitly released
        # The evicted owner transparently re-uploads on its next update.
        r1.set_data(
            np.random.default_rng(3).normal(size=(64, 512)).astype(np.float32),
            mock_gl=True,
        )
        assert r1.texture.texture_id is not None
        stats = tiny.stats()
        assert stats["bytes_now"] <= stats["budget_bytes"]
        r1.destroy(mock_gl=True)
        r2.destroy(mock_gl=True)
        assert len(tiny) == 0
    finally:
        wi.VRAM = original
