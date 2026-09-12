"""V11 ordering engine：稳定分数排序键 + 科学角色带 + 顺序→键分配。

设计（docs/development/qgis-cartography-runtime-v11/04-ordering.md）：

* **排序键**是 ``a``–``z`` 字母表上的字符串，全序 = 纯字典序。键空间
  在个别病态邻接对（如 ``"x"`` 与 ``"xa"``）处会耗尽——生成器显式抛
  :class:`KeySpaceExhausted`，调用方整容器重排（:func:`rebalanced_keys`，
  一次性事务内使用）。默认键使用定宽 8 位 base-26 整数（含 ``z`` 尾，
  同索引 → 同键，键间留 1 位间隙）。
* **角色带**（``ROLE_BANDS``）给出组内/根级松散图层的默认科学顺序，
  以 33 个 LayerRole 的实际审计为准（机器名，无显示名）。factor 组内
  沿用 FACTOR_CHILD_ORDER 科学序（``FACTOR_ROLE_RANK`` 提供 O(1) 秩）。
* **顺序→键**（:func:`assign_keys_for_order`）：把观察到的位置序转成
  稳定键——已有键的相对序与观察序一致的部分（最长递增子数列）原样
  保留，其余节点在前后邻居之间取中点键。用户拖动一次只改最少的键。

本模块纯函数、无 Qt/numpy；全部操作 O(N log N) 以内（排序键分配的
中点链最坏 O(N·L)，L=键长上界，受重排阈值约束）。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_DIGIT_OF = {ch: i for i, ch in enumerate(_ALPHABET)}
#: 索引键定宽（26^7 ≈ 8×10^9 槽位；中点插入可越宽生长，见模块 docstring）。
_INDEX_WIDTH = 8
#: 单键重排阈值：连续同点插入导致键长膨胀。
_REBALANCE_LENGTH = 64


class KeySpaceExhausted(ValueError):
    """两个键字典序紧邻（无中间串）——调用方应整容器重排后重试。"""


__all__ = [
    "KeySpaceExhausted",
    "key_for_index",
    "key_sequence",
    "key_between",
    "key_after",
    "key_before",
    "assign_keys_for_order",
    "key_needs_rebalance",
    "rebalanced_keys",
    "valid_key",
    "ROLE_BANDS",
    "role_band",
    "FACTOR_ROLE_RANK",
    "factor_role_rank",
    "band_sort_key",
]


# ---------------------------------------------------------------------------
# 键原语（纯字典序）
# ---------------------------------------------------------------------------

def valid_key(key: str) -> bool:
    """键字母表校验（空串 = 无键，legacy）。"""
    return all(ch in _DIGIT_OF for ch in key)


def key_for_index(index: int) -> str:
    """索引 → 定宽默认键（同索引 → 同键；字典序 == 索引序）。

    值域从 2 起（``key_for_index(0)`` 尾数 ``"b"``），0/1 留给向前/向后
    手工插入的余量；键尾保持非 ``"a"``，避免与其前缀形成紧邻对。
    """
    if index < 0:
        raise ValueError("index must be >= 0")
    value = index + 2
    digits = ["a"] * _INDEX_WIDTH
    pos = _INDEX_WIDTH - 1
    while value > 0 and pos >= 0:
        digits[pos] = _ALPHABET[value % 26]
        value //= 26
        pos -= 1
    if value > 0:
        raise ValueError(f"index {index} overflows key width {_INDEX_WIDTH}")
    return "".join(digits)


def key_sequence(count: int) -> list[str]:
    """前 ``count`` 个默认键（步长 1；相邻键之间至少 1 个中点槽位）。"""
    return [key_for_index(i) for i in range(count)]


def _common_prefix_len(a: str, b: str) -> int:
    i = 0
    limit = min(len(a), len(b))
    while i < limit and a[i] == b[i]:
        i += 1
    return i


def _str_below(rest: str) -> str:
    """非空串 ``s < rest``（``rest`` 全 ``a`` 时抛 KeySpaceExhausted）。"""
    if rest and rest[-1] > "a":
        return rest[:-1] + chr(ord(rest[-1]) - 1)
    stripped = rest.rstrip("a")
    if not stripped:
        # rest == "a"*k：下方只有更短的 a 串（"a"*(k-1) < rest）。
        if len(rest) >= 2:
            return rest[:-1]
        raise KeySpaceExhausted(f"no key below {rest!r}")
    # rest 形如 P + "a"*k（P 尾非 a）：P 去尾一位。
    return stripped[:-1] + chr(ord(stripped[-1]) - 1) + "z" * len(rest[len(stripped):])


def key_between(a: str, b: str) -> str:
    """严格介于 ``a`` 与 ``b`` 之间的键（要求 ``a < b``，均非空）。

    优先短键（``a + "b"``），紧邻对显式抛 :class:`KeySpaceExhausted`。
    """
    if not a or not b or not a < b:
        raise ValueError(f"key_between requires non-empty a < b (got {a!r}, {b!r})")
    candidate = a + "b"
    if candidate < b:
        return candidate
    # a 是 b 的前缀且 rest ≤ "b" 开头：在 rest 内部找下方串。
    rest = b[len(a):]
    return a + _str_below(rest)


def key_after(a: str) -> str:
    """大于 ``a`` 的近邻键（尾部追加；用于无上界插入）。"""
    if not a:
        return key_for_index(0)
    return a + "b"


def key_before(b: str) -> str:
    """小于 ``b`` 的近邻键（用于无下界插入；紧邻时抛耗尽）。"""
    if not b:
        raise ValueError("key_before requires a non-empty upper bound")
    return _str_below(b)


# ---------------------------------------------------------------------------
# 顺序 → 键分配（最小扰动）
# ---------------------------------------------------------------------------

def _longest_increasing_indices(keys: Sequence[str]) -> set[int]:
    """O(K log K) 最长递增子数列（保序集合）——patience sorting。"""
    import bisect

    tails: list[str] = []
    tails_pos: list[int] = []
    prev: list[int] = [-1] * len(keys)
    for idx, key in enumerate(keys):
        pos = bisect.bisect_left(tails, key)
        if pos == len(tails):
            tails.append(key)
            tails_pos.append(idx)
        else:
            tails[pos] = key
            tails_pos[pos] = idx
        prev[idx] = tails_pos[pos - 1] if pos > 0 else -1
    keep: set[int] = set()
    node = tails_pos[-1] if tails_pos else -1
    while node >= 0:
        keep.add(node)
        node = prev[node]
    return keep


def assign_keys_for_order(
    ordered_ids: Sequence[str],
    existing: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """把位置序转成稳定键，最小化已有键的改动。

    已有键构成的相对序与观察序一致的部分（LIS）原样保留；其余节点在
    前后邻居的键之间取中点链。任何一步键空间耗尽时整表重排为定宽
    默认键（保序、确定性）。返回 ``id → key``（对 ``ordered_ids`` 完备）。
    """
    ids = list(ordered_ids)
    if not ids:
        return {}
    prior = existing or {}
    if not any(prior.get(node_id) for node_id in ids):
        # 全新容器：直接定宽默认键（键长 O(1)，而非中点链线性增长）。
        return rebalanced_keys(ids)
    present = [str(prior.get(node_id, "")) for node_id in ids]
    keyed_positions = [j for j, k in enumerate(present) if k]
    keep = (
        _longest_increasing_indices([present[j] for j in keyed_positions])
        if keyed_positions else set()
    )
    keep_ids = {ids[keyed_positions[j]] for j in keep} if keyed_positions else set()
    try:
        out: dict[str, str] = {}
        prev_key: str | None = None
        pending: list[str] = []
        for node_id, key in zip(ids, present):
            if key and node_id in keep_ids:
                _flush_pending(pending, out, prev_key, key)
                pending = []
                out[node_id] = key
                prev_key = key
            else:
                pending.append(node_id)
        _flush_pending(pending, out, prev_key, None)
    except KeySpaceExhausted:
        return rebalanced_keys(ids)
    if key_needs_rebalance(out.values()):
        return rebalanced_keys(ids)
    return out


def _flush_pending(
    pending: list[str],
    out: dict[str, str],
    prev_key: str | None,
    next_key: str | None,
) -> None:
    """在 (prev_key, next_key) 开区间内为连续 pending 节点分配中点链。"""
    if not pending:
        return
    keys: list[str] = []
    low = prev_key or (key_before(next_key) if next_key else key_for_index(0))
    if prev_key is None and next_key is not None:
        low = key_before(next_key)
    for _ in pending:
        nxt = key_after(low) if next_key is None else None
        if next_key is not None:
            try:
                nxt = key_between(low, next_key)
            except (KeySpaceExhausted, ValueError):
                nxt = None
        if nxt is None:
            raise KeySpaceExhausted(
                f"no slot between {low!r} and {next_key!r}")
        keys.append(nxt)
        low = nxt
    for node_id, key in zip(pending, keys):
        out[node_id] = key


def key_needs_rebalance(keys: Iterable[str]) -> bool:
    return any(len(k) > _REBALANCE_LENGTH for k in keys)


def rebalanced_keys(ordered_ids: Sequence[str]) -> dict[str, str]:
    """整容器重排：按顺序重新派生定宽默认键（一次事务内使用）。"""
    return dict(zip(ordered_ids, key_sequence(len(ordered_ids))))


# ---------------------------------------------------------------------------
# 科学角色带（对 33 角色注册表的审计结论）
# ---------------------------------------------------------------------------

#: 带值越小越靠上（渲染在上）。组间粗排序由 SYSTEM_GROUP_TEMPLATES 的
#: 声明序承担；本表用于**组内**与**根级松散图层**的默认科学序。
ROLE_BANDS: dict[str, int] = {
    # 020 选择/拓扑/QC 覆盖
    "qc_warning": 20,
    "qc_conflict": 21,
    # 030 地图注记
    "map_annotation": 30,
    # 040 制图要素
    "map_symbol": 40,
    "map_reference": 41,
    # 050 综合解释
    "integrated_facies": 50,
    "integrated_boundary": 51,
    # 060 地质边界/符号
    "facies_boundary": 60,
    "fault_constraint": 61,
    # 070 人工解释
    "initial_facies_draft": 70,
    "interpretation_annotation": 71,
    "pending_review_area": 79,
    # 080 约束线
    "provenance_direction": 80,
    "provenance_line": 81,
    "distribution_line": 82,
    "paleo_shoreline": 83,
    "interpolation_boundary": 84,
    "mask_boundary": 85,
    # 090 factor 矢量（井点/分级区）
    "factor_input": 90,
    "factor_classification": 92,
    # 100 factor 等值线
    "factor_contour": 100,
    # 110 factor 栅格
    "factor_grid": 110,
    "factor_uncertainty": 112,
    "factor_qc": 114,
    # 120 预测层
    "well_facies_prediction": 120,
    "well_facies_confidence": 122,
    "seismic_facies_prediction": 124,
    "seismic_facies_confidence": 126,
    # 130 初始相
    "initial_facies_source": 130,
    # 140 井/地震足迹与分析辅助
    "analysis_aid": 140,
    # 150 参考/底图
    "base_reference": 150,
    "user_general": 155,
    "legacy_unclassified": 158,
}

#: factor 组内科学序（input→grid→contour→classification→uncertainty→QC；
#: 与 layer_groups.FACTOR_CHILD_ORDER 同源，此处提供 O(1) 秩查询）。
FACTOR_ROLE_RANK: dict[str, int] = {
    "factor_input": 0,
    "factor_grid": 1,
    "factor_contour": 2,
    "factor_classification": 3,
    "factor_uncertainty": 4,
    "factor_qc": 5,
}


def role_band(role: object) -> int:
    """角色的默认带值（未知角色 → 参考带，绝不抛）。"""
    return ROLE_BANDS.get(str(getattr(role, "value", role)), 150)


def factor_role_rank(role: object) -> int:
    """factor 组内科学序秩（未知 → 队尾）。"""
    return FACTOR_ROLE_RANK.get(str(getattr(role, "value", role)), 99)


def band_sort_key(role: object, sub_order: object = 0, node_id: str = "") -> tuple:
    """容器内默认排序键：带 → 科学子序 → 稳定 id（全序、确定性）。"""
    return (role_band(role), sub_order, node_id)
