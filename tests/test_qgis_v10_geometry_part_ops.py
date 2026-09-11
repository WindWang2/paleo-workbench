# -*- coding: utf-8 -*-
"""V10 bridge geometry part operations: QgsGeometry::addPart / deletePart
semantics (single→multi promotion, per-type parts, fail-closed errors)。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


@pytest.fixture(scope="module")
def geometry():
    from qgis_render_bridge import geometry as g

    return g


_SQUARE = json.dumps({"type": "Polygon", "coordinates": [
    [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]})
# 与 _SQUARE 共边（x=10）的相邻方块：union 可 dissolve，collect 不 dissolve。
_PART = json.dumps({"type": "Polygon", "coordinates": [
    [[10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]]})
_LINE = json.dumps({"type": "LineString", "coordinates": [[0.0, 0.0], [5.0, 5.0]]})
_LINE_PART = json.dumps({"type": "LineString", "coordinates": [[5.0, 0.0], [9.0, 9.0]]})


def test_add_part_promotes_single_polygon_to_multi(geometry):
    result = json.loads(geometry.add_part(_SQUARE, _PART))
    assert result["type"] == "MultiPolygon"
    assert len(result["coordinates"]) == 2
    assert result["coordinates"][0][0][0] == [0.0, 0.0]
    assert result["coordinates"][1][0][0] == [10.0, 0.0]


def test_add_part_appends_to_existing_multipart(geometry):
    once = json.loads(geometry.add_part(_SQUARE, _PART))
    twice = json.loads(geometry.add_part(json.dumps(once), _PART))
    assert twice["type"] == "MultiPolygon"
    assert len(twice["coordinates"]) == 3


def test_add_part_on_line_promotes_to_multiline(geometry):
    result = json.loads(geometry.add_part(_LINE, _LINE_PART))
    assert result["type"] == "MultiLineString"
    assert len(result["coordinates"]) == 2


def test_add_part_rejects_mismatched_type(geometry):
    with pytest.raises(Exception):
        geometry.add_part(_SQUARE, _LINE)


def test_delete_part_removes_first_part(geometry):
    multi = json.loads(geometry.add_part(_SQUARE, _PART))
    result = json.loads(geometry.delete_part(json.dumps(multi), 0))
    assert len(result["coordinates"]) == 1
    assert result["coordinates"][0][0][0] == [10.0, 0.0]


def test_delete_part_rejects_out_of_range(geometry):
    multi = json.loads(geometry.add_part(_SQUARE, _PART))
    with pytest.raises(Exception):
        geometry.delete_part(json.dumps(multi), 5)
    with pytest.raises(Exception):
        geometry.delete_part(json.dumps(multi), -1)


def test_delete_part_rejects_singlepart(geometry):
    with pytest.raises(Exception):
        geometry.delete_part(_SQUARE, 0)


def test_delete_part_rejects_last_part(geometry):
    multi = json.loads(geometry.add_part(_SQUARE, _PART))
    one = json.loads(geometry.delete_part(json.dumps(multi), 1))
    with pytest.raises(Exception):
        # 删掉最后一个部件会得到空几何：fail-closed。
        geometry.delete_part(json.dumps(one), 0)


def test_collect_vs_union_distinction(geometry):
    # collect 不 dissolve：两个共享边的正方形合并成 2 部件 MultiPolygon，
    # 而 union 会融合为单一 Polygon（V10 collect 编辑命令的语义基础）。
    collected = json.loads(geometry.singlepart_to_multipart([_SQUARE, _PART]))
    assert collected["type"] == "MultiPolygon"
    assert len(collected["coordinates"]) == 2
    unioned = json.loads(geometry.union([_SQUARE, _PART]))
    assert unioned["type"] == "Polygon"
