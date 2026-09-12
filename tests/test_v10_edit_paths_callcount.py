"""V10 edit-path call-count guards（08-performance §D 的落地）。

以调用计数（非 wall-clock）锁定：
- ToolContext 选集事实单趟扫描 + memo（同一状态重复构建不重扫）。
- 宏内批量命令只产生一次修订/一个 undo 单元。
"""

from __future__ import annotations

from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _layer(n_features: int) -> tuple[VectorLayer, object]:
    features = [
        VectorFeature(
            f"f{i}",
            {"type": "MultiPolygon", "coordinates": [
                [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
                [[[2.0, 0.0], [3.0, 0.0], [3.0, 1.0], [2.0, 0.0]]],
            ]},
            {"kind": "a"},
        )
        for i in range(n_features)
    ]
    layer = VectorLayer(id="L", name="L", features=features)
    return layer, layer.start_editing()


def _counting(session):
    """就地包一层计数（保持对象身份——memo 键含 id(session)，换包装器
    会假装 miss）。"""
    counter = {"calls": 0}
    original = session.feature

    def counted(feature_id):
        counter["calls"] += 1
        return original(feature_id)

    session.feature = counted
    return counter


def test_selection_facts_single_pass_over_selection():
    """两个选集事实（multipart 计数 + collect 就绪）合并为一趟扫描：
    session.feature 调用数 == 选集大小（而非 2×）。"""
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    layer, session = _layer(200)
    layer.set_selection(layer.feature_ids())
    counting = _counting(session)

    class _Host:
        _selection_facts_cache_store = {}

    facts = CompositeEditController._selection_geometry_facts(
        _Host(), layer, session)
    assert facts == (200, False)  # 全 multipart：计数满、collect 不可用
    assert counting["calls"] == 200  # 单趟


def test_selection_facts_memoized_across_rebuilds():
    """同一 (会话修订, 选集内容) 的重复构建不再扫描：0 次新增 feature 调用。"""
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    layer, session = _layer(100)
    layer.set_selection(layer.feature_ids())

    class _Host:
        _selection_facts_cache_store = {}

    first = CompositeEditController._selection_geometry_facts(_Host(), layer, session)
    assert first == (100, False)
    counting = _counting(session)
    second = CompositeEditController._selection_geometry_facts(_Host(), layer, session)
    assert second == first
    assert counting["calls"] == 0  # memo 命中

    # 修订漂移（新命令）后 memo 失效 → 重新扫描一次。
    session.set_vertex("f0", (0, 0, 0), (0.5, 0.5))
    counting["calls"] = 0  # set_vertex 自身的 feature 读取不计
    third = CompositeEditController._selection_geometry_facts(_Host(), layer, session)
    assert third[0] == 100
    assert counting["calls"] == 100


def test_macro_batch_bumps_revision_once():
    """批量 explode 形态（宏内 N 条 split）= 一次修订 + 一个 undo 单元。
    会话级已测 compound；这里锁修订计数（镜像增量消费方的水位线）。"""
    layer, session = _layer(3)
    session.begin_edit_command()
    for feature_id in layer.feature_ids():
        geometry = session.feature(feature_id).as_record()["geometry"]
        parts = geometry["coordinates"]
        session.set_geometry(feature_id, {"type": "Polygon", "coordinates": [parts[0]]})
    session.end_edit_command()
    assert len(session.undo_stack) == 1
    assert session.revision == 1  # 宏整体只 bump 一次


def test_duplicate_explicit_id_collision_rejected():
    """显式 id 冲突拒绝（review-2 #2）：不再可能用 undo 删掉既有要素。"""
    layer, session = _layer(1)
    try:
        session.duplicate_feature("f0", new_feature_id="f0")
        raised = False
    except ValueError:
        raised = True
    assert raised
    assert len(session.undo_stack) == 0
    assert len(session.features()) == 1


# -- 08-performance §D：native vertex 三操作的手势级契约 -------------------------


def test_native_vertex_gestures_are_single_command_and_revision():
    """native vertex 三操作（move / insert / delete）每手势恰：
    1 个 undo 单元 + 1 次 revision bump（08 §D）。

    一个用户手势 = 一个宏 = 一个 undo 单元（07 §B.1）；若实现漏开宏，
    三操作会各自留下独立 undo 项并多次 bump。
    """
    from paleo_workbench.mapping.map_tools import VertexTool

    layer, session = _layer(1)
    tool = VertexTool(session, identify_vertex=lambda _p: None)

    # move：拖动 ring 上一个顶点（path 指向外环第 1 个真实顶点）。
    before_rev = session.revision
    layer.set_selection(["f0"])
    assert tool.commit_vertex_move("f0", (0, 0, 1), (5.0, 5.0)) is True
    assert len(session.undo_stack) == 1, "move 应为 1 个 undo 单元"
    assert session.revision == before_rev + 1, "move 应恰 bump 1 次"

    # insert：双击段上插点。
    before_rev = session.revision
    assert tool.commit_vertex_insert("f0", (0, 0, 1), (9.0, 9.0)) is True
    assert len(session.undo_stack) == 2, "insert 应新增 1 个 undo 单元"
    assert session.revision == before_rev + 1, "insert 应恰 bump 1 次"

    # delete：删一个真实顶点。
    before_rev = session.revision
    assert tool.commit_vertex_delete("f0", (0, 0, 1)) is True
    assert len(session.undo_stack) == 3, "delete 应新增 1 个 undo 单元"
    assert session.revision == before_rev + 1, "delete 应恰 bump 1 次"


def test_native_vertex_gesture_does_not_scan_all_features():
    """native vertex 手势只读被编辑的那一个要素：session.feature 调用数
    与要素总数无关（08 §C3：单要素几何操作，无层扫描）。"""
    from paleo_workbench.mapping.map_tools import VertexTool

    layer, session = _layer(500)
    tool = VertexTool(session, identify_vertex=lambda _p: None)
    counting = _counting(session)
    assert tool.commit_vertex_insert("f0", (0, 0, 1), (9.0, 9.0)) is True
    # insert 路径的 feature 读取上界：begin/end 宏 + edit_source 不读要素，
    # 唯一读取是被编辑要素本身（实现若有额外全量扫描会立刻突破该界）。
    assert counting["calls"] <= 4, (
        f"insert 手势读了 {counting['calls']} 次要素（应只读被编辑的 1 个）"
    )


def _quad_ring_layer() -> tuple[VectorLayer, object]:
    """单要素四边形：外环 4 个真实顶点 + 闭合重复点（共 5 个坐标）。

    用 4（而非 3）个真实顶点，才能在删到第 4 个时仍在闭环守卫内
    （`len(parent) < 4` 判据含闭合点）。
    """
    feature = VectorFeature(
        "f0",
        {"type": "Polygon", "coordinates": [[
            [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0],
        ]]},
        {"kind": "a"},
    )
    layer = VectorLayer(id="L", name="L", features=[feature])
    return layer, layer.start_editing()


def test_rejected_native_vertex_gesture_leaves_no_command():
    """被拒手势（最少顶点守卫）不得留下 undo 单元或 bump 修订
    —— destroy_edit_command 必须真正回滚。"""
    from paleo_workbench.mapping.map_tools import VertexTool

    layer, session = _quad_ring_layer()
    tool = VertexTool(session, identify_vertex=lambda _p: None)
    # 4 真实顶点 → 删 1 个剩 3 个（合法），再删 1 个触发 ≥3 守卫。
    assert tool.commit_vertex_delete("f0", (0, 1)) is True
    before_rev = session.revision
    before_undo = len(session.undo_stack)
    assert tool.commit_vertex_delete("f0", (0, 1)) is False, "最少顶点守卫应拒绝"
    assert len(session.undo_stack) == before_undo, "拒绝手势不得留下 undo 单元"
    assert session.revision == before_rev, "拒绝手势不得 bump 修订"
