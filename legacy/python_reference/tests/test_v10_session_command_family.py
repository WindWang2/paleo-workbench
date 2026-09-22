"""V10 session command family: duplicate / part ops / ring ops.

新命令族的完整事务语义（一个动作 = 一个 undo 单元 / delta 映射 / 审计 / 宏）。
part 几何的 QGIS 执行（add_part/delete_part）在 controller 层（桥可用时），
这里锁定 session 侧的命令/delta/undo 语义与守卫。
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.edit_delta import delta_from_command
from paleo_workbench.mapping.vector_layer import (
    VectorEditSession,
    VectorFeature,
    VectorLayer,
)


def _ring(points):
    ring = [list(p) for p in points]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


SQUARE = {"type": "Polygon", "coordinates": [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])]}
MULTI_SQUARE = {
    "type": "MultiPolygon",
    "coordinates": [
        [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])],
        [_ring([(20, 0), (30, 0), (30, 10), (20, 10)])],
    ],
}


def _layer(geometry, feature_id="f1", attributes=None):
    layer = VectorLayer(
        id="L", name="L", features=[VectorFeature(feature_id, geometry, attributes or {"kind": "a"})]
    )
    return layer, layer.start_editing()


def _last_delta(session: VectorEditSession):
    assert session.delta_journal, "expected at least one delta"
    return session.delta_journal[-1]


# -- duplicate ---------------------------------------------------------------


def test_duplicate_copies_geometry_and_attributes_with_new_id():
    layer, session = _layer(SQUARE)
    duplicate = session.duplicate_feature("f1", "f2")
    assert duplicate.feature_id == "f2"
    assert session.feature("f2").geometry == session.feature("f1").geometry
    assert session.feature("f2").attributes == session.feature("f1").attributes
    assert session.undo()
    assert "f2" not in {f.feature_id for f in session.features()}
    assert session.redo()
    assert "f2" in {f.feature_id for f in session.features()}


def test_duplicate_default_id_is_fresh_and_unique():
    layer, session = _layer(SQUARE)
    d1 = session.duplicate_feature("f1")
    d2 = session.duplicate_feature("f1")
    assert d1.feature_id != d2.feature_id != "f1"


def test_duplicate_delta_is_create_feature():
    layer, session = _layer(SQUARE)
    session.duplicate_feature("f1", "f2")
    delta = _last_delta(session)
    assert delta.operation == "create_feature"
    assert delta.feature_id == "f2"
    assert delta.after_geometry is not None


def test_duplicate_audit_command_type():
    layer, session = _layer(SQUARE)
    session.duplicate_feature("f1", "f2")
    assert session.audit_history()[-1]["command_type"] == "duplicate_feature"


# -- add_part / delete_part（几何由调用方计算，session 落命令） ---------------------


def _with_second_part(session, feature_id="f1"):
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])],
            [_ring([(20, 0), (30, 0), (30, 10), (20, 10)])],
        ],
    }
    session.add_part(feature_id, geometry)


def test_add_part_records_single_undo_unit():
    layer, session = _layer(SQUARE)
    _with_second_part(session)
    assert len(session.undo_stack) == 1
    assert session.undo_stack[0].command_type == "add_part"
    assert session.undo()
    assert session.feature("f1").geometry["type"] == "Polygon"
    assert session.redo()
    assert session.feature("f1").geometry["type"] == "MultiPolygon"


def test_delete_part_single_undo_unit():
    layer, session = _layer(MULTI_SQUARE)
    session.delete_part("f1", {"type": "MultiPolygon", "coordinates": [MULTI_SQUARE["coordinates"][0]]})
    coords = session.feature("f1").geometry["coordinates"]
    assert len(coords) == 1 and coords[0][0][0] == (0.0, 0.0)
    assert session.undo()
    assert len(session.feature("f1").geometry["coordinates"]) == 2


@pytest.mark.parametrize("command,expected_op", [
    ("add_part", "replace_geometry"),
    ("delete_part", "replace_geometry"),
    ("move_part", "replace_geometry"),
    ("add_ring", "replace_geometry"),
    ("delete_ring", "replace_geometry"),
    ("duplicate_feature", "create_feature"),
])
def test_part_and_ring_delta_operation_mapping(command, expected_op):
    # 经由真实命令构造验证映射表（不重复 _COMMAND_OPERATION 字面量断言的
    # 那些既有 V7 契约，只锁 V10 新条目）。
    layer, session = _layer(MULTI_SQUARE)
    before = session.feature("f1")
    if command == "add_part":
        session.add_part("f1", MULTI_SQUARE)
    elif command == "delete_part":
        session.delete_part("f1", {"type": "MultiPolygon", "coordinates": [MULTI_SQUARE["coordinates"][0]]})
    elif command == "move_part":
        session.move_part("f1", 1, 5.0, 0.0)
    elif command == "duplicate_feature":
        session.duplicate_feature("f1", "f9")
        return  # create_feature 已在 duplicate 测试锁定
    else:
        # ring 命令在 Polygon 上执行
        layer2 = VectorLayer(id="P", name="P", features=[VectorFeature("p1", SQUARE)])
        s2 = layer2.start_editing()
        if command == "add_ring":
            s2.add_ring("p1", [(4, 4), (6, 4), (6, 6)])
        else:
            hole = {
                "type": "Polygon",
                "coordinates": [SQUARE["coordinates"][0], _ring([(4, 4), (6, 4), (6, 6), (4, 6)])],
            }
            s2.set_geometry("p1", hole)
            s2.delete_ring("p1", 1)
        delta = s2.delta_journal[-1]
        assert delta.operation == expected_op
        return
    delta = _last_delta(session)
    assert delta.operation == expected_op


# -- move_part ----------------------------------------------------------------


def test_move_part_translates_only_target_part():
    layer, session = _layer(MULTI_SQUARE)
    session.move_part("f1", 1, 5.0, 2.0)
    part0 = session.feature("f1").geometry["coordinates"][0]
    part1 = session.feature("f1").geometry["coordinates"][1]
    assert part0[0][0] == (0.0, 0.0)
    assert part1[0][0] == (25.0, 2.0)
    assert session.undo()
    assert session.feature("f1").geometry["coordinates"][1][0][0] == (20.0, 0.0)


def test_move_part_rejects_singlepart_geometry():
    layer, session = _layer(SQUARE)
    with pytest.raises(ValueError, match="multipart"):
        session.move_part("f1", 0, 1.0, 1.0)


def test_move_part_rejects_out_of_range_index():
    layer, session = _layer(MULTI_SQUARE)
    with pytest.raises(IndexError):
        session.move_part("f1", 2, 1.0, 1.0)


def test_move_part_on_multipoint_and_multiline():
    layer = VectorLayer(
        id="M",
        name="M",
        features=[
            VectorFeature("mp", {"type": "MultiPoint", "coordinates": [[0, 0], [10, 10]]}),
            VectorFeature("ml", {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[5, 5], [6, 6]]]}),
        ],
    )
    session = layer.start_editing()
    session.move_part("mp", 0, 1.0, 1.0)
    assert list(session.feature("mp").geometry["coordinates"][0]) == [1.0, 1.0]
    session.move_part("ml", 1, -1.0, 0.0)
    assert [list(p) for p in session.feature("ml").geometry["coordinates"][1]] == [[4.0, 5.0], [5.0, 6.0]]


# -- ring 命令（接线前的回归锁定） -----------------------------------------------


def test_add_ring_auto_closes_and_undo():
    layer, session = _layer(SQUARE)
    session.add_ring("f1", [(4, 4), (6, 4), (6, 6)])
    rings = session.feature("f1").geometry["coordinates"]
    assert len(rings) == 2
    assert rings[1][0] == rings[1][-1] == (4.0, 4.0)
    assert session.undo()
    assert len(session.feature("f1").geometry["coordinates"]) == 1


def test_delete_ring_interior_only():
    layer, session = _layer(
        {"type": "Polygon", "coordinates": [SQUARE["coordinates"][0], _ring([(4, 4), (6, 4), (6, 6), (4, 6)])]}
    )
    session.delete_ring("f1", 1)
    assert len(session.feature("f1").geometry["coordinates"]) == 1
    with pytest.raises(ValueError):
        session.delete_ring("f1", 0)


# -- 宏：一个手势 = 一个 undo 单元（含新命令） ------------------------------------


def test_part_ops_inside_macro_form_single_undo_unit():
    layer, session = _layer(MULTI_SQUARE)
    session.begin_edit_command()
    session.move_part("f1", 0, 1.0, 0.0)
    session.move_part("f1", 1, 0.0, 1.0)
    session.end_edit_command()
    assert len(session.undo_stack) == 1
    assert session.undo_stack[0].command_type == "compound"
    deltas = session.deltas()
    assert deltas[-1].operation == "replace_geometry"
    assert deltas[-2].operation == "replace_geometry"
    assert session.undo()
    assert session.feature("f1").geometry["coordinates"][0][0][0] == (0.0, 0.0)


def test_duplicate_plus_part_macro_single_undo():
    layer, session = _layer(SQUARE)
    session.begin_edit_command()
    duplicate = session.duplicate_feature("f1", "f2")
    session.add_part("f2", MULTI_SQUARE)
    session.end_edit_command()
    assert len(session.undo_stack) == 1
    assert session.undo()
    assert {f.feature_id for f in session.features()} == {"f1"}
    assert session.feature("f1").geometry["type"] == "Polygon"
