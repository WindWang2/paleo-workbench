# -*- coding: utf-8 -*-
"""V12-C 镜像缓存清理接线：reset_publish_ledger 真清理 + 栈回收三表同剪。

BASE 的两处缺口（qgis_mirror）：
1. ``_layer_ledger_tokens`` 的 ``return`` 之后挂着 V10/V11 的三行清理语句——
   死代码，``reset_publish_ledger`` 实际从未清 ``_SIGNATURE_CACHE`` /
   ``_RASTER_LEDGER`` / ``_STACK_ID_REFS``（工程切换后旧签跨工程存活，
   #1257 同族陈旧隐患）。
2. 栈地址复用/回收防护（``_purge_stack_entries``）只清主台账——签名缓存与
   raster 台账的旧 (stack, layer) 条目残留，新栈可能读到陈旧基线。
"""

from __future__ import annotations

import gc

import pytest

pytest.importorskip("PySide6")

import paleo_workbench.mapping.qgis_mirror as qgis_mirror
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.qgis_mirror import (
    _RASTER_LEDGER,
    _SIGNATURE_CACHE,
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)


class _Stack:
    """最小假栈：记录 upsert 调用（签名与真桥同形，能力探测全过）。"""

    def __init__(self):
        self.calls: list[dict] = []

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta="",
                            fields_json=""):
        self.calls.append({"doc_id": doc_id})
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass


def _layer(*, revision: int = 7, layer_id: str = "doc-mock") -> MapLayerSnapshot:
    return MapLayerSnapshot(
        id=layer_id, name="mock", layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=revision, style_revision=1,
        features=(
            {"type": "Feature",
             "geometry": {"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
             "properties": {"facies_name": "扇三角洲", "__pwb_fid": "f1"}},
        ),
        style={}, visible=True, opacity=1.0,
    )


@pytest.fixture(autouse=True)
def _clean_ledgers():
    reset_publish_ledger()
    yield
    reset_publish_ledger()


def test_reset_publish_ledger_clears_signature_cache(monkeypatch):
    stack = _Stack()
    mirror_snapshot_to_stack(stack, 1, MapRenderSnapshot(
        project_crs="EPSG:4326", layers=(_layer(),)))
    assert len(_SIGNATURE_CACHE) == 1  # 发布后签名缓存有条目（前置非空）

    reset_publish_ledger()

    # 死代码修复后：reset 真正清空签名缓存（旧实现留存 1 条）。
    assert len(_SIGNATURE_CACHE) == 0

    # 第二次发布必须重算全部签名（缓存不再跨 reset 存活）。
    calls = {"count": 0}
    real_signature = qgis_mirror._feature_signature

    def counting_signature(feature):
        calls["count"] += 1
        return real_signature(feature)

    monkeypatch.setattr(qgis_mirror, "_feature_signature", counting_signature)
    mirror_snapshot_to_stack(stack, 1, MapRenderSnapshot(
        project_crs="EPSG:4326", layers=(_layer(),)))
    assert calls["count"] == 1


def test_stack_gc_purges_signature_and_raster_entries_with_ledger():
    stack = _Stack()
    mirror_snapshot_to_stack(stack, 1, MapRenderSnapshot(
        project_crs="EPSG:4326", layers=(_layer(),)))
    stack_id = id(stack)
    subject = (stack_id, "doc-mock")
    # raster 台账手工播种同栈条目（走与生产一致的键形）。
    _RASTER_LEDGER[(stack_id, "raster-x")] = qgis_mirror._RasterLedgerEntry(
        tokens=(1, 2, 3), qgis_id="qgis-raster-x")
    assert _SIGNATURE_CACHE.latest(subject) is not None
    assert qgis_mirror._MIRROR_LEDGER.get(subject) is not None

    del stack
    gc.collect()  # 弱引用回调 → _purge_stack_entries(stack_id)

    # 三表同剪：栈消亡后旧 token/签名/raster 条目全部失效。
    assert _SIGNATURE_CACHE.latest(subject) is None
    assert qgis_mirror._MIRROR_LEDGER.get(subject) is None
    assert (stack_id, "raster-x") not in _RASTER_LEDGER
