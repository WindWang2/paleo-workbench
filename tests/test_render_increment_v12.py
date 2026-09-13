# -*- coding: utf-8 -*-
"""V12-C 渲染增量通道的缓存失效矩阵（含反向对照）。

七个失效场景（goal §3.4：改顶点 / 增删要素 / 改样式 / 可见性-不透明度 /
切换图层 / 切换 CRS / undo-redo）+ 标量栅格 QImage 缓存的失效与等价性。

每个失效场景都带**反向对照**测试：人为破坏缓存键（让修订比较失效 /
剪除失效），断言陈旧结果**确实会被服出**——证明正向测试的断言一旦键
损坏必然变红，不是空断言（tautological 守卫：tests/e2e/test_integrity_guard）。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.revision_cache import LatestRevisionCache


# ---------------------------------------------------------------- helpers ----

def _polygon(ox: float, oy: float, fid: str, size: float = 30.0) -> dict:
    return {
        "id": fid,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [ox, oy], [ox + size, oy], [ox + size, oy + size],
                [ox, oy + size], [ox, oy],
            ]],
        },
        "properties": {},
    }


def _vector_snapshot(
    *,
    data_revision: int = 1,
    style_revision: int = 1,
    features: tuple[dict, ...] | None = None,
    visible: bool = True,
    opacity: float = 1.0,
    layer_id: str = "vec:1",
    style: dict | None = None,
    crs: str = "EPSG:3857",
    project_crs: str = "EPSG:3857",
) -> MapRenderSnapshot:
    if features is None:
        features = (_polygon(0.0, 0.0, "f1"), _polygon(80.0, 0.0, "f2"))
    return MapRenderSnapshot(
        project_crs=project_crs,
        layers=(
            MapLayerSnapshot(
                id=layer_id,
                name="vector",
                layer_type="vector",
                extent=(0.0, 0.0, 300.0, 240.0),
                crs=crs,
                data_revision=data_revision,
                style_revision=style_revision,
                features=tuple(features),
                style=style if style is not None else {
                    "fill": "#2080d0", "stroke": "#102040", "stroke_width": 2.0,
                },
                visible=visible,
                opacity=opacity,
            ),
        ),
    )


class _CountingSolidRaster:
    """Deterministic scalar payload: one solid RGBA tile, call-counted."""

    def __init__(self, rgb=(220, 30, 30), size=(40, 50)) -> None:
        self._rgba = np.zeros((size[0], size[1], 4), dtype=np.uint8)
        self._set_rgb(rgb)
        self.rasterize_calls = 0
        self.data_revision = 1
        self.style_revision = 1

    def _set_rgb(self, rgb) -> None:
        self._rgba[..., 0] = rgb[0]
        self._rgba[..., 1] = rgb[1]
        self._rgba[..., 2] = rgb[2]
        self._rgba[..., 3] = 255

    @property
    def rgb(self) -> tuple:
        return (int(self._rgba[0, 0, 0]), int(self._rgba[0, 0, 1]), int(self._rgba[0, 0, 2]))

    def repaint(self, rgb, *, data_revision=None, style_revision=None) -> None:
        self._set_rgb(rgb)
        if data_revision is not None:
            self.data_revision = data_revision
        if style_revision is not None:
            self.style_revision = style_revision

    def rasterize(self) -> np.ndarray:
        self.rasterize_calls += 1
        return self._rgba


def _scalar_snapshot(payload, *, data_revision=1, style_revision=1, layer_id="map:grid"):
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id=layer_id,
                name="Scalar",
                layer_type="scalar_grid",
                extent=(30.0, 20.0, 240.0, 180.0),
                crs="EPSG:3857",
                data_revision=data_revision,
                style_revision=style_revision,
                renderer_payload=payload,
            ),
        ),
    )


def _render(backend: FallbackMapRenderBackend, snapshot: MapRenderSnapshot,
            extent=(0.0, 0.0, 300.0, 240.0)):
    backend.set_layer_snapshot(snapshot)
    backend.set_extent(extent)
    backend.set_output_size(200, 160)
    backend.set_dpi(96.0)
    return backend.render_sync()


def _center_rgba(frame) -> bytes:
    offset = (frame.height // 2) * frame.stride + (frame.width // 2) * 4
    return frame.rgba[offset: offset + 4]


@pytest.fixture
def sabotage_cache_key(monkeypatch):
    """反向对照专用：让 LatestRevisionCache.get 无视修订键（永远命中旧值）。

    这正是「缓存键损坏」的最小模型——用它服出陈旧结果、并断言陈旧确实
    发生，证明正向测试的修订断言有牙齿。
    """

    def broken_get(self, subject, revision_key):
        entry = self._entries.get(subject)
        return None if entry is None else entry[1]

    monkeypatch.setattr(LatestRevisionCache, "get", broken_get)


@pytest.fixture
def sabotage_prune(monkeypatch):
    """反向对照专用：让 prune 变 no-op（切换图层后旧条目不释放）。"""
    monkeypatch.setattr(LatestRevisionCache, "prune", lambda self, keep: None)


@pytest.fixture
def sabotage_frame_key(monkeypatch):
    """反向对照专用：_frame_key 丢弃 style_revision，visible 恒 True。"""
    original = FallbackMapRenderBackend._frame_key

    def stripped(self):
        extent, output, dpi, layers, project_crs = original(self)
        layers = tuple(
            (layer_id, layer_type, revision, True, opacity, scale_range, crs)
            for (layer_id, layer_type, revision, _style_rev, _visible, opacity,
                 scale_range, crs) in layers
        )
        return (extent, output, dpi, layers, project_crs)

    monkeypatch.setattr(FallbackMapRenderBackend, "_frame_key", stripped)


# =================================================== scalar QImage cache ====

def test_scalar_grid_reuses_qimage_across_frames_and_stays_pixel_identical():
    payload = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    frame_a = _render(backend, _scalar_snapshot(payload), extent=(30.0, 20.0, 230.0, 180.0))
    backend.set_extent((40.0, 20.0, 240.0, 180.0))  # pan: frame cache misses by design
    frame_b = backend.render_sync()

    reference = FallbackMapRenderBackend()
    ref_frame_b = _render(
        reference,
        _scalar_snapshot(_CountingSolidRaster()),  # same content, fresh backend
        extent=(40.0, 20.0, 240.0, 180.0),
    )

    assert payload.rasterize_calls == 1  # exactly one rasterize+copy across both frames
    diagnostics = backend.render_diagnostics()
    assert diagnostics["scalar_cache_misses"] == 1
    assert diagnostics["scalar_cache_hits"] == 1
    assert frame_b.rgba == ref_frame_b.rgba  # cached-QImage frame ≡ fresh-render frame


def test_scalar_grid_data_change_invalidates_cache():
    payload = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    red = _render(backend, _scalar_snapshot(payload))
    assert _center_rgba(red)[:3] == bytes((220, 30, 30))

    payload.repaint((30, 30, 220), data_revision=2)
    blue = _render(backend, _scalar_snapshot(payload, data_revision=2))

    assert payload.rasterize_calls == 2
    assert backend.render_diagnostics()["scalar_cache_misses"] == 2
    assert _center_rgba(blue)[:3] == bytes((30, 30, 220))


def test_scalar_grid_style_change_invalidates_cache():
    payload = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(payload))

    payload.repaint((30, 220, 30), style_revision=2)
    green = _render(backend, _scalar_snapshot(payload, style_revision=2))

    assert payload.rasterize_calls == 2
    assert _center_rgba(green)[:3] == bytes((30, 220, 30))


def test_scalar_grid_payload_revision_alone_invalidates_cache():
    """宿主忘了 bump 快照修订、只有 payload 自身修订变了 → 仍不得服旧像素。

    （平移触发重绘：帧缓存按设计失效，走 _draw_scalar_grid。）
    """
    payload = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(payload), extent=(30.0, 20.0, 230.0, 180.0))

    payload.repaint((220, 220, 30), data_revision=9)  # snapshot revisions stay 1/1
    yellow = _render(backend, _scalar_snapshot(payload), extent=(31.0, 20.0, 231.0, 180.0))

    assert payload.rasterize_calls == 2
    assert _center_rgba(yellow)[:3] == bytes((220, 220, 30))


def test_scalar_grid_payload_object_swap_forces_miss():
    """同 layer id、同修订、换了 payload 对象 → `is` 校验兜底，必须重建。"""
    payload_a = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(payload_a), extent=(30.0, 20.0, 230.0, 180.0))

    payload_b = _CountingSolidRaster(rgb=(120, 30, 220))
    purple = _render(
        backend, _scalar_snapshot(payload_b), extent=(31.0, 20.0, 231.0, 180.0)
    )  # same ids/revisions; only the extent (and payload object) changed

    assert payload_b.rasterize_calls == 1
    assert backend.render_diagnostics()["scalar_cache_misses"] == 2
    assert _center_rgba(purple)[:3] == bytes((120, 30, 220))


def test_negative_control_broken_scalar_key_serves_stale_pixels(sabotage_cache_key):
    payload = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(payload))

    payload.repaint((30, 30, 220), data_revision=2)
    stale = _render(backend, _scalar_snapshot(payload, data_revision=2))

    # 键被破坏时旧 QImage 确实被复用——正向测试的「必须变蓝」断言因此有牙齿。
    assert payload.rasterize_calls == 1
    assert _center_rgba(stale)[:3] == bytes((220, 30, 30))


def test_negative_control_dropped_payload_identity_serves_previous_image():
    """身份守卫失效（缓存条目被视作属于新 payload）→ 旧像素确实被服出。"""
    payload_a = _CountingSolidRaster()
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(payload_a), extent=(30.0, 20.0, 230.0, 180.0))

    payload_b = _CountingSolidRaster(rgb=(120, 30, 220))  # 同修订、不同对象
    backend._scalar_images.latest("map:grid").payload = payload_b  # 破坏身份守卫
    stale = _render(
        backend, _scalar_snapshot(payload_b), extent=(31.0, 20.0, 231.0, 180.0)
    )

    assert payload_b.rasterize_calls == 0  # 平移已强制重绘，仍未 rasterize ⇒ 陈旧
    assert _center_rgba(stale)[:3] == bytes((220, 30, 30))


def test_scalar_grid_layer_switch_prunes_cache():
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(_CountingSolidRaster(), layer_id="map:grid"))
    _render(backend, _scalar_snapshot(_CountingSolidRaster(), layer_id="map:other"))

    assert backend._scalar_images.subjects() == ("map:other",)


def test_negative_control_broken_prune_accumulates_stale_entries(sabotage_prune):
    backend = FallbackMapRenderBackend()
    _render(backend, _scalar_snapshot(_CountingSolidRaster(), layer_id="map:grid"))
    _render(backend, _scalar_snapshot(_CountingSolidRaster(), layer_id="map:other"))

    # prune 失效时旧条目确实残留——正向「剪除断言」因此有牙齿。
    assert set(backend._scalar_images.subjects()) == {"map:grid", "map:other"}


# ================================================ vector prepared cache =====

def test_vertex_edit_invalidates_prepared_and_changes_pixels():
    backend = FallbackMapRenderBackend()
    before = _render(backend, _vector_snapshot())
    misses_before = backend.render_diagnostics()["prepared_cache_misses"]

    moved = (_polygon(0.0, 40.0, "f1"), _polygon(80.0, 0.0, "f2"))  # f1 shifted up
    after = _render(backend, _vector_snapshot(features=moved, data_revision=2))

    assert backend.render_diagnostics()["prepared_cache_misses"] == misses_before + 1
    assert after.rgba != before.rgba


def test_feature_removal_invalidates_prepared_and_changes_pixels():
    backend = FallbackMapRenderBackend()
    before = _render(backend, _vector_snapshot())
    misses_before = backend.render_diagnostics()["prepared_cache_misses"]

    after = _render(
        backend,
        _vector_snapshot(features=(_polygon(0.0, 0.0, "f1"),), data_revision=2),
    )

    assert backend.render_diagnostics()["prepared_cache_misses"] == misses_before + 1
    assert backend.render_diagnostics()["features_total"] == 1
    assert after.rgba != before.rgba


def test_style_change_reuses_prepared_geometry():
    """改样式（不动几何）→ 帧必须变化，但 prepared 零重建（纯命中）。"""
    backend = FallbackMapRenderBackend()
    before = _render(backend, _vector_snapshot())
    hits_before = backend.render_diagnostics()["prepared_cache_hits"]
    misses_before = backend.render_diagnostics()["prepared_cache_misses"]

    after = _render(
        backend,
        _vector_snapshot(style_revision=2, style={
            "fill": "#d02080", "stroke": "#401020", "stroke_width": 2.0,
        }),
    )

    diagnostics = backend.render_diagnostics()
    # 每帧两次 _prepared_layer 调用（预热 + 绘制）都命中——几何零重建。
    assert diagnostics["prepared_cache_hits"] > hits_before
    assert diagnostics["prepared_cache_misses"] == misses_before  # zero rebuild
    assert after.rgba != before.rgba  # style visibly applied


def test_visibility_roundtrip_keeps_prepared_entry():
    backend = FallbackMapRenderBackend()
    visible_1 = _render(backend, _vector_snapshot(visible=True))
    misses_before = backend.render_diagnostics()["prepared_cache_misses"]

    _render(backend, _vector_snapshot(visible=False, style_revision=2))
    visible_2 = _render(backend, _vector_snapshot(visible=True, style_revision=3))

    # 隐藏期间缓存保留，重新可见零重建，且几何与首次可见帧逐字节一致。
    assert backend.render_diagnostics()["prepared_cache_misses"] == misses_before
    assert visible_2.rgba == visible_1.rgba


def test_layer_switch_prunes_prepared_entries():
    backend = FallbackMapRenderBackend()
    two_layers = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="vec:a", name="a", layer_type="vector",
                extent=(0.0, 0.0, 300.0, 240.0), crs="EPSG:3857",
                data_revision=1, style_revision=1,
                features=(_polygon(0.0, 0.0, "f1"),),
            ),
            MapLayerSnapshot(
                id="vec:b", name="b", layer_type="vector",
                extent=(0.0, 0.0, 300.0, 240.0), crs="EPSG:3857",
                data_revision=1, style_revision=1,
                features=(_polygon(80.0, 0.0, "f2"),),
            ),
        ),
    )
    _render(backend, two_layers)
    assert set(backend._prepared.subjects()) == {"vec:a", "vec:b"}

    _render(backend, _vector_snapshot(layer_id="vec:c"))
    assert backend._prepared.subjects() == ("vec:c",)


def test_negative_control_broken_prune_keeps_old_layers(sabotage_prune):
    backend = FallbackMapRenderBackend()
    _render(backend, _vector_snapshot(layer_id="vec:a"))
    _render(backend, _vector_snapshot(layer_id="vec:c"))

    # prune 失效时旧层条目确实残留——正向「主体集 == 新集合」因此有牙齿。
    assert set(backend._prepared.subjects()) == {"vec:a", "vec:c"}


def test_negative_control_broken_prepared_key_serves_stale_geometry(sabotage_cache_key):
    """#1257 同族场景：修订键失效时，编辑后的几何不会被重建（陈旧被服出）。"""
    backend = FallbackMapRenderBackend()
    before = _render(backend, _vector_snapshot())

    moved = (_polygon(0.0, 40.0, "f1"), _polygon(80.0, 0.0, "f2"))
    stale = _render(backend, _vector_snapshot(features=moved, data_revision=2))

    # 旧 prepared 几何被复用 → 帧与编辑前一致；正向「帧必须变化」因此有牙齿。
    assert stale.rgba == before.rgba


def test_negative_control_broken_frame_key_serves_stale_style(sabotage_frame_key):
    backend = FallbackMapRenderBackend()
    before = _render(backend, _vector_snapshot())

    styled = _render(
        backend,
        _vector_snapshot(style_revision=2, style={
            "fill": "#ffffff", "stroke": "#ffffff", "stroke_width": 2.0,
        }),
    )
    hidden = _render(backend, _vector_snapshot(visible=False, style_revision=2))

    # 帧键丢掉 style_revision / visible 时旧帧确实被复用——样式未上屏、
    # 隐藏层不消失；两个正向断言（帧变化 / 隐藏生效）因此有牙齿。
    assert styled.rgba == before.rgba
    assert hidden.rgba == before.rgba


def test_undo_redo_rebuilds_and_restores_geometry_pixels():
    """undo 后几何与 v1 相同（修订不同）→ 必须重建且像素与 v1 逐字节一致。"""
    backend = FallbackMapRenderBackend()
    v1 = _render(backend, _vector_snapshot(data_revision=1))
    misses_after_v1 = backend.render_diagnostics()["prepared_cache_misses"]

    _render(backend, _vector_snapshot(
        features=(_polygon(0.0, 40.0, "f1"), _polygon(80.0, 0.0, "f2")),
        data_revision=2,
    ))
    assert backend.render_diagnostics()["prepared_cache_misses"] == misses_after_v1 + 1

    # undo：几何回滚，修订继续单调递增（undo 也是一个新修订）。
    undone = _render(backend, _vector_snapshot(data_revision=3))

    assert backend.render_diagnostics()["prepared_cache_misses"] == misses_after_v1 + 2
    assert undone.rgba == v1.rgba  # geometry-equal ⇒ pixel-equal, revision be damned


def _geo_snapshot(project_crs: str, *, visible: bool = True) -> MapRenderSnapshot:
    """经纬度图层（EPSG:4326），几何 lon 116..117 / lat 39..40。"""
    return _vector_snapshot(
        features=(_polygon(116.0, 39.0, "g1", size=1.0),),
        crs="EPSG:4326",
        project_crs=project_crs,
        layer_id="vec:geo",
        visible=visible,
    )


def _empty_frame(project_crs: str, extent):
    backend = FallbackMapRenderBackend()
    return _render(backend, _geo_snapshot(project_crs, visible=False), extent=extent)


_EXTENT_32650 = (405000.0, 4300000.0, 505000.0, 4440000.0)
_EXTENT_3857 = (12890000.0, 4700000.0, 13030000.0, 4900000.0)


def test_crs_switch_reprojects_through_new_cache_entry():
    pytest.importorskip("pyproj")
    from paleo_workbench.mapping.map_render_backend import make_crs_transformer

    if make_crs_transformer("EPSG:4326", "EPSG:32650") is None:
        pytest.skip("pyproj cannot resolve the test CRS pair")

    backend = FallbackMapRenderBackend()
    in_utm = _render(backend, _geo_snapshot("EPSG:32650"), extent=_EXTENT_32650)
    assert in_utm.rgba != _empty_frame("EPSG:32650", _EXTENT_32650).rgba  # geometry visible
    assert len(backend._reprojected) == 1

    in_merc = _render(backend, _geo_snapshot("EPSG:3857"), extent=_EXTENT_3857)
    # 新工程 CRS → 新投影缓存键，几何以 Web 墨卡托米制坐标可见；条目替换不累积。
    assert in_merc.rgba != _empty_frame("EPSG:3857", _EXTENT_3857).rgba
    assert in_merc.rgba != in_utm.rgba
    assert len(backend._reprojected) == 1


def test_negative_control_broken_reproject_key_serves_stale_projection(sabotage_cache_key):
    pytest.importorskip("pyproj")
    from paleo_workbench.mapping.map_render_backend import make_crs_transformer

    if make_crs_transformer("EPSG:4326", "EPSG:32650") is None:
        pytest.skip("pyproj cannot resolve the test CRS pair")

    backend = FallbackMapRenderBackend()
    _render(backend, _geo_snapshot("EPSG:32650"), extent=_EXTENT_32650)

    # 键被破坏：切到 3857 后仍复用 UTM 投影几何——UTM 数值落在墨卡托
    # 画布之外，几何消失（帧 == 空基线）。正向「新 CRS 下几何可见」因此有牙齿。
    stale = _render(backend, _geo_snapshot("EPSG:3857"), extent=_EXTENT_3857)
    assert stale.rgba == _empty_frame("EPSG:3857", _EXTENT_3857).rgba
