# -*- coding: utf-8 -*-
"""fields_sig 进镜像台账 no-op 判定（工程加载首发布先于角色恢复的自愈）。

场景：工程打开的首次组合发布发生在角色（metadata.role）恢复之前——
镜像层以无字段形态建出（memory provider 丢属性，分类 renderer 匹配
不到 → 图层不渲染，mock 相图重开不分色的根因）。角色到位后的第二次
组合发布必须因 fields_json 签名变化而真实重推（而不是 no-op），
桥侧补建字段后分类渲染恢复。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

import paleo_workbench.mapping.qgis_mirror as qgis_mirror
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.qgis_mirror import (
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
        """upsert_mirror_layer(..., data_revision: int, delta: str, fields_json: str) -> str"""
        self.calls.append({"doc_id": doc_id, "fields_json": fields_json,
                           "data_revision": data_revision})
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass


def _layer(*, role: str) -> MapLayerSnapshot:
    return MapLayerSnapshot(
        id="doc-mock", name="mock相图", layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=7, style_revision=1,
        features=(
            {"type": "Feature",
             "geometry": {"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
             "properties": {"facies_name": "扇三角洲", "__pwb_fid": "f1"}},
        ),
        style={}, visible=True, opacity=1.0,
        metadata={"role": role} if role else {},
    )


def test_fields_json_signature_change_forces_republish():
    stack = _Stack()
    reset_publish_ledger()

    mirror_snapshot_to_stack(
        stack, 1, MapRenderSnapshot(project_crs="EPSG:4326", layers=(_layer(role=""),)))
    first = [c for c in stack.calls if c["doc_id"] == "doc-mock"]
    assert len(first) == 1
    assert first[0]["fields_json"] == ""  # 角色未到位：无字段 schema

    stack.calls.clear()
    mirror_snapshot_to_stack(
        stack, 1, MapRenderSnapshot(project_crs="EPSG:4326", layers=(_layer(role="seismic_facies_prediction"),)))
    second = [c for c in stack.calls if c["doc_id"] == "doc-mock"]
    # 修订/样式/显示全未变，但 fields_json 出现 → 不得 no-op
    assert len(second) == 1, "fields_json 变化必须触发真实重推（否则镜像层永远无字段）"
    assert "facies_name" in second[0]["fields_json"]

    # 第三次（签名稳定）→ 回到 no-op
    stack.calls.clear()
    mirror_snapshot_to_stack(
        stack, 1, MapRenderSnapshot(project_crs="EPSG:4326", layers=(_layer(role="seismic_facies_prediction"),)))
    assert not [c for c in stack.calls if c["doc_id"] == "doc-mock"]


def test_fields_json_missing_role_still_noops_across_publishes():
    stack = _Stack()
    reset_publish_ledger()
    snapshot = MapRenderSnapshot(project_crs="EPSG:4326", layers=(_layer(role=""),))
    mirror_snapshot_to_stack(stack, 1, snapshot)
    stack.calls.clear()
    mirror_snapshot_to_stack(stack, 1, snapshot)
    assert not [c for c in stack.calls if c["doc_id"] == "doc-mock"]
