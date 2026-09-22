"""ConstraintProduct — 约束组领域投影 + 双枚举收敛 + CRS 纪律（V9 ADR-6）。

一个约束组的身份 = ``ConstraintLayers.id``（与 constraint_versions 的
提交/版本链一致）。本模块收敛：

* **双 ConstraintKind 收敛**：地质语义 ``layer_roles.ConstraintKind``
  （10 态）是规范类型；:func:`to_engine_kind` 经
  ``CONSTRAINT_INTERPOLATION_ROLE`` 唯一映射到 engine 语义
  ``constraint_capabilities.ConstraintKind``（5 态）——同名异义枚举不再
  直传（基线 P1-4）；
* **CRS 纪律**：:func:`assert_constraints_crs_compatible` —— 已声明且
  不同的 CRS → ValueError（此前从不比对，基线 P1-3）；未声明 → 诚实
  note（按任务 CRS 解释），绝不猜测；
* **strength/confidence**：per-line ``properties.strength/confidence``
  可选；缺省 strength=1.0（标注 default）confidence=unknown（goal §10）。

编辑生命周期（goal §11）：QGIS 负责几何编辑；commit（既有
``commit_constraint_group``）产生新 DataVersion；下游 factor 经
content-hash pins 感知（本投影只读）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.mapping_workspace.layer_roles import (
    CONSTRAINT_INTERPOLATION_ROLE,
    ConstraintKind as GeoConstraintKind,
    constraint_kind_from_value,
)
from paleo_workbench.workflow.constraint_capabilities import (
    ConstraintKind as EngineConstraintKind,
)

#: ConstraintLine.role（插值引擎兼容语义）→ engine 约束词汇。
_ROLE_TO_ENGINE_KIND: dict[str, EngineConstraintKind] = {
    "break": EngineConstraintKind.BARRIER,
    "direction": EngineConstraintKind.DIRECTION,
    "boundary": EngineConstraintKind.BOUNDARY_MASK,
}


def to_engine_kind(geo_kind: "GeoConstraintKind | str") -> EngineConstraintKind | None:
    """地质约束类型 → engine 约束类型（唯一映射；未知 → None，不猜）。"""
    resolved = (constraint_kind_from_value(str(geo_kind))
                if not isinstance(geo_kind, GeoConstraintKind) else geo_kind)
    if resolved is None:
        return None
    role = CONSTRAINT_INTERPOLATION_ROLE.get(resolved, "")
    return _ROLE_TO_ENGINE_KIND.get(str(role))


def assert_constraints_crs_compatible(
    factor_crs: str | None,
    constraint_crs: str | None,
    *,
    context: str = "",
) -> str:
    """约束 CRS 与 factor CRS 的纪律检查（基线 P1-3）。

    * 双方已声明且不同 → ``ValueError``（绝不静默混合坐标）；
    * 任一方未声明 → 返回诚实 note（未声明方按对方坐标系解释）；
    * 双方一致 → 返回 ""（无异常说明）。
    """
    a = str(factor_crs or "").strip()
    b = str(constraint_crs or "").strip()
    prefix = f"[{context}] " if context else ""
    if a and b and a != b:
        raise ValueError(
            f"{prefix}constraint CRS {b!r} differs from factor CRS {a!r} — "
            "reproject the constraint group before interpolation "
            "(mixed coordinates are never silently mixed)"
        )
    if a and not b:
        return f"{prefix}constraint CRS undeclared — interpreted in factor CRS {a!r}"
    if b and not a:
        return f"{prefix}factor CRS undeclared — constraints assumed {b!r}"
    if not a and not b:
        return f"{prefix}both CRSs undeclared — coordinates assumed consistent (unverified)"
    return ""


@dataclass(frozen=True)
class ConstraintLineSummary:
    """单条约束线的投影（identity/role/kind/strength/confidence/geometry）。"""

    line_id: str
    name: str
    role: str                       # engine role (break/direction/boundary/...)
    geo_kind: str                   # 地质类型（""=未标注）
    active: bool
    n_points: int
    strength: float = 1.0
    strength_declared: bool = False
    confidence: str = "unknown"     # unknown | low | medium | high（声明才有效）
    content_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "name": self.name,
            "role": self.role,
            "geo_kind": self.geo_kind,
            "active": self.active,
            "n_points": self.n_points,
            "strength": self.strength,
            "strength_declared": self.strength_declared,
            "confidence": self.confidence,
            "content_fingerprint": self.content_fingerprint,
        }


@dataclass(frozen=True)
class ConstraintProduct:
    """一个约束组的产品投影（载荷=文档 ConstraintLayers；版本=catalog）。"""

    constraint_id: str              # = ConstraintLayers.id（提交/版本链身份）
    name: str = ""
    target_horizon: str = ""
    kinds: tuple[str, ...] = ()     # 地质类型（去重）
    engine_kinds: tuple[str, ...] = ()  # engine 投影（去重）
    crs: str = ""
    crs_declared: bool = False
    lines: tuple[ConstraintLineSummary, ...] = ()
    n_active: int = 0
    #: 最新提交（"" = 从未提交 → maturity=draft）。
    committed_version_id: str = ""
    committed_content_hash: str = ""
    content_hash: str = ""          # 当前内容（含未提交编辑）
    maturity: str = "draft"         # draft | committed
    #: constraint_pins_staleness 词汇：current/unpinned/unknown/missing/
    #: stale_version/stale_content（""=未评估）。
    staleness: str = ""
    staleness_detail: str = ""
    source: str = "user"            # user | imported | derived
    validity: str = ""              # 诚实校验说明（空=未见异常）

    @property
    def has_uncommitted_edits(self) -> bool:
        return bool(
            self.committed_content_hash
            and self.content_hash
            and self.committed_content_hash != self.content_hash
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "name": self.name,
            "target_horizon": self.target_horizon,
            "kinds": list(self.kinds),
            "engine_kinds": list(self.engine_kinds),
            "crs": self.crs,
            "crs_declared": self.crs_declared,
            "lines": [line.to_dict() for line in self.lines],
            "n_active": self.n_active,
            "committed_version_id": self.committed_version_id,
            "committed_content_hash": self.committed_content_hash,
            "content_hash": self.content_hash,
            "maturity": self.maturity,
            "staleness": self.staleness,
            "staleness_detail": self.staleness_detail,
            "source": self.source,
            "validity": self.validity,
        }


def _line_summary(line: Any) -> ConstraintLineSummary:
    props = dict(getattr(line, "properties", None) or {})
    geo_kind = str(props.get("constraint_kind") or "")
    if constraint_kind_from_value(geo_kind) is None:
        geo_kind = ""
    strength_declared = "strength" in props
    try:
        strength = float(props.get("strength", 1.0)) if strength_declared else 1.0
    except (TypeError, ValueError):
        strength, strength_declared = 1.0, False
    confidence = str(props.get("confidence", "") or "unknown")
    if confidence not in ("low", "medium", "high"):
        confidence = "unknown"  # 未声明不猜
    coords = getattr(line, "coordinates", None) or []
    return ConstraintLineSummary(
        line_id=str(getattr(line, "id", "") or ""),
        name=str(getattr(line, "name", "") or ""),
        role=str(getattr(line, "role", "") or ""),
        geo_kind=geo_kind,
        active=bool(getattr(line, "active", True)),
        n_points=len(coords),
        strength=strength,
        strength_declared=strength_declared,
        confidence=confidence,
        content_fingerprint=str(props.get("content_fingerprint", "") or ""),
    )


def constraint_product_for_group(
    document: Any,
    group: Any,
    *,
    catalog: Any = None,
) -> ConstraintProduct:
    """文档约束组 → ConstraintProduct（只读投影）。"""
    from paleo_workbench.workflow.constraint_versions import (
        constraint_group_content_hash,
    )

    lines = tuple(_line_summary(line) for line in (group.lines or []))
    kinds: list[str] = []
    engine: list[str] = []
    for line in lines:
        if line.geo_kind and line.geo_kind not in kinds:
            kinds.append(line.geo_kind)
        engine_kind = to_engine_kind(line.geo_kind) if line.geo_kind else None
        if line.role:
            mapped = _ROLE_TO_ENGINE_KIND.get(line.role)
            if mapped is not None and mapped.value not in engine:
                engine.append(mapped.value)
        if engine_kind is not None and engine_kind.value not in engine:
            engine.append(engine_kind.value)

    committed_version = ""
    committed_hash = ""
    try:
        from paleo_workbench.workflow.constraint_versions import (
            current_constraint_version,
        )

        if catalog is not None:
            latest = current_constraint_version(catalog, str(group.id))
            if latest is not None:
                committed_version = str(getattr(latest, "id", "") or "")
                meta = dict(getattr(latest, "metadata", None) or {})
                committed_hash = str(meta.get("content_hash", "") or "")
    except Exception:  # noqa: BLE001 — 版本链缺失诚实为 draft
        committed_version, committed_hash = "", ""

    content_hash = ""
    try:
        content_hash, _n = constraint_group_content_hash(group)
    except Exception:  # noqa: BLE001 — 内容哈希失败 → 空串（不阻断投影）
        content_hash = ""

    # 组级 staleness：最新提交是否仍为 live 内容（resolve_constraint_ref
    # 的诚实词汇：current/stale/superseded/unknown；未提交→""=未评估）。
    staleness = ""
    staleness_detail = ""
    if committed_version:
        try:
            from paleo_workbench.workflow.constraint_versions import (
                resolve_constraint_ref,
            )

            verdict = resolve_constraint_ref(
                document, catalog,
                f"constraints:{group.id}:{committed_version}")
            staleness = str(verdict.get("status", "") or "")
            staleness_detail = str(verdict.get("detail", "") or "")
        except Exception:  # noqa: BLE001 — 解析失败 → 未评估
            staleness, staleness_detail = "unknown", "约束版本解析失败"
    elif content_hash:
        staleness = "uncommitted"
        staleness_detail = "约束组从未提交——无版本链，内容以 live 文档为准"

    validity = ""
    if committed_hash and content_hash and committed_hash != content_hash:
        validity = "存在未提交编辑（live 内容 ≠ 最新提交）"

    crs = str(getattr(group, "crs", "") or "")
    return ConstraintProduct(
        constraint_id=str(group.id),
        name=str(getattr(group, "name", "") or ""),
        target_horizon=str(getattr(group, "target_horizon", "") or ""),
        kinds=tuple(kinds),
        engine_kinds=tuple(engine),
        crs=crs,
        crs_declared=bool(crs),
        lines=lines,
        n_active=sum(1 for line in lines if line.active),
        committed_version_id=committed_version,
        committed_content_hash=committed_hash,
        content_hash=content_hash,
        maturity="committed" if committed_version else "draft",
        staleness=staleness,
        staleness_detail=staleness_detail,
        validity=validity,
    )


def constraint_products_for_document(
    document: Any,
    *,
    catalog: Any = None,
) -> list[ConstraintProduct]:
    return [
        constraint_product_for_group(document, group, catalog=catalog)
        for group in (getattr(document, "constraint_layers", None) or [])
    ]
