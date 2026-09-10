"""V9 Geological Interpretation & Compilation Workbench — domain spine.

统一领域脊柱（ADR-1，docs/development/geological-interpretation-v9/01-domain-model.md）：

* :mod:`evidence` — 统一 Evidence 契约（类型化选择器 + 解析结果）；
* :mod:`factor_product` — FactorProduct 投影（grid/contours/polygons/uncertainty/QC 同一产品）；
* :mod:`constraint_product` — ConstraintProduct 投影（组身份 + 版本链 + CRS 纪律）；
* :mod:`compilation` — CompilationInputSet（pin 输入版本，可 freeze）；
* :mod:`integrated_interpretation` — IntegratedInterpretation 一等成果；
* :mod:`revision` — InterpretationRevision（人工解释溯源）；
* :mod:`algorithm_registry` — AlgorithmSpec 能力唯一权威；
* :mod:`summaries` — Inspector 摘要契约（FactorSummary 等）；
* :mod:`version_compare` — 统一版本比较入口；
* :mod:`staleness` — 统一 staleness 词汇 + 贯通传播。

所有对象都是 **投影/索引**（ADR-2）：载荷与版本唯一权威是 Catalog
（DataAsset/DataVersion/DataRun）+ ProjectDocument；本包绝不复制载荷，
不建第二数据库。
"""
from paleo_workbench.workflow.interpretation.evidence import (
    EvidenceKind,
    EvidenceResolution,
    EvidenceSelector,
    EvidenceStatus,
    available_evidence,
    format_evidence_selector,
    parse_evidence_selector,
    resolve_evidence,
)

__all__ = [
    "EvidenceKind",
    "EvidenceResolution",
    "EvidenceSelector",
    "EvidenceStatus",
    "available_evidence",
    "format_evidence_selector",
    "parse_evidence_selector",
    "resolve_evidence",
]
