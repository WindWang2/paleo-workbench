"""V10 vertex ring-closure invariants + adversarial vertex-path addressing.

锁定 session 层（VectorEditSession）的顶点三操作语义：

- 闭合 ring（Polygon/MultiPolygon，首==尾，>=4 点）的 set/insert/delete
  必须维持首==尾（RFC 7946 闭环不变量）——这是 V10 修复的权威级缺陷：
  此前拖动 ring 首顶点会留下不闭合的权威几何。
- 闭合 LineString 的首尾重合是独立顶点：移动一端不得带动另一端。
- 最少顶点守卫（ring >=3 真实顶点 / line >=2 / multipoint >=1）。
- 路径寻址对抗：内环、MultiPolygon 深嵌套、越界路径拒绝。

注意：``VectorFeature`` 冻结坐标为 tuple——所有值比较用 tuple。
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _layer_with(geometry, feature_id="f1", attributes=None):
    layer = VectorLayer(id="L", name="L", features=[VectorFeature(feature_id, geometry, attributes or {})])
    return layer, layer.start_editing()


def _ring(points):
    ring = [list(p) for p in points]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


SQUARE = {"type": "Polygon", "coordinates": [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])]}
SQUARE_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        _ring([(0, 0), (10, 0), (10, 10), (0, 10)]),
        _ring([(4, 4), (6, 4), (6, 6), (4, 6)]),
    ],
}
MULTI_SQUARE = {
    "type": "MultiPolygon",
    "coordinates": [
        [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])],
        [_ring([(20, 0), (30, 0), (30, 10), (20, 10)])],
    ],
}
CLOSED_LINE = {"type": "LineString", "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]]}
OPEN_LINE = {"type": "LineString", "coordinates": [[0, 0], [5, 0], [5, 5]]}


def _ring_of(session, feature_id="f1", ring=0, part=None):
    coords = session.feature(feature_id).geometry["coordinates"]
    return coords[part][ring] if part is not None else coords[ring]


# -- set_vertex 闭环维护 -------------------------------------------------------


@pytest.mark.parametrize("index", [0, 4])  # 首顶点 / 闭合重复点
def test_set_first_or_closing_vertex_keeps_ring_closed(index):
    layer, session = _layer_with(SQUARE)
    session.set_vertex("f1", (0, index), (2.5, -1.5))
    ring = _ring_of(session)
    assert ring[index] == (2.5, -1.5)
    assert ring[0] == ring[-1] == (2.5, -1.5)
    assert session.feature("f1").geometry["type"] == "Polygon"


def test_set_interior_ring_vertex_keeps_closure():
    layer, session = _layer_with(SQUARE_WITH_HOLE)
    session.set_vertex("f1", (1, 0), (5.0, 3.0))
    hole = _ring_of(session, ring=1)
    assert hole[0] == (5.0, 3.0)
    assert hole[0] == hole[-1]


def test_set_multipart_vertex_closure_both_parts():
    layer, session = _layer_with(MULTI_SQUARE)
    session.set_vertex("f1", (1, 0, 4), (25.0, -2.0))
    ring = _ring_of(session, ring=0, part=1)
    assert ring[4] == (25.0, -2.0)
    assert ring[0] == ring[-1] == (25.0, -2.0)
    # 未触及的 part 不受影响。
    assert _ring_of(session, ring=0, part=0)[0] == (0.0, 0.0)


def test_set_vertex_closed_linestring_endpoints_independent():
    layer, session = _layer_with(CLOSED_LINE)
    session.set_vertex("f1", (0,), (7.0, 0.0))
    coords = session.feature("f1").geometry["coordinates"]
    assert coords[0] == (7.0, 0.0)
    assert coords[-1] == (0.0, 0.0)  # 闭合线的尾点是独立顶点，不跟随


def test_set_vertex_undo_restores_closed_ring():
    layer, session = _layer_with(SQUARE)
    session.set_vertex("f1", (0, 0), (2.5, -1.5))
    assert session.undo()
    ring = _ring_of(session)
    assert ring[0] == ring[-1] == (0.0, 0.0)
    assert session.redo()
    assert _ring_of(session)[0] == (2.5, -1.5)


# -- insert_vertex 闭环维护 ----------------------------------------------------


def test_insert_at_ring_start_retargets_closing_duplicate():
    layer, session = _layer_with(SQUARE)
    session.insert_vertex("f1", (0, 0), (-3.0, -3.0))
    ring = _ring_of(session)
    assert len(ring) == 6
    assert ring[0] == (-3.0, -3.0) and ring[-1] == (-3.0, -3.0)
    assert ring[1] == (0.0, 0.0)


def test_insert_before_closing_duplicate_stays_closed():
    layer, session = _layer_with(SQUARE)
    session.insert_vertex("f1", (0, 4), (5.0, 10.5))
    ring = _ring_of(session)
    assert len(ring) == 6
    assert ring[-2] == (5.0, 10.5)
    assert ring[0] == ring[-1] == (0.0, 0.0)


def test_insert_append_position_clamped_to_before_closing():
    # index==len（闭合点之后）应归一到闭合点之前，不打开 ring。
    layer, session = _layer_with(SQUARE)
    session.insert_vertex("f1", (0, 5), (5.0, -0.5))
    ring = _ring_of(session)
    assert ring[-2] == (5.0, -0.5)
    assert ring[0] == ring[-1] == (0.0, 0.0)


def test_insert_middle_of_ring_unaffected_closure():
    layer, session = _layer_with(SQUARE)
    session.insert_vertex("f1", (0, 2), (10.5, 5.0))
    ring = _ring_of(session)
    assert ring[2] == (10.5, 5.0)
    assert ring[0] == ring[-1]


def test_insert_on_open_line_no_closure_logic():
    layer, session = _layer_with(OPEN_LINE)
    session.insert_vertex("f1", (1,), (2.5, 0.0))
    coords = session.feature("f1").geometry["coordinates"]
    assert [list(c) for c in coords] == [[0.0, 0.0], [2.5, 0.0], [5.0, 0.0], [5.0, 5.0]]


# -- delete_vertex 闭环维护 + 最少顶点守卫 ---------------------------------------


def test_delete_ring_start_moves_closing_to_new_first():
    layer, session = _layer_with(SQUARE)
    session.delete_vertex("f1", (0, 0))
    ring = _ring_of(session)
    assert len(ring) == 4
    assert ring[0] == ring[-1] == (10.0, 0.0)


def test_delete_closing_duplicate_removes_last_real_vertex():
    layer, session = _layer_with(SQUARE)
    session.delete_vertex("f1", (0, 4))
    ring = _ring_of(session)
    # 原 ring: [0,0],[10,0],[10,10],[0,10],[0,0] → 删除末位真实顶点 [0,10]
    assert len(ring) == 4
    assert ring[0] == ring[-1] == (0.0, 0.0)
    assert (0.0, 10.0) not in ring


def test_delete_interior_ring_vertex():
    layer, session = _layer_with(SQUARE_WITH_HOLE)
    session.delete_vertex("f1", (1, 1))
    hole = _ring_of(session, ring=1)
    assert len(hole) == 4  # 3 真实 + 闭合
    assert hole[0] == hole[-1]


def test_delete_below_min_ring_vertices_rejected():
    triangle = {"type": "Polygon", "coordinates": [_ring([(0, 0), (4, 0), (0, 4)])]}
    layer, session = _layer_with(triangle)
    with pytest.raises(ValueError, match="at least three"):
        session.delete_vertex("f1", (0, 0))
    # 拒绝不产生命令/修订漂移（working copy 未变）。
    assert session.undo_stack == []
    assert session.feature("f1").geometry["coordinates"][0][0] == (0.0, 0.0)


def test_delete_line_below_two_vertices_rejected():
    layer, session = _layer_with({"type": "LineString", "coordinates": [[0, 0], [5, 0]]})
    with pytest.raises(ValueError, match="at least two"):
        session.delete_vertex("f1", (0,))


def test_delete_multipart_last_point_rejected():
    layer, session = _layer_with({"type": "MultiPoint", "coordinates": [[1, 1]]})
    with pytest.raises(ValueError, match="at least one"):
        session.delete_vertex("f1", (0,))


# -- 对抗寻址 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "geometry,path",
    [
        (SQUARE, (0, 5)),
        (SQUARE, (2, 0)),
        (SQUARE_WITH_HOLE, (1, 5)),
        (MULTI_SQUARE, (2, 0, 0)),
        (MULTI_SQUARE, (0, 1, 0)),
        (OPEN_LINE, (3,)),
        ({"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]}, (0, 2)),
        ({"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]}, (1, 0)),
        ({"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]}, (2,)),
        ({"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]}, (0, 0)),
    ],
)
def test_out_of_range_paths_rejected(geometry, path):
    layer, session = _layer_with(geometry)
    with pytest.raises((IndexError, ValueError)):
        session.set_vertex("f1", path, (99.0, 99.0))
    with pytest.raises((IndexError, ValueError)):
        session.delete_vertex("f1", path)


def test_point_geometry_empty_path_whole_coordinate():
    layer, session = _layer_with({"type": "Point", "coordinates": [3.0, 4.0]})
    session.set_vertex("f1", (), (8.0, 9.0))
    assert list(session.feature("f1").geometry["coordinates"]) == [8.0, 9.0]


def test_multipart_vertex_drag_does_not_touch_other_part():
    layer, session = _layer_with(MULTI_SQUARE)
    session.set_vertex("f1", (0, 0, 1), (12.0, 0.0))
    part0 = _ring_of(session, ring=0, part=0)
    part1 = _ring_of(session, ring=0, part=1)
    assert part0[1] == (12.0, 0.0)
    # part1 原样：首顶点 (20,0)、第二顶点 (30,0) 均未被触碰。
    assert part1[0] == (20.0, 0.0)
    assert part1[1] == (30.0, 0.0)


# -- 提交链：闭环几何落库 --------------------------------------------------------


def test_committed_geometry_stays_closed_after_vertex_edit():
    layer, session = _layer_with(SQUARE, attributes={"facies_name": "delta"})
    session.set_vertex("f1", (0, 0), (2.5, -1.5))
    session.commit_changes()
    ring = layer.feature("f1").geometry["coordinates"][0]
    assert ring[0] == (2.5, -1.5)
    assert ring[0] == ring[-1]
