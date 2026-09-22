"""Per-LayerRole snapping profiles（V9 W4，Goal §18）.

推荐 ≠ 硬编码真值：每个角色的 profile 给出**可解释**的默认捕捉模式/
容差/拓扑提示（rationale 一并携带），供两处消费：

* ``SnappingSettingsDialog`` 的「按角色推荐」预填——用户可改，改后即用户
  配置（``SnappingService`` 既有 per-layer 覆盖通道，无新增状态源）；
* ``GeologicalCaptureSpec``（V9 W9）：按角色建捕获图层时应用推荐，使
  「物源方向线」「相带边界」等捕获从第一笔起就有正确的捕捉语义。

模式词表 = ``SnappingService.modes`` 既有词汇（vertex/segment/midpoint/
endpoint/intersection/reference/grid）——本模块不发明第二套模式语言。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping_workspace.layer_roles import LayerRole

__all__ = [
    "SnappingProfile",
    "recommended_profile_for_role",
    "profile_summary",
]


@dataclass(frozen=True, slots=True)
class SnappingProfile:
    """一个角色类别的推荐捕捉配置（解释先行，用户可覆盖）。"""

    role: LayerRole
    #: 推荐模式集（SnappingService.modes 词表）。
    modes: frozenset[str]
    #: 推荐像素容差（QGIS 桌面默认 12px 上下浮动）。
    tolerance_px: float
    #: 是否建议开启拓扑编辑（共享节点传播 + 保存校验）。
    topological: bool
    #: 推荐理由（呈现给用户的解释，不是内部注释）。
    rationale: str


#: 角色聚类 → profile。聚类而非逐角色：同簇角色的捕捉语义一致，逐角色
#: 表只会复制粘贴然后漂移。缺省簇 = 通用编辑默认。
_PROFILES: dict[str, SnappingProfile] = {
    "boundary": SnappingProfile(
        role=LayerRole.FACIES_BOUNDARY,
        modes=frozenset({"vertex", "segment", "intersection"}),
        tolerance_px=12.0,
        topological=True,
        rationale=(
            "相带边界追求无缝拼接：顶点+段+交点捕捉并开启拓扑编辑，"
            "相邻边界共享节点自动传播，避免出现缝/重叠"
        ),
    ),
    "shoreline": SnappingProfile(
        role=LayerRole.PALEO_SHORELINE,
        modes=frozenset({"vertex", "segment"}),
        tolerance_px=10.0,
        topological=False,
        rationale=(
            "古岸线是连续曲线约束：顶点+段捕捉保证与已有岸线/边界衔接；"
            "拓扑编辑默认关闭（岸线允许与相带边界交叉而非共节点）"
        ),
    ),
    "fault": SnappingProfile(
        role=LayerRole.FAULT_CONSTRAINT,
        modes=frozenset({"vertex", "endpoint", "segment"}),
        tolerance_px=8.0,
        topological=False,
        rationale=(
            "断层端点位置有独立地质含义：端点+顶点+段捕捉便于精确拾取"
            "断距端头与已有断层交会，拓扑编辑关闭（断层不与边界共节点）"
        ),
    ),
    "direction": SnappingProfile(
        role=LayerRole.PROVENANCE_DIRECTION,
        modes=frozenset({"endpoint", "vertex"}),
        tolerance_px=10.0,
        topological=False,
        rationale=(
            "物源方向线以箭头端点表达指向：端点捕捉让方向线终点落在"
            "井位/参考点上；段捕捉关闭（方向线中段无需贴合其它要素）"
        ),
    ),
    "line_constraint": SnappingProfile(
        role=LayerRole.DISTRIBUTION_LINE,
        modes=frozenset({"vertex", "segment"}),
        tolerance_px=10.0,
        topological=False,
        rationale=(
            "展布线/物源线沿走向追踪：顶点+段捕捉衔接已有约束线；"
            "拓扑编辑关闭（约束线允许相交表达超覆关系）"
        ),
    ),
    "polygon_constraint": SnappingProfile(
        role=LayerRole.INTERPOLATION_BOUNDARY,
        modes=frozenset({"vertex", "segment"}),
        tolerance_px=12.0,
        topological=True,
        rationale=(
            "插值边界/掩膜必须闭合且不与工区边界留缝：顶点+段捕捉配合"
            "拓扑编辑，闭合性由保存时校验兜底"
        ),
    ),
    "draft": SnappingProfile(
        role=LayerRole.INITIAL_FACIES_DRAFT,
        modes=frozenset({"vertex", "segment", "intersection"}),
        tolerance_px=12.0,
        topological=True,
        rationale=(
            "解释草稿的相单元需要互相拼接：边界簇 profile 同款——"
            "顶点+段+交点 + 拓扑编辑"
        ),
    ),
    "general": SnappingProfile(
        role=LayerRole.USER_GENERAL,
        modes=frozenset({"vertex", "segment", "midpoint"}),
        tolerance_px=10.0,
        topological=False,
        rationale="通用编辑默认：顶点+段+中点捕捉，拓扑编辑关闭",
    ),
}

#: 角色 → 簇键（缺省 general）。
_ROLE_CLUSTER: dict[LayerRole, str] = {
    LayerRole.FACIES_BOUNDARY: "boundary",
    LayerRole.INTEGRATED_BOUNDARY: "boundary",
    LayerRole.INITIAL_FACIES_DRAFT: "draft",
    LayerRole.INTEGRATED_FACIES: "draft",
    LayerRole.PALEO_SHORELINE: "shoreline",
    LayerRole.FAULT_CONSTRAINT: "fault",
    LayerRole.PROVENANCE_DIRECTION: "direction",
    LayerRole.PROVENANCE_LINE: "line_constraint",
    LayerRole.DISTRIBUTION_LINE: "line_constraint",
    LayerRole.INTERPOLATION_BOUNDARY: "polygon_constraint",
    LayerRole.MASK_BOUNDARY: "polygon_constraint",
    LayerRole.USER_GENERAL: "general",
    LayerRole.LEGACY_UNCLASSIFIED: "general",
    LayerRole.INTERPRETATION_ANNOTATION: "general",
    LayerRole.MAP_ANNOTATION: "general",
}


def recommended_profile_for_role(role: object) -> SnappingProfile | None:
    """角色 → 推荐 profile；无编辑语义/未知角色返回 None（不猜）。

    RAW 保护角色（原始相图/模型结果）不可编辑——推荐无意义，返回 None。
    """
    if isinstance(role, LayerRole):
        parsed = role
    else:
        text = str(role or "").strip().lower()
        if not text:
            return None
        try:
            parsed = LayerRole(text)
        except ValueError:
            return None
    if parsed.is_raw_protected:
        return None
    return _PROFILES.get(_ROLE_CLUSTER.get(parsed, "general"))


def profile_summary(profile: SnappingProfile) -> str:
    """profile 的一句话呈现（对话框/状态条用）。"""
    modes = "、".join(sorted(profile.modes))
    return (
        f"{profile.role.label}推荐：{modes}，容差 {profile.tolerance_px:g}px，"
        f"拓扑编辑{'开' if profile.topological else '关'}——{profile.rationale}"
    )
