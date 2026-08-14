"""Metadata governance: standard asset-level fields + controlled vocabularies.

Tags stay free-form (filtering surface); governance metadata is the curated,
asset-level attribute set (来源 / 区域 / 负责人 / 学科 / 可信等级 / 审核状态).
Storage reuses the existing ``DataAsset.metadata`` dict — no schema expansion
(``CATALOG_SCHEMA_VERSION`` stays 1) — so governance is purely a validation
and vocabulary layer over the same free-form dict.

Design rules (ADR 0056 lineage):

- Fields live on the ASSET (mutable, identity-level). Version metadata stays
  immutable-with-the-version; there is deliberately no version-level update.
- ``created_time`` is NOT a governance key: ``created_at`` is already a
  first-class column on assets and versions.
- ``status`` is named ``review_status`` to avoid colliding with the existing
  processing-status vocabularies (ResourceItem.status, DataRun.status).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class GovernanceError(ValueError):
    """Raised when a governance field value is not in its vocabulary."""


@dataclass(frozen=True)
class GovernanceField:
    """One standard metadata field: key, label, optional controlled vocab."""

    key: str
    label: str
    vocabulary: tuple[str, ...] | None = None  # None = free text
    display: Mapping[str, str] = field(default_factory=dict)  # value -> zh label
    aliases: Mapping[str, str] = field(default_factory=dict)  # input -> canonical


_DISCIPLINE_ALIASES = {
    # legacy resource types / domain spellings -> discipline
    "seismic": "seismic",
    "well_log": "well_log",
    "well_log_prediction": "well_log",
    "welllog": "well_log",
    "horizon": "horizon",
    "interpretation": "interpretation",
    "correlation": "correlation",
    "stratigraphy": "correlation",
    "well_stratification": "correlation",
    "fault": "fault",
    "factor_map": "factor_map",
    "interpolation": "factor_map",
    "prediction": "prediction",
    "paleomap": "paleomap",
    "mapping": "paleomap",
    "qc": "qc",
    "export": "export",
    "modeling": "modeling",
    "general": "general",
    "tabular": "general",
    "spreadsheet": "general",
    "document": "general",
    "image_reference": "general",
    "reference_map": "general",
    "well_reference": "well_log",
    "time_depth": "well_log",
    "raster": "general",
    "vector": "general",
    "unknown": "general",
}

_DISCIPLINE_DISPLAY = {
    "seismic": "地震",
    "well_log": "测井",
    "horizon": "层位",
    "interpretation": "解释",
    "correlation": "地层对比",
    "fault": "断层",
    "factor_map": "因子制图",
    "prediction": "预测",
    "paleomap": "古地图编制",
    "qc": "质量控制",
    "export": "成果导出",
    "modeling": "三维建模",
    "general": "综合",
}

_CONFIDENCE_ALIASES = {
    "high": "high", "h": "high", "a": "high", "高": "high",
    "medium": "medium", "m": "medium", "b": "medium", "中": "medium",
    "low": "low", "l": "low", "c": "low", "低": "low",
}

_REVIEW_ALIASES = {
    "draft": "draft", "草稿": "draft",
    "pending_review": "pending_review", "pending": "pending_review",
    "待审核": "pending_review",
    "approved": "approved", "已通过": "approved", "通过": "approved",
    "rejected": "rejected", "已驳回": "rejected", "驳回": "rejected",
}

GOVERNANCE_FIELDS: dict[str, GovernanceField] = {
    f.key: f
    for f in (
        GovernanceField("source", "来源"),
        GovernanceField("region", "区域"),
        GovernanceField("creator", "负责人"),
        GovernanceField(
            "discipline",
            "学科方向",
            vocabulary=tuple(_DISCIPLINE_DISPLAY),
            display=_DISCIPLINE_DISPLAY,
            aliases=_DISCIPLINE_ALIASES,
        ),
        GovernanceField(
            "confidence",
            "可信等级",
            vocabulary=("high", "medium", "low"),
            display={"high": "高", "medium": "中", "low": "低"},
            aliases=_CONFIDENCE_ALIASES,
        ),
        GovernanceField(
            "review_status",
            "审核状态",
            vocabulary=("draft", "pending_review", "approved", "rejected"),
            display={
                "draft": "草稿",
                "pending_review": "待审核",
                "approved": "已通过",
                "rejected": "已驳回",
            },
            aliases=_REVIEW_ALIASES,
        ),
    )
}

GOVERNANCE_KEYS: tuple[str, ...] = tuple(GOVERNANCE_FIELDS)

# Internal bookkeeping keys of the asset metadata dict that a governance
# patch must never overwrite (``format`` seeds future versions' format,
# ``external`` marks unmanaged assets, ``trash``/``legacy_tags`` are
# lifecycle/migration records).
RESERVED_METADATA_KEYS = frozenset({"format", "external", "trash", "legacy_tags"})


def normalize_governance_value(key: str, value: Any) -> str:
    """Normalize one governance value; raises :class:`GovernanceError` when a
    controlled-vocabulary field receives an unknown value.

    Empty/None normalizes to ``""`` (field cleared). Free-text fields are
    stripped; whitespace collapses; a 200-char cap keeps the dict sane.
    """
    spec = GOVERNANCE_FIELDS.get(key)
    if spec is None:
        raise GovernanceError(f"unknown governance field: {key!r}")
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    if spec.vocabulary is None:
        return text[:200]
    lowered = text.casefold()
    canonical = spec.aliases.get(lowered) or spec.aliases.get(text)
    if canonical is None and lowered in spec.vocabulary:
        canonical = lowered
    elif canonical is None and text in spec.vocabulary:
        canonical = text
    if canonical is None:
        allowed = "、".join(spec.vocabulary)
        raise GovernanceError(
            f"{spec.label}({key}) 的值 {text!r} 不在受控词表中: {allowed}"
        )
    return canonical


def normalize_governance_patch(patch: Mapping[str, Any]) -> dict[str, str]:
    """Validate/normalize the governance subset of a metadata patch.

    Non-governance keys are passed through unchanged (asset.metadata stays a
    free-form dict) EXCEPT the reserved internal keys (``format`` /
    ``external`` / ``trash`` / ``legacy_tags``) which are rejected — a
    governance edit must never rewrite lifecycle bookkeeping. Governance keys
    are normalized or raise.
    """
    result: dict[str, Any] = {}
    for key, value in dict(patch).items():
        if key in RESERVED_METADATA_KEYS:
            raise GovernanceError(
                f"字段 {key!r} 是目录内部保留键，不能通过治理信息修改"
            )
        if key in GOVERNANCE_FIELDS:
            result[key] = normalize_governance_value(key, value)
        else:
            result[key] = value
    return result


def governance_values(metadata: Mapping[str, Any] | None) -> dict[str, str]:
    """Extract the governance subset of an asset metadata dict (raw values)."""
    if not metadata:
        return {}
    return {
        key: str(metadata[key])
        for key in GOVERNANCE_KEYS
        if metadata.get(key) not in (None, "")
    }


def governance_display(key: str, value: str) -> str:
    """Chinese display label for a governance value (free text passes through)."""
    spec = GOVERNANCE_FIELDS.get(key)
    if spec is None or not value:
        return value
    return spec.display.get(value, value)


def governance_display_rows(metadata: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Ordered (label, display value) rows for inspector tables."""
    rows: list[tuple[str, str]] = []
    values = governance_values(metadata)
    for key in GOVERNANCE_KEYS:
        if key in values:
            rows.append(
                (GOVERNANCE_FIELDS[key].label, governance_display(key, values[key]))
            )
    return rows
