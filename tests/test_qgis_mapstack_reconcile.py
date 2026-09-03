"""M2 Task 2: 增量镜像——未变图层的 QgsMapLayer 对象与树节点在 re-mirror 后保持不变。"""
import json

import pytest

pytest.importorskip("PySide6")

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
         "properties": {"name": "A1"}}
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_upsert_reuses_layer_object(stack):
    a = stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                                  json.dumps(_FC), "", "", "", True, 1.0)
    b = stack.upsert_mirror_layer("doc-b", "边界", "Point", "EPSG:4326",
                                  json.dumps(_FC), "", "", "", True, 1.0)
    a2 = stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                                   json.dumps(_FC), "", "", "", False, 0.8)
    assert a2 == a  # 同一镜像复用同一 QgsVectorLayer
    assert b != a


def test_remove_except_and_order(stack):
    ids = {}
    for doc in ("doc-1", "doc-2", "doc-3"):
        ids[doc] = stack.upsert_mirror_layer(doc, doc, "Point", "EPSG:4326",
                                             json.dumps(_FC), "", "", "", True, 1.0)
    stack.set_mirror_layer_order(["doc-3", "doc-1", "doc-2"])
    assert stack.mirror_order_top_first() == ["doc-3", "doc-1", "doc-2"]
    stack.remove_mirror_layers_except(["doc-1"])
    assert stack.project_layer_count() == 1
    stack.remove_mirror_layers_except([])
    assert stack.project_layer_count() == 0


def test_visibility_without_rebuild(stack):
    qid = stack.upsert_mirror_layer("doc-v", "v", "Point", "EPSG:4326",
                                    json.dumps(_FC), "", "", "", True, 1.0)
    stack.set_mirror_layer_visibility("doc-v", False)
    assert stack.mirror_layer_visibility("doc-v") is False
    stack.set_mirror_layer_visibility("doc-v", True)
    assert stack.mirror_layer_visibility("doc-v") is True
    # 对象未被替换
    assert stack.upsert_mirror_layer("doc-v", "v", "Point", "EPSG:4326",
                                     json.dumps(_FC), "", "", "", True, 1.0) == qid
