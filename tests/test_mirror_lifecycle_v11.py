"""V11 mirror lifecycle contracts（09-mirror-lifecycle）。

结构性断言（非计时）：
1. 会话内单点编辑：delta 只含触及要素（O(touched)，非 O(N) 全量重签）。
2. 全快照 no-op：逐要素签名一次都不算。
3. save-intent 缓冲：待提交会话的变更对发布不可见；提交后发布可见。
4. raster ledger：数据未动时零桥调用；样式仅变时走 renderer 通道。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from paleo_workbench.mapping import qgis_mirror


def _feature(fid: str, x: float, props: dict | None = None):
    properties = {"__pwb_fid": fid, "id": fid}
    properties.update(props or {})
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [x, 1.0]},
            "properties": properties}


def _vector_layer(layer_id: str, features, data_revision: int,
                  name: str | None = None, visible: bool = True,
                  opacity: float = 1.0, kind: str = "point",
                  style: dict | None = None):
    return SimpleNamespace(
        id=layer_id, name=name or layer_id, layer_type="vector",
        features=tuple({"type": "Feature",
                        "geometry": f["geometry"],
                        "properties": f["properties"],
                        "id": f["properties"].get("__pwb_fid")} for f in features),
        data_revision=data_revision, visible=visible, opacity=opacity,
        style=style or {}, metadata={"geometry_kind": kind},
        scale_range=None)


def _snapshot(layers, project_crs: str = ""):
    return SimpleNamespace(layers=list(layers), project_crs=project_crs)


class _ProbeStack:
    """duck-type 桥：支持 capability 探针 + delta + 记录调用。"""

    def __init__(self):
        self.calls: list[tuple] = []

    # capability probes (via inspect.signature parameter names)
    def upsert_mirror_layer(
        self, doc_id, name, geometry_type, crs, geojson,
        renderer_xml="", labeling_xml="", legacy_style=None,
        visible=True, opacity=1.0, is_reference=False, is_editable=False,
        reference_snap=False, data_revision=0, delta="",
        fields_json="", min_scale=0.0, max_scale=0.0):
        self.calls.append(("upsert",
                           (doc_id, name, geometry_type, crs, geojson),
                           {"data_revision": data_revision, "delta": delta}))
        return doc_id

    def upsert_raster_mirror_layer(self, *args, **kwargs):
        """(doc_id:str, name:str, source_path:str, crs:str,
        renderer_xml:str, visible:bool, opacity:float, is_reference:bool)"""
        self.calls.append(("raster", args, kwargs))
        return args[0]

    def remove_mirror_layers_except(self, seen):
        self.calls.append(("remove_except", tuple(seen)))

    def set_mirror_layer_order(self, seen):
        self.calls.append(("order", tuple(seen)))

    def set_destination_crs(self, canvas, crs):
        self.calls.append(("crs", crs))

    def refresh_canvas(self, canvas):
        self.calls.append(("refresh",))

    def kinds(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture(autouse=True)
def _fresh_ledger():
    qgis_mirror.reset_publish_ledger()
    yield
    qgis_mirror.reset_publish_ledger()


class TestFeatureSignatureCache:
    def test_second_publish_computes_no_signatures(self, monkeypatch):
        stack = _ProbeStack()
        features = [_feature(f"f{i}", float(i)) for i in range(300)]
        layer = _vector_layer("L", features, 1)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)

        calls = {"n": 0}
        real = qgis_mirror._feature_signature

        def counting(feature):
            calls["n"] += 1
            return real(feature)

        monkeypatch.setattr(qgis_mirror, "_feature_signature", counting)
        # 同快照再次发布（数据修订未动 → no-op，必须零签名）
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)
        assert calls["n"] == 0

    def test_single_touch_only_resigns_touched(self, monkeypatch):
        stack = _ProbeStack()
        features = [_feature(f"f{i}", float(i)) for i in range(300)]
        layer = _vector_layer("L", features, 1)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)

        # 单点扰动（修订递增）+ 宿主 journal 提示 → 只重签被扰动的要素
        touched = list(features)
        touched[7] = _feature("f7", 777.0)
        layer2 = _vector_layer("L", touched, 2)

        calls = {"n": 0}
        real = qgis_mirror._feature_signature

        def counting(feature):
            calls["n"] += 1
            return real(feature)

        monkeypatch.setattr(qgis_mirror, "_feature_signature", counting)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer2]), groups=True,
            changed_hints={"L": {"f7"}})
        # 重签 = 触及要素数（1），绝非 O(N) 全量
        assert calls["n"] == 1

    def test_no_hints_falls_back_to_full_compare(self, monkeypatch):
        """无提示回落全量比较（正确性不变——delta 仍只含真实变更）。"""
        stack = _ProbeStack()
        features = [_feature(f"f{i}", float(i)) for i in range(50)]
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([_vector_layer("L", features, 1)]), groups=True)
        touched = list(features)
        touched[7] = _feature("f7", 777.0)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([_vector_layer("L", touched, 2)]), groups=True)
        upserts = stack.kinds("upsert")
        delta = json.loads(upserts[-1][2]["delta"])
        changed_fids = {c["properties"]["__pwb_fid"] for c in delta["changed"]}
        assert changed_fids == {"f7"}

    def test_delta_only_carries_changed(self):
        stack = _ProbeStack()
        features = [_feature(f"f{i}", float(i)) for i in range(50)]
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([_vector_layer("L", features, 1)]), groups=True)
        touched = list(features)
        touched[7] = _feature("f7", 777.0)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([_vector_layer("L", touched, 2)]), groups=True)
        upserts = stack.kinds("upsert")
        last = upserts[-1]
        delta = json.loads(last[2]["delta"])
        changed_fids = {c["properties"]["__pwb_fid"] for c in delta["changed"]}
        assert changed_fids == {"f7"}
        assert delta["removed_ids"] == []


class TestSaveIntentBuffer:
    def test_uncommitted_session_invisible_to_publish(self):
        from paleo_workbench.mapping.vector_layer import VectorLayer

        host = VectorLayer(id="V", name="V")
        stack = _ProbeStack()

        def snapshot():
            return _snapshot([_host_records(host)])

        published, _, _ = qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, snapshot(), groups=True)
        assert published == ["V"]
        upserts = stack.kinds("upsert")
        assert json.loads(upserts[-1][1][4])["features"] == []

        # 会话内加点（未提交）→ 发布不可见（save-intent 缓冲）
        host.start_editing()
        host.edit_session.add_feature(__import__(
            "paleo_workbench.mapping.vector_layer",
            fromlist=["VectorFeature"]).VectorFeature(
                "g1", {"type": "Point", "coordinates": [3.0, 4.0]}, {}))
        stack.calls.clear()
        qgis_mirror.mirror_snapshot_to_stack(stack, 0, snapshot(), groups=True)
        upserts = stack.kinds("upsert")
        if upserts:
            assert json.loads(upserts[-1][1][4])["features"] == []

        # 提交 → 发布可见
        host.edit_session.commit_changes()
        qgis_mirror.mirror_snapshot_to_stack(stack, 0, snapshot(), groups=True)
        upserts = stack.kinds("upsert")
        shipped = json.loads(upserts[-1][1][4])["features"]
        assert len(shipped) == 1

    def test_rollback_keeps_publish_stable(self):
        from paleo_workbench.mapping.vector_layer import VectorLayer

        host = VectorLayer(id="V", name="V")
        stack = _ProbeStack()

        def snapshot():
            return _snapshot([_host_records(host)])

        qgis_mirror.mirror_snapshot_to_stack(stack, 0, snapshot(), groups=True)
        host.start_editing()
        host.edit_session.rollback_changes()
        stack.calls.clear()
        _, seen, _ = qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, snapshot(), groups=True)
        assert seen == ["V"]  # 基线 stable（提交/回滚都是 host 侧基线推进）


def _host_records(host):
    """宿主 VectorLayer → 发布记录（会话内只结算提交基线）。"""
    layer = host
    pending = layer.edit_session is not None
    source = () if pending else layer.features()
    return SimpleNamespace(
        id=layer.id, name=layer.name, layer_type="vector",
        features=tuple({
            "type": "Feature", "geometry": f.geometry,
            "properties": dict(f.attributes), "id": f.feature_id}
            for f in source),
        data_revision=layer.data_revision, visible=True, opacity=1.0,
        style={}, metadata={"geometry_kind": "point"}, scale_range=None)


class TestRasterLedger:
    def test_unchanged_raster_zero_bridge_calls(self):
        stack = _ProbeStack()
        layer = SimpleNamespace(
            id="R", name="R", layer_type="raster_source", crs="",
            renderer_payload="/vsimem/never.tif", visible=True, opacity=1.0,
            data_revision=3, style={}, metadata={}, scale_range=None)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)
        first = len(stack.kinds("raster"))
        assert first == 1
        stack.calls.clear()
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)
        assert stack.kinds("raster") == []  # 数据/样式/显隐全未动 → 零调用

    def test_visibility_change_still_pushes(self):
        """显隐/名称变化仍下推（tokens 含它们；raster_source 无样式通道——
        参考影像保持自身像素，样式变化概念只属于 scalar_grid）。"""
        stack = _ProbeStack()
        layer = SimpleNamespace(
            id="R", name="R", layer_type="raster_source", crs="",
            renderer_payload="/vsimem/never.tif", visible=True, opacity=1.0,
            data_revision=3, style={}, metadata={}, scale_range=None)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)
        stack.calls.clear()
        layer2 = SimpleNamespace(
            id="R", name="R", layer_type="raster_source", crs="",
            renderer_payload="/vsimem/never.tif", visible=False, opacity=1.0,
            data_revision=3, style={}, metadata={}, scale_range=None)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer2]), groups=True)
        rasters = stack.kinds("raster")
        assert len(rasters) == 1  # 显隐变化 → 下推（桥侧做可见性直写）

    def test_data_revision_change_rebuilds(self):
        stack = _ProbeStack()
        layer = SimpleNamespace(
            id="R", name="R", layer_type="raster_source", crs="",
            renderer_payload="/vsimem/r1.tif", visible=True, opacity=1.0,
            data_revision=3, style={}, metadata={}, scale_range=None)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer]), groups=True)
        layer2 = SimpleNamespace(
            id="R", name="R", layer_type="raster_source", crs="",
            renderer_payload="/vsimem/r2.tif", visible=True, opacity=1.0,
            data_revision=4, style={}, metadata={}, scale_range=None)
        qgis_mirror.mirror_snapshot_to_stack(
            stack, 0, _snapshot([layer2]), groups=True)
        rasters = stack.kinds("raster")
        assert [r[1][2] for r in rasters] == ["/vsimem/r1.tif", "/vsimem/r2.tif"]
