"""V8 M3：跨图层拓扑传播的复合撤销（一次地质动作 = 一次 undo/redo）。

已知限制修复验证：V7 中 ``propagate_shared_vertex`` 在其它图层的独立
undo 栈上开命令，origin 层 undo 只回滚一半。复合组把 origin 命令与传播
命令按对象身份绑定，undo/redo 整组原子，冲突（传播后同要素又有编辑）
显式拒绝而非错位回滚。
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _adjacent_layers() -> tuple[VectorLayer, VectorLayer]:
    """两个共享顶点 (1, 0) 的相邻多边形图层。"""
    left = VectorLayer(
        id="left", name="Left", features=[
            VectorFeature("a", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
        ]
    )
    right = VectorLayer(
        id="right", name="Right", features=[
            VectorFeature("b", {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 0]]]})
        ]
    )
    return left, right


def _commit_origin_vertex(left: VectorLayer, moved_to=(1.5, 0)) -> None:
    left_session = left.start_editing()
    left_session.set_vertex("a", (0, 1), moved_to)


def test_compound_undo_reverts_origin_and_propagation_together() -> None:
    left, right = _adjacent_layers()
    _commit_origin_vertex(left)
    topology = TopologyService(enabled=True)

    result = topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    assert result.compound_registered, "应当登记复合撤销组"

    session = left.edit_session
    group = topology.pending_compound(session)
    assert group is not None
    undone = topology.undo_compound(group)
    assert undone.ok, undone.reason

    # 一次 undo：两层都回到传播前（V7 已知限制在此修复）。
    assert left.edit_session.feature("a").geometry["coordinates"][0][1] == (1.0, 0.0)
    assert right.edit_session.feature("b").geometry["coordinates"][0][0] == (1.0, 0.0)
    # 工作副本层上已无残留命令（is_dirty 为 False——没有半组编辑残留）。
    assert not right.edit_session.is_dirty


def test_compound_redo_reapplies_whole_group_linearly() -> None:
    left, right = _adjacent_layers()
    _commit_origin_vertex(left)
    topology = TopologyService(enabled=True)
    topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    group = topology.pending_compound(left.edit_session)
    assert topology.undo_compound(group).ok

    redone = topology.redo_compound(group)
    assert redone.ok, redone.reason
    assert left.edit_session.feature("a").geometry["coordinates"][0][1] == (1.5, 0.0)
    assert right.edit_session.feature("b").geometry["coordinates"][0][0] == (1.5, 0.0)

    # 组撤销后任一涉及层又有新编辑 → 整组拒绝重做（线性历史）。
    assert topology.undo_compound(group).ok
    left.edit_session.set_vertex("a", (0, 2), (9, 9))
    refused = topology.redo_compound(group)
    assert not refused.ok
    assert "拒绝重做" in refused.reason


def test_compound_undo_refused_when_target_layer_edited_after_propagation() -> None:
    left, right = _adjacent_layers()
    _commit_origin_vertex(left)
    topology = TopologyService(enabled=True)
    topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    # 传播后目标层同要素又有编辑：逐条撤销不再等价于那一次地质动作。
    right.edit_session.set_vertex("b", (0, 2), (2.0, 5.0))

    group = topology.pending_compound(left.edit_session)
    assert group is not None
    refused = topology.undo_compound(group)
    assert not refused.ok
    assert "又有编辑" in refused.reason
    # all-or-nothing：origin 编辑也必须原封不动。
    assert left.edit_session.feature("a").geometry["coordinates"][0][1] == (1.5, 0.0)
    assert right.edit_session.feature("b").geometry["coordinates"][0][2] == (2.0, 5.0)


def test_compound_not_registered_for_later_origin_edits() -> None:
    """origin 命令之上又有编辑 → pending_compound 不命中，走单层 undo。"""
    left, right = _adjacent_layers()
    _commit_origin_vertex(left)
    topology = TopologyService(enabled=True)
    topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    left.edit_session.set_vertex("a", (0, 2), (0.0, 7.0))

    assert topology.pending_compound(left.edit_session) is None
    assert left.edit_session.undo()  # 常规单命令撤销仍然可用
    assert left.edit_session.feature("a").geometry["coordinates"][0][2] == (1.0, 1.0)


def test_compound_degrades_honestly_when_macro_open() -> None:
    """宏打开时传播命令不落 undo 栈——登记降级（compound_registered=False）。"""
    left, right = _adjacent_layers()
    left_session = left.start_editing()
    left_session.begin_edit_command()
    left_session.set_vertex("a", (0, 1), (1.5, 0))
    topology = TopologyService(enabled=True)

    result = topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    assert result.changed, "传播仍应发生（V7 行为不变）"
    assert not result.compound_registered, "宏打开时如实降级为非原子"


def test_compound_discarded_when_layer_session_commits() -> None:
    left, right = _adjacent_layers()
    _commit_origin_vertex(left)
    topology = TopologyService(enabled=True)
    topology.propagate_shared_vertex(
        [left, right], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )
    assert topology.pending_compound(left.edit_session) is not None

    topology.discard_compounds(["left", "right"])
    assert topology.pending_compound(left.edit_session) is None
    assert topology.pending_compound_redo(left.edit_session) is None


# -- 工作站集成（undo 入口整组化） --------------------------------------------


class _WorkstationHarness:
    def __init__(self) -> None:
        from paleo_workbench.mapping.vector_layer import VectorFeature
        from paleo_workbench.ui.workstation.composite_editing import CompositeEditController

        self.controller = CompositeEditController(project_crs="EPSG:3857")
        self.conflicts: list[str] = []
        self.controller.topology_conflict.connect(self.conflicts.append)
        self.controller.set_topology(True)
        self.left = self.controller.create_layer("Left", "polygon")
        self.right = self.controller.create_layer("Right", "polygon")
        session_left, _ = self.controller.ensure_layer_session(self.left.id)
        session_right, _ = self.controller.ensure_layer_session(self.right.id)
        session_left.add_feature(
            VectorFeature("feat-1", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
        )
        session_right.add_feature(
            VectorFeature("feat-2", {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 0]]]})
        )
        session_left.commit_changes()
        session_right.commit_changes()
        self.controller.set_active_layer(self.left.id)

    def commit_vertex(self) -> None:
        session = self.controller._open_session(self.left)
        session.set_vertex("feat-1", (0, 1), (1.5, 0))
        self.controller._propagate_shared_vertex("feat-1", (0, 1), (1, 0), (1.5, 0))


@pytest.mark.qt_no_exception_capture
def test_workstation_undo_reverts_propagation_across_layers() -> None:
    harness = _WorkstationHarness()
    harness.commit_vertex()
    assert harness.right.edit_session is not None

    assert harness.controller.edit_command("undo")

    assert harness.left.edit_session is not None
    assert harness.left.edit_session.feature("feat-1").geometry["coordinates"][0][1] == (1.0, 0.0)
    assert harness.right.edit_session.feature("feat-2").geometry["coordinates"][0][0] == (1.0, 0.0)
    assert harness.conflicts == []


def test_workstation_undo_refusal_is_not_silent() -> None:
    harness = _WorkstationHarness()
    harness.commit_vertex()
    harness.right.edit_session.set_vertex("feat-2", (0, 2), (2.0, 5.0))

    assert not harness.controller.edit_command("undo")
    assert harness.conflicts and "又有编辑" in harness.conflicts[-1]


def test_production_tool_flow_registers_compound_cross_layer(qtbot) -> None:
    """review-2 P0 回归钉：真实 _commit_vertex 路径（回调在宏外）必须登记
    跨图层复合组——此前回调在宏内触发，生产恒降级为 V7 非原子。"""
    from paleo_workbench.mapping.map_tools import _commit_vertex

    left, right = _adjacent_layers()
    session = left.start_editing()
    topology = TopologyService(enabled=True)

    def hook(feature_id, path, origin, replacement):
        topology.propagate_shared_vertex(
            [left, right], origin=origin, replacement=replacement,
            skip=(left.id, str(feature_id), tuple(path)),
        )

    assert _commit_vertex(
        session, "a", (0, 1), (1.5, 0), hook, source_suffix="native",
    )
    group = topology.pending_compound(session)
    assert group is not None, "生产路径必须登记复合组（review-2 P0 修复）"
    undone = topology.undo_compound(group)
    assert undone.ok, undone.reason
    assert left.edit_session.feature("a").geometry["coordinates"][0][1] == (1.0, 0.0)
    assert right.edit_session.feature("b").geometry["coordinates"][0][0] == (1.0, 0.0)
