"""V10 transaction invariants: 单一 undo 单元矩阵 / delta 无副作用纪律 /
rollback 语义 / 无绕过路径（源码扫描）。

这些是 Milestone K 的不变量测试：任何新增编辑路径破坏其中一条即失败。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from paleo_workbench.mapping import vector_layer as vl
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

REPO = Path(__file__).resolve().parents[1]


def _ring(points):
    ring = [list(p) for p in points]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _layer(features):
    layer = VectorLayer(
        id="L", name="L",
        features=[VectorFeature(fid, geom, {"kind": "a"}) for fid, geom in features])
    return layer, layer.start_editing()


_SQUARE = {"type": "Polygon", "coordinates": [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])]}
_MULTI = {"type": "MultiPolygon", "coordinates": [
    [_ring([(0, 0), (10, 0), (10, 10), (0, 10)])],
    [_ring([(20, 0), (30, 0), (30, 10), (20, 10)])],
]}
_HOLE = {"type": "Polygon", "coordinates": [
    _ring([(0, 0), (10, 0), (10, 10), (0, 10)]),
    _ring([(4, 4), (6, 4), (6, 6), (4, 6)]),
]}


def test_every_command_type_has_delta_operation_mapping():
    """每个 session 命令类型串要么映射到 EditDelta 操作，要么是 compound
    （由宏平铺出成员 delta——唯一合法豁免）。"""
    from paleo_workbench.mapping.edit_delta import _COMMAND_OPERATION

    known_types = {
        "add_feature", "duplicate_feature", "delete_feature", "move_feature",
        "set_vertex", "insert_vertex", "delete_vertex", "change_attribute",
        "split_feature", "merge_features", "set_geometry", "add_ring",
        "delete_ring", "add_part", "delete_part", "move_part", "compound",
    }
    assert set(_COMMAND_OPERATION) <= known_types
    unmapped = known_types - set(_COMMAND_OPERATION) - {"compound"}
    assert not unmapped, f"command types without delta mapping: {unmapped}"


def test_one_action_one_undo_unit_matrix():
    """一个用户级动作 = 一个 undo 单元（各操作族的系统性矩阵）。"""
    # add / duplicate
    layer, session = _layer([("f1", _SQUARE)])
    session.add_feature(VectorFeature("f2", _SQUARE, {}))
    session.duplicate_feature("f1", "f3")
    assert len(session.undo_stack) == 2
    # vertex 三操作
    session.set_vertex("f1", (0, 0), (1.0, 1.0))
    session.insert_vertex("f1", (0, 2), (5.0, 10.0))
    session.delete_vertex("f1", (0, 2))
    assert len(session.undo_stack) == 5
    # geometry 级（顺序保持几何合法性：multipart 化后再做部件操作）
    session.set_geometry("f1", _HOLE)
    session.add_ring("f1", [(2, 2), (4, 2), (4, 4)])
    session.delete_ring("f1", 1)
    session.add_part("f1", _MULTI)
    session.move_part("f1", 1, 2.0, 0.0)
    session.move_feature("f1", 1.0, 1.0)
    session.change_attribute("f1", "kind", "b")
    session.delete_part("f1", {"type": "MultiPolygon",
                               "coordinates": [_MULTI["coordinates"][0]]})
    assert len(session.undo_stack) == 13
    # 每条都可单独撤销且类型串正确
    expected_types = [
        "delete_part", "change_attribute", "move_feature", "move_part",
        "add_part", "delete_ring", "add_ring", "set_geometry", "delete_vertex",
        "insert_vertex", "set_vertex", "duplicate_feature", "add_feature",
    ]
    assert [c.command_type for c in reversed(session.undo_stack)] == expected_types
    # 逐条 undo 全部可逆（working copy 恢复）
    for _ in range(13):
        assert session.undo()
    assert {f.feature_id for f in session.features()} == {"f1"}
    assert session.feature("f1").geometry["coordinates"][0][0] == (0.0, 0.0)


def test_undo_redo_produce_no_deltas():
    layer, session = _layer([("f1", _SQUARE)])
    before = len(session.deltas())
    session.set_vertex("f1", (0, 0), (1.0, 1.0))
    assert len(session.deltas()) == before + 1
    assert session.undo()
    assert session.redo()
    assert len(session.deltas()) == before + 1  # 导航不产生 delta


def test_rollback_voids_delta_journal_and_requires_full_rebuild():
    layer, session = _layer([("f1", _SQUARE)])
    session.set_vertex("f1", (0, 0), (1.0, 1.0))
    revision = session.revision
    assert session.deltas()
    session.rollback_changes()
    assert session.deltas() == ()
    assert layer.edit_session is None
    # changes_since(旧修订) 必须 None（全量重建语义），不是 ()
    new_session = layer.start_editing()
    assert new_session.changes_since(revision) is None


def test_macro_flattens_to_single_undo_and_keeps_deltas():
    layer, session = _layer([("f1", _MULTI)])
    session.begin_edit_command()
    session.move_part("f1", 0, 1.0, 0.0)
    session.move_part("f1", 1, 0.0, 1.0)
    session.change_attribute("f1", "kind", "b")
    session.end_edit_command()
    assert len(session.undo_stack) == 1
    assert session.undo_stack[0].command_type == "compound"
    # 成员 delta 保留（三个操作）
    assert [d.operation for d in session.deltas()] == [
        "replace_geometry", "replace_geometry", "update_attributes"]
    assert session.undo()
    assert len(session.undo_stack) == 0
    assert session.feature("f1").attributes["kind"] == "a"


# -- 无绕过路径：源码扫描（宿主侧零 QGIS 层直改） ---------------------------------

_FORBIDDEN_PYTHON_MUTATIONS = re.compile(
    r"\.(startEditing|changeGeometry|changeAttributeValue|commitChanges|"
    r"rollBack|deleteFeature|addFeature|deleteFeatures|addFeatures)\s*\("
)


def test_no_python_side_qgis_layer_mutation():
    """paleo_workbench/ 下不允许出现 QgsVectorLayer 编辑缓冲直改调用。

    桥在 vendored QGIS WITH_PYTHON=OFF 下本就不可从 Python 访问——本测试
    把这一架构事实钉死：将来任何人在宿主侧写 ``layer.startEditing()`` 或
    引入 qgis Python 绑定直改镜像层，本测试立即失败（Milestone K 不变量）。
    """
    offenders: list[str] = []
    for path in (REPO / "paleo_workbench").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(import|from)\s+qgis(\.|\s*$)", text, re.M):
            offenders.append(f"{path}: imports qgis python bindings")
            continue
        for match in _FORBIDDEN_PYTHON_MUTATIONS.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            offenders.append(f"{path}:{line_no}: {match.group(0)}")
    assert not offenders, "QGIS layer mutations outside the C++ bridge:\n" + "\n".join(offenders)


def test_native_side_mirror_writes_confined_to_bridge():
    """C++ 侧镜像层写路径只允许出现在 sanctioned 文件（upsert/provider 级
    刷新协议 + 捕获 scratch 层）。"""
    sanctioned = {
        "native/qgis_render_bridge/src/qgis_render_bridge.cpp",
        "native/qgis_render_bridge/src/map_stack_service.cpp",
    }
    offenders: list[str] = []
    for path in (REPO / "native").rglob("*.cpp"):
        rel = path.relative_to(REPO).as_posix()
        if rel in sanctioned:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"->(deleteFeatures|addFeatures|startEditing)\s*\(", text):
            offenders.append(rel)
    assert not offenders, f"mirror writes outside sanctioned bridge files: {offenders}"


# -- #1257：镜像几何变更后定位器必须失效（否则捕捉吸附过期几何） -------------------


def _mirror_full_ship_body() -> str:
    """截取 upsertMirrorLayer 内 `if (!delta_applied)` 起的分支正文。"""
    text = (REPO / "native" / "qgis_render_bridge" / "src"
            / "map_stack_service.cpp").read_text(encoding="utf-8")
    start = text.index("if (!delta_applied) {")
    return text[start:text.index("existing->updateExtents();", start)]


def test_full_ship_branch_invalidates_point_locators():
    """#1257：全量 truncate+add 绕过 layer dataChanged，必须显式失效定位器。

    锁定"全量分支在同一作用域内调用了 invalidateLocators"这一事实——
    否则 undo/redo、角色回退、schema 漂移后的全量重发会让 QgsPointLocator
    持续命中重建前的旧几何（捕捉吸附到已移动/已删除顶点）。
    """
    body = _mirror_full_ship_body()
    assert "truncate()" in body, "分支裁剪失效（未拿到全量重发正文）"
    assert "addFeatures(" in body, "分支裁剪失效（未拿到全量重发正文）"
    assert "invalidateLocators(" in body, (
        "全量重发分支必须调用 invalidateLocators（否则定位器索引不清）"
    )


def test_locator_invalidation_is_shared_not_inlined():
    """#1257：定位器失效逻辑集中在一处 helper，delta 与全量两条路径共用；
    禁止再次内联复制（平行实现会各自漂移）。"""
    text = (REPO / "native" / "qgis_render_bridge" / "src"
            / "map_stack_service.cpp").read_text(encoding="utf-8")
    header = (REPO / "native" / "qgis_render_bridge" / "src"
              / "map_stack_service.hpp").read_text(encoding="utf-8")
    assert "void QgisMapStack::invalidateLocators(" in text, "缺少 helper 定义"
    assert "void invalidateLocators(const QgsVectorLayer& layer);" in header, (
        "缺少 helper 声明"
    )
    # delta 路径经 helper（不再内联 locatorForLayer 循环）。唯一允许的
    # 另一处 locatorForLayer 是 set_snapping_config 的预热路径（不同职责：
    # 首次建索引，不经 hasIndex 守卫）。
    warmup = text.count("locatorForLayer(") - 1
    assert warmup == 1, (
        f"locatorForLayer 出现 {text.count('locatorForLayer(')} 次："
        "helper 内 1 次 + snapping 预热 1 次；多出即为内联复制"
    )
    # 两条镜像写路径都必须调用 helper
    assert text.count("invalidateLocators(") >= 3, (
        "helper 定义 + delta 调用 + 全量调用（至少 3 处）"
    )
