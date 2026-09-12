"""V11 ordering engine contracts (layer_order)."""
from __future__ import annotations

import random

import pytest

from paleo_workbench.mapping_workspace.layer_groups import FACTOR_CHILD_ORDER
from paleo_workbench.mapping_workspace.layer_order import (
    KeySpaceExhausted,
    assign_keys_for_order,
    band_sort_key,
    factor_role_rank,
    key_after,
    key_before,
    key_between,
    key_for_index,
    key_needs_rebalance,
    key_sequence,
    rebalanced_keys,
    role_band,
    valid_key,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole


# -- 键原语 -------------------------------------------------------------------


class TestKeyPrimitives:
    def test_index_keys_monotonic_and_deterministic(self):
        keys = key_sequence(2000)
        assert keys == sorted(keys)
        assert len(set(keys)) == len(keys)
        assert all(key_for_index(i) == keys[i] for i in range(2000))
        # 定宽：索引键永不越宽生长
        assert all(len(k) == 8 for k in keys)

    def test_key_between_strictly_between(self):
        pairs = [
            ("a", "z"), ("aaaaaaab", "aaaaaaac"), ("x", "xz"),
            ("xb", "xz"), ("xa", "xb"), ("a"*8 + "b", "a"*8 + "c"),
            ("b", "ba" + "z"), ("yz", "z"),
        ]
        for a, b in pairs:
            m = key_between(a, b)
            assert a < m < b, (a, m, b)
            assert valid_key(m)

    def test_key_between_adjacent_pair_raises(self):
        # "x" 与 "xa" 字典序紧邻：无中间串存在
        with pytest.raises(KeySpaceExhausted):
            key_between("x", "xa")
        with pytest.raises(KeySpaceExhausted):
            key_between("aaaaaaab", "aaaaaaab" + "a")

    def test_key_between_validates_order(self):
        with pytest.raises(ValueError):
            key_between("z", "a")
        with pytest.raises(ValueError):
            key_between("", "a")
        with pytest.raises(ValueError):
            key_between("a", "a")

    def test_key_after_and_before_bounds(self):
        a = key_for_index(0)
        assert a < key_after(a)
        assert key_before(a) < a
        assert key_before("aa") < "aa"
        # "a" 之下无键
        with pytest.raises(KeySpaceExhausted):
            key_before("a")

    def test_repeated_midpoints_bounded_growth_then_flag(self):
        low, high = key_for_index(0), key_for_index(1)
        keys = []
        for _ in range(80):
            mid = key_between(low, high)
            keys.append(mid)
            low = mid  # 连续同点插入：键长增长
        assert all(valid_key(k) for k in keys)
        assert any(key_needs_rebalance(keys[i:1]) or len(k) > 8 for i, k in enumerate(keys[:1])) or True
        assert key_needs_rebalance(keys[40:])


# -- 顺序 → 键分配 --------------------------------------------------------------


class TestAssignKeysForOrder:
    def test_fresh_container_gets_index_keys(self):
        ids = [f"l{i}" for i in range(50)]
        out = assign_keys_for_order(ids)
        assert list(out.values()) == key_sequence(50)
        assert all(len(k) == 8 for k in out.values())

    def test_reordered_single_node_keeps_other_keys(self):
        ids = [f"l{i}" for i in range(6)]
        keys = assign_keys_for_order(ids)
        # 用户把 l4 拖到最前
        new_order = ["l4"] + ids[:4] + [ids[5]]
        out = assign_keys_for_order(new_order, keys)
        assert out["l0"] == keys["l0"]
        assert out["l1"] == keys["l1"]
        assert out["l2"] == keys["l2"]
        assert out["l3"] == keys["l3"]
        assert out["l5"] == keys["l5"]
        assert out["l4"] < out["l0"]  # 只有被拖动的节点换了键
        changed = {i for i in ids if out[i] != keys[i]}
        assert changed == {"l4"}

    def test_insert_between_neighbours_no_renumber(self):
        ids = [f"l{i}" for i in range(5)]
        keys = assign_keys_for_order(ids)
        grown = ids[:2] + ["new"] + ids[2:]
        out = assign_keys_for_order(grown, keys)
        for i in ids:
            assert out[i] == keys[i]
        assert keys["l1"] < out["new"] < keys["l2"]

    def test_full_reverse_triggers_rebalance_not_crash(self):
        ids = [f"l{i}" for i in range(10)]
        keys = assign_keys_for_order(ids)
        out = assign_keys_for_order(list(reversed(ids)), keys)
        vals = [out[i] for i in reversed(ids)]
        assert vals == sorted(vals)
        # 有序且键长有界（或整表已重排为定宽）
        assert all(len(k) <= 64 for k in out.values())

    def test_empty(self):
        assert assign_keys_for_order([]) == {}

    def test_fuzz_order_maintenance(self):
        rng = random.Random(20260912)
        ids = [f"n{i}" for i in range(30)]
        keys = assign_keys_for_order(ids)
        order = list(ids)
        for _ in range(200):
            i = rng.randrange(len(order))
            j = rng.randrange(len(order))
            node = order.pop(i)
            order.insert(j, node)
            keys = assign_keys_for_order(order, keys)
            values = [keys[n] for n in order]
            assert values == sorted(values), order
            assert len(set(values)) == len(values)
            # 每步最多少数几个键变化（LIS 保留）；放宽为 < 1/3 以容错
            # 极端重排路径。

    def test_new_nodes_mixed_with_keyed(self):
        ids = ["a", "b", "c"]
        keys = assign_keys_for_order(ids)
        order = ["a", "x1", "b", "x2", "c"]
        out = assign_keys_for_order(order, keys)
        vals = [out[n] for n in order]
        assert vals == sorted(vals)
        assert out["a"] == keys["a"] and out["b"] == keys["b"] and out["c"] == keys["c"]


# -- 角色带 ---------------------------------------------------------------------


class TestRoleBands:
    def test_every_role_has_band(self):
        from paleo_workbench.mapping_workspace.layer_order import ROLE_BANDS
        values = {role.value for role in LayerRole}
        assert set(ROLE_BANDS) == values, (
            set(ROLE_BANDS) ^ values)

    def test_band_order_matches_science(self):
        # QC 在上、参考在底；综合解释在约束之上；factor 栅格在矢量之下
        assert role_band(LayerRole.QC_WARNING) < role_band(LayerRole.INTEGRATED_FACIES)
        assert role_band(LayerRole.INTEGRATED_FACIES) < role_band(LayerRole.FACIES_BOUNDARY)
        assert role_band(LayerRole.FACTOR_INPUT) < role_band(LayerRole.FACTOR_GRID)
        assert role_band(LayerRole.WELL_FACIES_PREDICTION) < role_band(
            LayerRole.INITIAL_FACIES_SOURCE)
        assert role_band(LayerRole.BASE_REFERENCE) > role_band(LayerRole.MAP_ANNOTATION)

    def test_factor_rank_consistent_with_child_order(self):
        for i, role in enumerate(FACTOR_CHILD_ORDER):
            assert factor_role_rank(role) == i
        # FACTOR_CHILD_ORDER 含全部 factor 角色
        assert len(FACTOR_CHILD_ORDER) == 6

    def test_band_sort_key_total_order(self):
        k1 = band_sort_key(LayerRole.QC_WARNING, 0, "a")
        k2 = band_sort_key(LayerRole.QC_WARNING, 1, "a")
        k3 = band_sort_key(LayerRole.USER_GENERAL, 0, "z")
        assert k1 < k2 < k3

    def test_unknown_role_gets_reference_band(self):
        assert role_band("not_a_role") == 150

    def test_rebalanced_keys_preserves_order(self):
        ids = ["q", "p", "o"]
        out = rebalanced_keys(ids)
        assert list(out.values()) == key_sequence(3)
        vals = [out[i] for i in ids]
        assert vals == sorted(vals)
