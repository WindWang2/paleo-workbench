"""Deterministic consultation and gap report generators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.workflow.contracts.models import ExpertQuestionStatus
from paleo_workbench.workflow.contracts.registry import (
    WorkflowContractRegistry,
    get_default_registry,
)
from paleo_workbench.workflow.contracts.readiness import WorkflowReadinessEvaluator


SECTION_ORDER = [
    ("data", "数据"),
    ("well_log", "测井模块"),
    ("seismic", "地震模块"),
    ("interpretation", "地层解释"),
    ("factor", "单因素图"),
    ("prediction", "预测"),
    ("mapping", "古地理编图"),
    ("qc", "QC"),
    ("export", "导出"),
    ("joint", "井震联合"),
    ("modeling", "三维建模"),
]


def generate_consultation_report(
    *,
    registry: WorkflowContractRegistry | None = None,
    project: Any | None = None,
) -> str:
    reg = registry or get_default_registry()
    lines: list[str] = [
        "# 古地理工作台 — 专业地质工作流咨询报告",
        "",
        "本报告由软件合同（Workflow Contract）自动生成。",
        "标注为 **待专家确认** 的问题不得由软件擅自裁定。",
        "",
        "---",
        "",
        "## 1. 模块总览",
        "",
        "| ID | 名称 | 实现状态 | 开放专家问题数 |",
        "|----|------|----------|----------------|",
    ]
    for c in reg.list_contracts():
        open_n = sum(
            1 for q in c.expert_questions if q.status is ExpertQuestionStatus.OPEN
        )
        lines.append(
            f"| `{c.id}` | {c.name_zh or c.name} | {c.implementation_status.value} | {open_n} |"
        )

    lines += ["", "## 2. 模块关系（合同级潜在依赖）", ""]
    for c in reg.list_contracts():
        up = ", ".join(c.upstream_contract_ids) or "—"
        down = ", ".join(c.downstream_contract_ids) or "—"
        lines.append(f"- **{c.name_zh or c.name}** (`{c.id}`): 上游 {up} → 下游 {down}")

    # Category sections
    by_cat: dict[str, list] = {}
    for c in reg.list_contracts():
        by_cat.setdefault(c.category, []).append(c)

    sec_i = 3
    for cat, title in SECTION_ORDER:
        contracts = by_cat.get(cat) or []
        if not contracts:
            continue
        lines += ["", f"## {sec_i}. {title}", ""]
        sec_i += 1
        for c in contracts:
            lines += _module_section(c)

    # Consolidated matrix
    lines += [
        "",
        f"## {sec_i}. 专家确认问题矩阵",
        "",
        "| 编号 | 模块 | 类别 | 当前软件实现 | 需要确认的问题 | 影响范围 | 优先级 | 状态 |",
        "|------|------|------|--------------|----------------|----------|--------|------|",
    ]
    for q in reg.all_expert_questions():
        lines.append(
            f"| `{q.id}` | `{q.module_id}` | {q.category.value} | "
            f"{_cell(q.current_software_behavior)} | {_cell(q.question)} | "
            f"{_cell(q.impact_if_unresolved)} | {q.priority.value} | {q.status.value} |"
        )

    if project is not None:
        lines += ["", f"## {sec_i + 1}. 当前工程就绪状态（元数据）", ""]
        ev = WorkflowReadinessEvaluator(reg)
        for r in ev.evaluate_all(project):
            msgs = "; ".join(x.message_zh for x in r.reasons) or "—"
            lines.append(
                f"- `{r.contract_id}`: **{r.status.value}** "
                f"({r.implementation_status.value}) — {msgs}"
            )

    lines += ["", "---", "", "*生成器: paleo_workbench.workflow.contracts.report*", ""]
    return "\n".join(lines)


def _module_section(c) -> list[str]:
    lines = [
        f"### {c.name_zh or c.name} (`{c.id}`)",
        "",
        f"**当前软件功能：** {c.description_zh or c.description}",
        f"**实现状态：** {c.implementation_status.value}",
        "",
        "#### 输入",
    ]
    if not c.inputs:
        lines.append("- （无结构化输入声明）")
    for inp in c.inputs:
        req = "必需" if inp.required else "可选"
        lines.append(f"- {inp.name}（{req}，{inp.cardinality.value}）— {inp.description}")
    lines += ["", "#### 主要操作"]
    for i, op in enumerate(c.operations, 1):
        lines.append(f"{i}. **用户：** {op.user_action or op.name}")
        if op.software_action:
            lines.append(f"   **软件：** {op.software_action}")
    lines += ["", "#### 输出"]
    for out in c.outputs:
        lines.append(
            f"- {out.name} [{out.output_class}] stage={out.data_stage or '—'} "
            f"versioned={out.versioned}"
        )
    lines += ["", "#### 上下游连接"]
    lines.append(f"- 上游（合同）：{', '.join(c.upstream_contract_ids) or '—'}")
    lines.append(f"- 下游（合同）：{', '.join(c.downstream_contract_ids) or '—'}")
    if c.datarun_operations:
        lines.append(f"- DataRun.operation：{', '.join(c.datarun_operations)}")
    lines += ["", "#### 当前软件规则 / QC"]
    for qc in c.qc_rules:
        impl = "已实现" if qc.implemented else "未实现"
        lines.append(f"- [{qc.severity.value}] {qc.name}（{impl}）")
    lines += ["", "#### 待专家确认"]
    open_q = [q for q in c.expert_questions if q.status is ExpertQuestionStatus.OPEN]
    if not open_q:
        lines.append("- （无开放问题）")
    for q in open_q:
        lines.append(f"- **[{q.priority.value}]** {q.question}")
        lines.append(f"  - 现状：{q.current_software_behavior}")
    lines.append("")
    return lines


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def generate_gap_report(
    *,
    registry: WorkflowContractRegistry | None = None,
) -> str:
    reg = registry or get_default_registry()
    lines = [
        "# 工作流合同 — 开发缺口报告",
        "",
        "| 模块 | 实现状态 | 缺失校验 | 缺失持久化/版本 | 缺失 lineage op | Demo-only | 开放专家问题 |",
        "|------|----------|----------|-----------------|-----------------|-----------|--------------|",
    ]
    for c in reg.list_contracts():
        missing_val = []
        if not any(q.implemented for q in c.qc_rules) and c.category not in {
            "well_log",
            "seismic",
        }:
            if not c.qc_rules:
                missing_val.append("no_qc")
        missing_persist = []
        for o in c.outputs:
            if o.output_class == "scientific" and not o.versioned:
                missing_persist.append(o.id)
        missing_lineage = []
        if c.id in {
            "factor_interpolation",
            "facies_prediction",
            "export",
            "horizon_interpretation",
            "paleomap_compile",
            "quality_control",
        } and not c.datarun_operations:
            missing_lineage.append("no_datarun_op")
        demo = "yes" if c.implementation_status.value in {"DEMO", "PLACEHOLDER"} else "no"
        open_n = sum(
            1 for q in c.expert_questions if q.status is ExpertQuestionStatus.OPEN
        )
        lines.append(
            f"| `{c.id}` | {c.implementation_status.value} | "
            f"{','.join(missing_val) or '—'} | "
            f"{','.join(missing_persist) or '—'} | "
            f"{','.join(missing_lineage) or '—'} | {demo} | {open_n} |"
        )
    lines += [
        "",
        "## 建议的下一工程优先级（严格来自缺口）",
        "",
        "1. 将 mock 预测与正式交付硬隔离（facies_prediction DEMO）。",
        "2. 为 map_compile/qc 补齐生产路径上的 DataRun 登记调用。",
        "3. 断层完整版本生命周期（当前 PARTIAL 约束折线）。",
        "4. 关闭 P0 专家问题前不要把软件默认值写成地质标准。",
        "",
    ]
    return "\n".join(lines)


def write_reports(
    out_dir: str | Path,
    *,
    project: Any | None = None,
    registry: WorkflowContractRegistry | None = None,
) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    consult = out / "geological_workflow_consultation.md"
    gap = out / "workflow_gap_report.md"
    consult.write_text(
        generate_consultation_report(registry=registry, project=project),
        encoding="utf-8",
    )
    gap.write_text(generate_gap_report(registry=registry), encoding="utf-8")
    return consult, gap
