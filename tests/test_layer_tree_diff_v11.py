"""V11 TreeDiff contracts（keyed LCS 最小操作集）。"""
from __future__ import annotations

from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
)
from paleo_workbench.mapping_workspace.layer_tree_diff import (
    GroupCreate,
    GroupMove,
    GroupRename,
    GroupStateSet,
    LayerMove,
    diff_trees,
    lcs_indices,
)


def _snap(*children) -> LayerTreeSnapshot:
    return LayerTreeSnapshot(children=tuple(children), source="domain")


def _group(gid: str, *children, name: str | None = None, visible=True, expanded=True,
           locked=False) -> GroupNode:
    return GroupNode(group_id=gid, name=name or gid, kind="system",
                     children=tuple(children), expanded=expanded,
                     locked=locked, visible=visible)


def _layer(lid: str) -> LayerRef:
    return LayerRef(layer_id=lid)


class TestLcsIndices:
    def test_identical_full(self):
        assert lcs_indices(["a", "b", "c"], ["a", "b", "c"]) == [0, 1, 2]

    def test_typical(self):
        # LCS(a,b,c,d vs a,c,b,d) 长度 3；保持 a 序列下标升序且对应子序列
        a = ["a", "b", "c", "d"]
        b = ["a", "c", "b", "d"]
        keep = lcs_indices(a, b)
        assert len(keep) == 3
        assert [a[i] for i in keep] == [x for x in b if x in {a[i] for i in keep}]
        assert [b.index(a[i]) for i in keep] == sorted(
            b.index(a[i]) for i in keep)

    def test_disjoint(self):
        assert lcs_indices([], ["x"]) == []
        assert lcs_indices(["x"], []) == []


class TestDiffTrees:
    def test_identical_trees_empty_diff(self):
        cur = _snap(_group("g1", _layer("a"), _layer("b")))
        assert diff_trees(cur, cur).is_empty

    def test_noop_at_scale(self):
        layers = [_layer(f"l{i}") for i in range(1000)]
        cur = _snap(_group("g1", *layers))
        d = diff_trees(cur, _snap(_group("g1", *layers)))
        assert d.op_count() == 0

    def test_single_layer_move_within_group(self):
        cur = _snap(_group("g1", _layer("a"), _layer("b"), _layer("c")))
        des = _snap(_group("g1", _layer("b"), _layer("a"), _layer("c")))
        d = diff_trees(cur, des)
        # LCS = (b,c) 或 (a,c)——恰一个节点需要移动
        assert d.op_count() == 1
        assert len(d.layer_moves) == 1
        move = d.layer_moves[0]
        assert move.new_parent == "g1"

    def test_layer_moves_to_another_group(self):
        cur = _snap(_group("g1", _layer("a")), _group("g2"))
        des = _snap(_group("g1"), _group("g2", _layer("a")))
        d = diff_trees(cur, des)
        assert list(d.layer_moves) == [LayerMove("a", "g2", 0)]
        assert d.is_empty is False

    def test_layer_moves_to_root(self):
        cur = _snap(_group("g1", _layer("a"), _layer("b")))
        des = _snap(_group("g1", _layer("b")), _layer("a"))
        d = diff_trees(cur, des)
        # 根级子序 = [g1, a]：a 排在组之后（index 1）
        assert list(d.layer_moves) == [LayerMove("a", "", 1)]

    def test_group_create_topological_order(self):
        cur = _snap()
        des = _snap(
            _group("user.outer", _group("user.inner", _layer("x"))))
        d = diff_trees(cur, des)
        assert list(d.group_creates) == [
            GroupCreate("user.outer", "user.outer", ""),
            GroupCreate("user.inner", "user.inner", "user.outer"),
        ]
        # 图层放置随组创建之后
        assert list(d.layer_moves) == [LayerMove("x", "user.inner", 0)]

    def test_group_remove(self):
        cur = _snap(_group("g1", _layer("a")), _group("user.gone"))
        des = _snap(_group("g1", _layer("a")))
        d = diff_trees(cur, des)
        assert [op.group_id for op in d.group_removes] == ["user.gone"]

    def test_group_rename(self):
        cur = _snap(_group("user.g", _layer("a"), name="旧名"))
        des = _snap(_group("user.g", _layer("a"), name="新名"))
        d = diff_trees(cur, des)
        assert list(d.group_renames) == [GroupRename("user.g", "新名")]
        assert len(d.layer_moves) == 0  # 重命名不扰动放置

    def test_group_move_between_parents(self):
        cur = _snap(_group("user.a"), _group("user.b", _group("user.c")))
        des = _snap(_group("user.a", _group("user.c")), _group("user.b"))
        d = diff_trees(cur, des)
        assert list(d.group_moves) == [GroupMove("user.c", "user.a", 0)]

    def test_visibility_and_state_sets(self):
        cur = _snap(_group("g1", _layer("a"), visible=False, expanded=False))
        des = _snap(_group("g1", _layer("a"), visible=True, expanded=True, locked=True))
        d = diff_trees(cur, des)
        kinds = {(s.kind, s.value) for s in d.group_states}
        assert ("visible", True) in kinds
        assert ("expanded", True) in kinds
        assert ("locked", True) in kinds
        assert len(d.layer_moves) == 0

    def test_new_layer_insertion_one_op(self):
        layers = [_layer(f"l{i}") for i in range(100)]
        cur = _snap(_group("g1", *layers))
        grown = layers[:50] + [_layer("new")] + layers[50:]
        d = diff_trees(cur, _snap(_group("g1", *grown)))
        assert d.op_count() == 1
        assert d.layer_moves[0].layer_id == "new"

    def test_reversal_minimal_moves(self):
        cur = _snap(_group("g1", _layer("a"), _layer("b"), _layer("c")))
        des = _snap(_group("g1", _layer("c"), _layer("b"), _layer("a")))
        d = diff_trees(cur, des)
        assert len(d.layer_moves) == 2  # LCS 长 1 → 恰 2 个 move

    def test_empty_group_materialization_is_create(self):
        cur = _snap(_group("g1", _layer("a")))
        des = _snap(_group("g1", _layer("a")), _group("phase3.integrated"))
        d = diff_trees(cur, des)
        assert [op.group_id for op in d.group_creates] == ["phase3.integrated"]

    def test_cross_group_no_shared_moves(self):
        # 图层从 g1 移到 g2 + g1 内部重排——只发出必要 move
        cur = _snap(_group("g1", _layer("a"), _layer("b"), _layer("c")),
                    _group("g2", _layer("d")))
        des = _snap(_group("g1", _layer("b"), _layer("c")),
                    _group("g2", _layer("d"), _layer("a")))
        d = diff_trees(cur, des)
        assert list(d.layer_moves) == [LayerMove("a", "g2", 1)]
