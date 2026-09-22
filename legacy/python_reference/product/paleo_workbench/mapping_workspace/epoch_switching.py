"""期次差分切换计划器（00-decisions D3）——纯函数，无 Qt。

输入是鸭子类型的图层快照（``MapLayerSnapshot`` 形状：id/name/visible/opacity/
metadata），输出 show/hide 对称差与洋葱皮层集合；执行器按计划逐层调用既有
``set_layer_visible`` / ``set_layer_opacity``（增量镜像，零画布重建）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from paleo_workbench.mapping_workspace.layer_groups import epoch_key_of_group
from paleo_workbench.mapping_workspace.layer_roles import LayerRole

#: 参与洋葱皮的图层角色（相带面/相带边界类；00-decisions D2）。
_FACIES_LAYER_ROLES: frozenset[str] = frozenset(
    {
        LayerRole.INITIAL_FACIES_SOURCE.value,
        LayerRole.INITIAL_FACIES_DRAFT.value,
        LayerRole.INTEGRATED_FACIES.value,
        LayerRole.INTEGRATED_BOUNDARY.value,
        LayerRole.PENDING_REVIEW_AREA.value,
        # 模板键（旧工程/快照 metadata 惯用字符串）。
        "facies",
        "facies_polygon",
        "facies_boundary",
        "facies_sub",
        "facies_micro",
    }
)


@dataclass(frozen=True)
class EpochSwitchPlan:
    """一次期次切换的最小可见性变更集。"""

    target: str
    show: tuple[str, ...] = ()
    hide: tuple[str, ...] = ()

    def __bool__(self) -> bool:  # 空计划 = 无图层变更
        return bool(self.show or self.hide)


def _tag_only_classifier(layer: Any) -> str | None:
    """无期次目录时的保守分类：只认显式标签（epoch/horizon/epoch 组）。"""
    metadata = dict(getattr(layer, "metadata", None) or {})
    tag = str(metadata.get("epoch", "") or "").strip()
    if tag:
        return tag
    tag = str(metadata.get("horizon", "") or "").strip()
    if tag:
        return tag
    group = str(metadata.get("group", "") or "").strip()
    return epoch_key_of_group(group) if group else None


def default_epoch_classifier(
    epochs: Sequence[Any],
) -> Callable[[Any], str | None]:
    """图层 → 期次 key（无归属返回 None）。

    信号优先级：metadata.epoch / metadata.horizon / metadata.group（epoch 组 id）
    → 层名包含期次 key 或 label（长模式优先，避免前缀吞并）。
    """
    patterns = [
        (str(getattr(e, "key", "") or ""), str(getattr(e, "label", "") or ""))
        for e in epochs
    ]
    patterns = [(k, l) for k, l in patterns if k]
    patterns.sort(key=lambda p: -(len(p[0]) + len(p[1])))

    def classify(layer: Any) -> str | None:
        metadata = dict(getattr(layer, "metadata", None) or {})
        for field in ("epoch", "horizon"):
            tag = str(metadata.get(field, "") or "").strip()
            if tag:
                for key, _ in patterns:
                    if tag == key:
                        return key
        group = str(metadata.get("group", "") or "").strip()
        if group:
            epoch_key = epoch_key_of_group(group)
            if epoch_key:
                for key, _ in patterns:
                    if epoch_key == key:
                        return key
        name = str(getattr(layer, "name", "") or "")
        if name:
            for key, label in patterns:
                # 单字符键的子串匹配误命中率高（如 "A" ⊂ "BASE"），要求
                # 键/标签长度 ≥2 才走名称兜底。
                if (len(key) >= 2 and key in name) or (
                    label and len(label) >= 2 and label in name
                ):
                    return key
        return None

    return classify


def is_facies_layer(layer: Any) -> bool:
    """相带面/边界类图层判定（洋葱皮参与条件，D2）。"""
    metadata = dict(getattr(layer, "metadata", None) or {})
    role = str(metadata.get("layer_role", "") or "").strip()
    if role:
        return role in _FACIES_LAYER_ROLES
    name = str(getattr(layer, "name", "") or "")
    # 名称兜底（review P3）：收窄为明确相带词，避免吞"相干体切片"等地震层。
    return any(word in name for word in ("相带", "沉积相", "相面", "亚相", "微相"))


def build_epoch_switch_plan(
    layers: Sequence[Any],
    *,
    current: str | None,
    target: str,
    classifier: Callable[[Any], str | None] | None = None,
) -> EpochSwitchPlan:
    """当前→目标期次的最小变更计划（对称差；同 epoch 返回空计划）。"""
    if target == current:
        return EpochSwitchPlan(target=target)
    classify = classifier or _tag_only_classifier
    show: list[str] = []
    hide: list[str] = []
    for layer in layers:
        key = classify(layer)
        if key is None:
            continue  # 无归属层（底图/井位/参考）不随期次切换
        visible = bool(getattr(layer, "visible", True))
        if key == target and not visible:
            show.append(str(layer.id))
        elif key != target and visible:
            hide.append(str(layer.id))
    return EpochSwitchPlan(target=target, show=tuple(show), hide=tuple(hide))


def build_onion_layers(
    layers: Sequence[Any],
    epochs: Sequence[Any],
    *,
    current: str,
    classifier: Callable[[Any], str | None] | None = None,
) -> list[str]:
    """相邻前一期次（index-1）的相带层 id（老→新目录序，D2）。"""
    keys = [str(getattr(e, "key", "") or "") for e in epochs]
    if not keys or current not in keys:
        return []
    index = keys.index(current)
    if index == 0:
        return []  # 最老期次无前一期
    prev = keys[index - 1]
    classify = classifier or _tag_only_classifier
    return [
        str(layer.id)
        for layer in layers
        if classify(layer) == prev and is_facies_layer(layer)
    ]
