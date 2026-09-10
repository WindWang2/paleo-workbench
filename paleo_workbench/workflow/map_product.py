"""MapProduct assembly: multi-factor paleogeographic products (P1-D).

The final vertical slice of the factor→product chain: a MapProduct composes
validated factor maps + interpretation references + manual adjustments +
a cartographic composition into ONE catalog OUTPUT version carrying the
complete lineage. Fail-closed discipline (compile_map_production rules):

* synthetic/mock factor inputs are refused — never laundered into a product;
* a factor task without a persisted grid version has nothing reproducible
  to compose and is refused;
* every input factor grid version lands in the run's input_version_ids;
* the payload is whatever the caller staged (typically the serialized
  composition + product manifest); the catalog owns its storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.project.models import MapProductRecord, ProjectDocument

GENERATOR_ID = "map-product-v1"


@dataclass
class MapProductAssembly:
    """Declarative recipe for one product build."""

    product_name: str
    factor_task_ids: list[str]
    interpretation_refs: list[str] = field(default_factory=list)
    composition_ref: str | None = None
    adjustments_note: str = ""
    notes: str = ""
    # Manual adjustments are recorded as free-form entries (author, what,
    # why) — the honest representation of expert editing before finalization.
    manual_adjustments: list[dict[str, Any]] = field(default_factory=list)
    # V9 (P1-6): the computational interpretation is composable into the
    # product — fusion seed version, integrated interpretation record, and
    # the pinned compilation input set join the recipe + fingerprint.
    fusion_version_id: str = ""
    integrated_interpretation_id: str = ""
    input_set_id: str = ""

    def scientific_fingerprint(self, project: ProjectDocument) -> str:
        """Deterministic content fingerprint over the assembly's inputs.

        Order-sensitive by design: the same factors assembled in a different
        order are a different scientific statement.
        """
        tasks = {
            str(t.id): t for t in getattr(project, "factor_map_tasks", None) or []
        }
        inputs = []
        for task_id in self.factor_task_ids:
            task = tasks.get(str(task_id))
            grid_version = getattr(task, "grid_artifact_version_id", "") or ""
            inputs.append([str(task_id), str(grid_version)])
        payload = {
            "name": self.product_name,
            "factors": inputs,
            "interpretations": sorted(str(r) for r in self.interpretation_refs),
            "composition": self.composition_ref or "",
            "adjustments": sorted(
                json.dumps(a, sort_keys=True, ensure_ascii=False)
                for a in self.manual_adjustments
            ),
            "fusion_version": self.fusion_version_id,
            "integrated_interpretation": self.integrated_interpretation_id,
            "input_set": self.input_set_id,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def write_product_manifest(
    project: ProjectDocument,
    *,
    product_name: str,
    factor_task_ids: list[str],
) -> Path:
    """Stage the product manifest into a caller-managed temp JSON file.

    ``assemble_map_product`` requires a staged payload FILE (the catalog
    copies it into the managed OUTPUT store).  Producers that have no
    serialized composition yet stage this manifest instead — passing a
    directory always failed assembly (v7 P0-2 regression).  The caller
    owns unlinking the returned path after assembly.
    """
    import tempfile

    tasks_by_id = {str(t.id): t for t in getattr(project, "factor_map_tasks", None) or []}
    manifest = {
        "product_name": product_name,
        "factor_tasks": [
            {
                "id": str(task.id),
                "name": str(task.name),
                "grid_version": str(getattr(task, "grid_artifact_version_id", "") or ""),
            }
            for task_id in factor_task_ids
            if (task := tasks_by_id.get(str(task_id))) is not None
        ],
        "interpretation_refs": [
            str(ref.id)
            for ref in (getattr(project, "horizon_interpretations", None) or [])
        ],
    }
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        return Path(handle.name)


@dataclass
class MapProductResult:
    product_name: str
    record_id: str
    output_version_id: str
    run_id: str
    scientific_fingerprint: str
    superseded_record_id: str | None = None


def assemble_map_product(
    project: ProjectDocument,
    *,
    assembly: MapProductAssembly,
    catalog: Any = None,
    payload_path: Path | str | None = None,
) -> MapProductResult:
    """Validate the assembly, then register the OUTPUT version + run.

    Without a catalog the function refuses: a product without lineage is
    exactly the orphan the lifecycle exists to prevent.
    """
    if not assembly.factor_task_ids:
        raise ValueError("map product needs at least one factor task")

    tasks = {str(t.id): t for t in getattr(project, "factor_map_tasks", None) or []}
    resolved = []
    for task_id in assembly.factor_task_ids:
        task = tasks.get(str(task_id))
        if task is None:
            raise ValueError(f"unknown factor task {task_id!r}")
        source = str(getattr(task, "source_kind", "") or "")
        if source in ("mock", "mixed"):
            raise ValueError(
                f"factor task {task_id!r} is {source}; synthetic factors "
                "cannot enter a product"
            )
        grid_version = getattr(task, "grid_artifact_version_id", None)
        if not grid_version:
            raise ValueError(
                f"factor task {task_id!r} has no persisted grid version; "
                "re-run its interpolation before assembling a product"
            )
        resolved.append((task, str(grid_version)))

    if catalog is None:
        raise ValueError("map product assembly requires the data catalog")
    payload = Path(payload_path) if payload_path is not None else None
    if payload is None or not payload.is_file():
        raise ValueError("map product assembly needs a staged payload file")

    fingerprint = assembly.scientific_fingerprint(project)
    # #1219: the run is booked RUNNING first and completes only after the
    # output version registers. The old default-completed booking left a
    # permanent ghost when the process died (or registration raised) between
    # the two saves — a completed run that produced nothing.
    run = catalog.register_run(
        "map_product_assembly",
        input_version_ids=[grid_version for _task, grid_version in resolved],
        parameters={
            "product_name": assembly.product_name,
            "factor_task_ids": list(assembly.factor_task_ids),
            "interpretation_refs": list(assembly.interpretation_refs),
            "composition_ref": assembly.composition_ref,
            "manual_adjustments": list(assembly.manual_adjustments),
            "notes": assembly.notes,
            "scientific_fingerprint": fingerprint,
            # Assembly-time per-factor truth: what the product ACTUALLY
            # consumed. Comparisons must read this, not the live tasks
            # (which keep evolving after the product exists).
            "factor_snapshot": [
                {
                    "task_id": str(task.id),
                    "method": str(getattr(task, "method", "") or ""),
                    "parameters": dict(getattr(task, "parameters", None) or {}),
                    "grid_version_id": grid_version,
                    "quality_metrics": dict(
                        getattr(task, "quality_metrics", None) or {}
                    ),
                }
                for task, grid_version in resolved
            ],
        },
        generator=GENERATOR_ID,
        status="running",
    )
    try:
        version = catalog.register_result_asset(
            name=assembly.product_name,
            type="map_product",
            format=payload.suffix.lstrip(".") or "json",
            asset_metadata={
                "product_name": assembly.product_name,
                "factor_task_ids": list(assembly.factor_task_ids),
                "scientific_fingerprint": fingerprint,
            },
            source_path=payload,
            stage=DataStage.OUTPUT,
            run_id=run.id,
            version_metadata={
                "product_name": assembly.product_name,
                "generator": GENERATOR_ID,
            },
        )
    except Exception:
        # Output registration failed: the run must NOT stay completed (or
        # running forever) — fail it with the error preserved.
        try:
            catalog.update_run_status(
                run.id, "failed", extra_parameters={
                    "error": "output registration failed"
                }
            )
        except Exception:
            pass
        raise
    catalog.update_run_status(run.id, "complete")

    record = MapProductRecord(
        product_name=assembly.product_name,
        factor_task_ids=list(assembly.factor_task_ids),
        interpretation_refs=list(assembly.interpretation_refs),
        composition_ref=assembly.composition_ref,
        notes=assembly.notes,
        output_version_id=version.id,
        run_id=run.id,
        scientific_fingerprint=fingerprint,
        manual_adjustments=list(assembly.manual_adjustments),
    )
    project.map_products = [*list(getattr(project, "map_products", None) or []), record]
    return MapProductResult(
        product_name=assembly.product_name,
        record_id=record.id,
        output_version_id=version.id,
        run_id=run.id,
        scientific_fingerprint=fingerprint,
    )


def describe_map_product(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    catalog: Any = None,
) -> dict[str, Any]:
    """One-step provenance answer for a finalized MapProduct.

    Returns what the product consumed and produced: wells (via the well
    tables its factor tasks read), interpretation versions (horizon /
    correlation / fault refs), factor maps with their persisted grid
    versions and interpolation parameters, the assembling run's generator
    and parameters, and where the output payload lives. Missing references
    are reported as ``null`` with the reason — never silently omitted.
    """
    tasks = {str(t.id): t for t in getattr(project, "factor_map_tasks", None) or []}
    tables = {str(t.id): t for t in getattr(project, "well_tables", None) or []}
    interp_index: dict[str, tuple[str, Any]] = {}
    for kind, refs in (
        ("horizon", getattr(project, "horizon_interpretations", None) or []),
        ("correlation", getattr(project, "correlation_interpretations", None) or []),
        ("fault", getattr(project, "fault_interpretations", None) or []),
    ):
        for ref in refs:
            interp_index[str(ref.id)] = (kind, ref)

    factor_maps = []
    wells: list[dict[str, Any]] = []
    seen_wells: set[str] = set()
    for task_id in record.factor_task_ids:
        task = tasks.get(str(task_id))
        if task is None:
            factor_maps.append({"task_id": str(task_id), "status": "missing_task"})
            continue
        table = tables.get(str(getattr(task, "well_table_id", "") or ""))
        if table is not None:
            for row in table.rows:
                key = str(row.well_id)
                if key in seen_wells:
                    continue
                seen_wells.add(key)
                wells.append({"well_id": key, "name": str(row.name or "")})
        factor_maps.append(
            {
                "task_id": str(task_id),
                "name": str(task.name),
                "factor_type": str(task.factor_type),
                "target_horizon": str(task.target_horizon),
                "method": str(task.method),
                "parameters": dict(task.parameters),
                "grid_version_id": str(task.grid_artifact_version_id or "") or None,
                "source_kind": str(task.source_kind),
                "well_table_id": str(task.well_table_id) if task.well_table_id else None,
            }
        )

    interpretations = []
    for ref_id in record.interpretation_refs:
        entry = interp_index.get(str(ref_id))
        if entry is None:
            interpretations.append({"ref_id": str(ref_id), "status": "missing_ref"})
            continue
        kind, ref = entry
        interpretations.append(
            {
                "ref_id": str(ref_id),
                "kind": kind,
                "name": str(ref.name),
                "current_version_id": str(ref.current_version_id or "") or None,
                "status": str(ref.status),
            }
        )

    run_info: dict[str, Any] | None = None
    if catalog is not None and record.run_id:
        try:
            run = catalog.get_run(record.run_id)
            run_info = {
                "run_id": str(run.id),
                "generator": str(getattr(run, "generator", "") or ""),
                "parameters": dict(getattr(run, "parameters", {}) or {}),
                "input_version_ids": list(getattr(run, "input_version_ids", []) or []),
                "status": str(getattr(run, "status", "") or ""),
            }
        except Exception as exc:  # catalog closed / run purged: report, don't guess
            run_info = {"run_id": str(record.run_id), "status": "unavailable", "reason": str(exc)}

    output_info: dict[str, Any] | None = None
    if catalog is not None and record.output_version_id:
        try:
            version = catalog.get_version(record.output_version_id)
            stage = getattr(version, "stage", "")
            stage_value = getattr(stage, "value", stage)
            output_info = {
                "version_id": str(version.id),
                "stage": str(stage_value or ""),
                "path": str(getattr(version, "path", "") or "") or None,
                "checksum": str(getattr(version, "sha256", "") or "") or None,
            }
        except Exception as exc:
            output_info = {
                "version_id": str(record.output_version_id),
                "status": "unavailable",
                "reason": str(exc),
            }

    return {
        "product_name": record.product_name,
        "record_id": record.id,
        "scientific_fingerprint": record.scientific_fingerprint,
        "status": str(getattr(record, "status", "final")),
        "frozen": bool(getattr(record, "frozen", False)),
        "superseded_by": getattr(record, "superseded_by", None),
        "cloned_from": getattr(record, "cloned_from", None),
        "staleness": product_staleness(record, project),
        "created_at": record.created_at,
        "wells": wells,
        "well_count": len(wells),
        "factor_maps": factor_maps,
        "interpretations": interpretations,
        "composition_ref": record.composition_ref,
        "run": run_info,
        "output": output_info,
        "notes": record.notes,
    }


# --------------------------------------------------------------------------- #
# M10 — product lifecycle: clone / rerun / compare / freeze / supersede / stale
# --------------------------------------------------------------------------- #

PRODUCT_STATUS_FINAL = "final"
PRODUCT_STATUS_SUPERSEDED = "superseded"


def find_map_product(project: ProjectDocument, record_id: str) -> MapProductRecord | None:
    """Project-side product registry lookup (records are the only index)."""
    for record in getattr(project, "map_products", None) or []:
        if str(record.id) == str(record_id):
            return record
    return None


def _record_is_frozen(record: MapProductRecord) -> bool:
    if getattr(record, "frozen", False):
        return True
    return effective_lifecycle(record) in ("frozen", "published")


#: V9 生命周期阶梯（goal §31）。legacy 记录在读取时和解：
#: frozen=True → frozen；status=superseded → superseded；其余（含旧
#: "final"）→ draft——组装完成不等于已评审。
LIFECYCLE_DRAFT = "draft"
LIFECYCLE_REVIEWED = "reviewed"
LIFECYCLE_FROZEN = "frozen"
LIFECYCLE_PUBLISHED = "published"
LIFECYCLE_SUPERSEDED = "superseded"

_LIFECYCLE_ORDER = {
    LIFECYCLE_DRAFT: 0,
    LIFECYCLE_REVIEWED: 1,
    LIFECYCLE_FROZEN: 2,
    LIFECYCLE_PUBLISHED: 3,
    LIFECYCLE_SUPERSEDED: 4,
}


def effective_lifecycle(record: MapProductRecord) -> str:
    """记录的有效生命周期（显式字段优先，legacy 标志和解兜底）。"""
    explicit = str(getattr(record, "lifecycle", "") or "")
    if explicit == LIFECYCLE_DRAFT:
        # draft 也可能与 legacy frozen 标志共存（旧 freeze 只翻布尔）。
        if getattr(record, "frozen", False):
            return LIFECYCLE_FROZEN
        if record.status == PRODUCT_STATUS_SUPERSEDED:
            return LIFECYCLE_SUPERSEDED
        return LIFECYCLE_DRAFT
    if explicit in _LIFECYCLE_ORDER:
        return explicit
    # 无字段（极旧记录）：按 legacy 标志推导。
    if getattr(record, "frozen", False):
        return LIFECYCLE_FROZEN
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        return LIFECYCLE_SUPERSEDED
    return LIFECYCLE_DRAFT


#: 产品级 QA severity 词汇（goal §30）。BLOCKER 阻断 publish。
QA_INFO = "info"
QA_WARNING = "warning"
QA_ERROR = "error"
QA_BLOCKER = "blocker"


def product_qa(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> dict[str, Any]:
    """产品级 QA（goal §30）：input/geometry/result/publication 检查 + 统一
    staleness verdict → severity 分级 findings（INFO/WARNING/ERROR/BLOCKER）。

    报告挂到 ``record.product_qa``（产品域，不再只看工程级 active report）。
    """
    findings: list[dict[str, Any]] = []

    def add(severity: str, stage: str, message: str) -> None:
        findings.append({"severity": severity, "stage": stage, "message": message})

    # 输入完备性。
    if not (record.factor_task_ids or []):
        add(QA_ERROR, "input", "产品未引用任何单因素任务")
    catalog_present = catalog is not None
    for task_id in record.factor_task_ids or []:
        task = next(
            (t for t in getattr(project, "factor_map_tasks", None) or []
             if str(t.id) == str(task_id)), None)
        if task is None:
            add(QA_ERROR, "input", f"单因素任务 {task_id} 不存在（输入缺失）")
            continue
        grid_version = str(getattr(task, "grid_artifact_version_id", "") or "")
        if not grid_version:
            add(QA_ERROR, "input", f"单因素 {task.name}：结果无登记版本")
        elif catalog_present:
            try:
                resolved = catalog.resolve_version(grid_version)
            except Exception:  # noqa: BLE001 — 解析失败按不可解析处理
                resolved = None
            if resolved is None:
                # goal §30 BLOCKER：产品输入载荷已不可解析——产品科学上
                # 已失效，发布不可被 accept_warnings 豁免。
                add(QA_BLOCKER, "input",
                    f"单因素 {task.name}：结果版本 {grid_version} 在目录中"
                    "不可解析（载荷缺失/被清理）——产品输入已失效")
        unit = (task.quality_metrics or {}).get("unit") \
            or (task.parameters or {}).get("unit")
        if not str(unit or "").strip():
            add(QA_WARNING, "input", f"单因素 {task.name}：单位未声明")
        if (task.quality_metrics or {}).get("variance_min") is None:
            add(QA_WARNING, "result", f"单因素 {task.name}：无不确定度面")
        constraint_diag = (task.parameters or {}).get("constraint_diagnostics") or {}
        if constraint_diag.get("unsupported_constraints"):
            add(QA_WARNING, "input",
                f"单因素 {task.name}：约束 "
                f"{constraint_diag['unsupported_constraints']} 被方法忽略")
        if str(getattr(task, "source_kind", "")) in ("mock", "mixed"):
            add(QA_WARNING, "input", f"单因素 {task.name}：含模拟数据")

    # 统一 staleness verdict（V9：产品域）。
    try:
        from paleo_workbench.workflow.interpretation.staleness import (
            evaluate_verdict,
        )

        verdict = evaluate_verdict(
            project, f"mapproduct:{record.id}",
            catalog=catalog, workspace_state=workspace_state)
        if verdict.verdict.value == "missing_input":
            add(QA_ERROR, "input", f"产品输入缺失：{verdict.detail}")
        elif verdict.verdict.value == "unknown":
            add(QA_WARNING, "input",
                f"产品新鲜度未知（{verdict.detail or '无溯源 run'}）——不可证明为最新")
        elif verdict.is_problem:
            add(QA_ERROR, "input",
                f"产品{verdict.label}：{verdict.detail or '上游已变化'}")
    except Exception as exc:  # noqa: BLE001 — QA 评估失败=未知，不猜通过
        add(QA_WARNING, "input", f"产品新鲜度评估失败：{exc}")

    # 溯源完备性。
    if not str(getattr(record, "run_id", "") or ""):
        add(QA_ERROR, "provenance", "产品无溯源 run（组装未登记）")
    if not str(getattr(record, "output_version_id", "") or ""):
        add(QA_ERROR, "provenance", "产品无输出版本")

    severities = {f["severity"] for f in findings}
    report = {
        "schema": 1,
        "product_id": record.id,
        "findings": findings,
        "counts": {
            severity: sum(1 for f in findings if f["severity"] == severity)
            for severity in (QA_INFO, QA_WARNING, QA_ERROR, QA_BLOCKER)
        },
        "has_blocker": QA_BLOCKER in severities,
        "has_error": QA_ERROR in severities,
        "status": ("blocked" if QA_BLOCKER in severities
                   else "error" if QA_ERROR in severities
                   else "warning" if QA_WARNING in severities
                   else "passed"),
    }
    record.product_qa = report
    return report


def review_map_product(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> dict[str, Any]:
    """draft → reviewed（需产品级 QA 无 ERROR/BLOCKER）。"""
    lifecycle = effective_lifecycle(record)
    if lifecycle != LIFECYCLE_DRAFT:
        raise ValueError(
            f"product {record.id} lifecycle is {lifecycle}; only draft products can be reviewed")
    report = product_qa(record, project, catalog=catalog,
                        workspace_state=workspace_state)
    if report["has_error"] or report["has_blocker"]:
        raise ValueError(
            f"product {record.id} cannot pass review — QA status "
            f"{report['status']}: "
            + "; ".join(f["message"] for f in report["findings"]
                        if f["severity"] in (QA_ERROR, QA_BLOCKER)))
    record.lifecycle = LIFECYCLE_REVIEWED
    return report


def clone_map_product(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    new_name: str | None = None,
    notes: str | None = None,
) -> MapProductRecord:
    """Clone a product record: same inputs, independently evolvable identity.

    The clone references the SAME catalog versions (no payload duplication —
    the catalog is the payload authority); only the record is new.
    """
    if _record_is_frozen(record):
        raise ValueError(
            f"product {record.id} is frozen; unfreeze before cloning"
        )
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        raise ValueError(
            f"product {record.id} is superseded; clone its successor instead"
        )
    clone = MapProductRecord(
        product_name=new_name or f"{record.product_name} (副本)",
        factor_task_ids=list(record.factor_task_ids),
        interpretation_refs=list(record.interpretation_refs),
        composition_ref=record.composition_ref,
        notes=notes if notes is not None else record.notes,
        output_version_id=record.output_version_id,
        run_id=record.run_id,
        scientific_fingerprint=record.scientific_fingerprint,
        cloned_from=record.id,
    )
    project.map_products = [*list(getattr(project, "map_products", None) or []), clone]
    return clone


def rerun_map_product(
    project: ProjectDocument,
    *,
    record: MapProductRecord,
    catalog: Any = None,
    payload_path: Path | str | None = None,
    assembly: MapProductAssembly | None = None,
) -> MapProductResult:
    """Re-assemble a product from the CURRENT project state.

    The recipe (factor tasks + interpretations + composition) comes from the
    existing record unless an updated *assembly* is supplied. The current
    grid versions are what assemble_map_product consumes, so a re-run after
    re-interpolation naturally produces a fresh OUTPUT version + run through
    the SAME run graph — no second pipeline. The original record is marked
    superseded by the new one.
    """
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        raise ValueError(
            f"product {record.id} is already superseded; rerun its successor instead"
        )
    if _record_is_frozen(record):
        raise ValueError(f"product {record.id} is frozen; unfreeze before rerunning")
    effective_assembly = assembly or MapProductAssembly(
        product_name=record.product_name,
        factor_task_ids=list(record.factor_task_ids),
        interpretation_refs=list(record.interpretation_refs),
        composition_ref=record.composition_ref,
        notes=record.notes,
        manual_adjustments=[
            dict(a) for a in getattr(record, "manual_adjustments", None) or []
        ],
    )
    result = assemble_map_product(
        project, assembly=effective_assembly, catalog=catalog,
        payload_path=payload_path,
    )
    successor = find_map_product(project, result.record_id)
    if successor is None:  # assemble just appended it; never expected
        raise RuntimeError("assemble_map_product did not register the successor")
    successor.cloned_from = successor.cloned_from or record.id
    record.status = PRODUCT_STATUS_SUPERSEDED
    record.superseded_by = successor.id
    record.lifecycle = LIFECYCLE_SUPERSEDED
    result.superseded_record_id = record.id
    return result


def compare_map_products(
    a: MapProductRecord,
    b: MapProductRecord,
    project: ProjectDocument,
    *,
    catalog: Any = None,
) -> dict[str, Any]:
    """Diff two product records across every lifecycle-relevant dimension.

    Structural differences (inputs/parameters/versions) are compared from the
    records + project; payload hashes when the catalog can resolve the output
    versions. Nothing is compared by payload content here — the catalog
    checksums are the hash authority.
    """
    tasks = {str(t.id): t for t in getattr(project, "factor_map_tasks", None) or []}

    def _run_factor_snapshot(record: MapProductRecord) -> dict[str, dict[str, Any]] | None:
        """Assembly-time factor truth from the record's run, when resolvable."""
        if catalog is None or not record.run_id:
            return None
        try:
            run = catalog.get_run(record.run_id)
        except Exception:
            return None
        snapshot = (getattr(run, "parameters", {}) or {}).get("factor_snapshot")
        if not isinstance(snapshot, list):
            return None
        return {
            str(entry.get("task_id")): {
                "method": entry.get("method"),
                "parameters": entry.get("parameters"),
                "grid_version_id": entry.get("grid_version_id"),
                "quality_metrics": entry.get("quality_metrics"),
            }
            for entry in snapshot
            if isinstance(entry, dict) and entry.get("task_id") is not None
        }

    def _factor_views(record: MapProductRecord) -> dict[str, dict[str, Any]]:
        view: dict[str, dict[str, Any]] = {}
        snapshot = _run_factor_snapshot(record)
        if snapshot is not None:
            return snapshot
        # No catalog / run unavailable: fall back to the LIVE task state and
        # say so — the comparison then covers structure only.
        for task_id in record.factor_task_ids:
            task = tasks.get(str(task_id))
            view[str(task_id)] = {
                "method": str(getattr(task, "method", "") or "") if task else None,
                "parameters": dict(getattr(task, "parameters", None) or {}) if task else None,
                "grid_version_id": str(getattr(task, "grid_artifact_version_id", "") or "") or None,
                "quality_metrics": dict(getattr(task, "quality_metrics", None) or {}) if task else None,
            }
        return view

    factors_a = _factor_views(a)
    factors_b = _factor_views(b)

    def _factor_source(record: MapProductRecord) -> str:
        return (
            "run_snapshot"
            if _run_factor_snapshot(record) is not None
            else "live_fallback"
        )

    factor_diff: dict[str, Any] = {
        "only_in_a": sorted(set(factors_a) - set(factors_b)),
        "only_in_b": sorted(set(factors_b) - set(factors_a)),
        "changed": {},
    }
    for task_id in sorted(set(factors_a) & set(factors_b)):
        fa, fb = factors_a[task_id], factors_b[task_id]
        differences = {
            key: {"a": fa.get(key), "b": fb.get(key)}
            for key in ("method", "parameters", "grid_version_id", "quality_metrics")
            if fa.get(key) != fb.get(key)
        }
        if differences:
            factor_diff["changed"][task_id] = differences

    def _output_hash(record: MapProductRecord) -> str | None:
        if catalog is None or not record.output_version_id:
            return None
        try:
            version = catalog.get_version(record.output_version_id)
        except Exception:
            return None
        return str(getattr(version, "sha256", "") or "") or None

    return {
        "factor_source": {"a": _factor_source(a), "b": _factor_source(b)},
        "scientific_fingerprint_equal": a.scientific_fingerprint == b.scientific_fingerprint,
        "fingerprint_a": a.scientific_fingerprint,
        "fingerprint_b": b.scientific_fingerprint,
        "factor_tasks": factor_diff,
        "interpretation_refs": {
            "only_in_a": sorted(set(a.interpretation_refs) - set(b.interpretation_refs)),
            "only_in_b": sorted(set(b.interpretation_refs) - set(a.interpretation_refs)),
        },
        "composition_ref_equal": a.composition_ref == b.composition_ref,
        "output": {
            "version_a": a.output_version_id,
            "version_b": b.output_version_id,
            "checksum_a": _output_hash(a),
            "checksum_b": _output_hash(b),
        },
    }


def product_staleness(
    record: MapProductRecord,
    project: ProjectDocument,
) -> dict[str, Any]:
    """Compare the record's fingerprint against the CURRENT project inputs.

    A product is stale when any factor task re-interpolated (new grid
    version) or the assembly membership changed since it was built.
    """
    current = MapProductAssembly(
        product_name=record.product_name,
        factor_task_ids=list(record.factor_task_ids),
        interpretation_refs=list(record.interpretation_refs),
        composition_ref=record.composition_ref,
        manual_adjustments=[
            dict(a) for a in getattr(record, "manual_adjustments", None) or []
        ],
    )
    current_fingerprint = current.scientific_fingerprint(project)
    stale = current_fingerprint != record.scientific_fingerprint
    return {
        "stale": stale,
        "record_fingerprint": record.scientific_fingerprint,
        "current_fingerprint": current_fingerprint,
        "reason": "inputs changed since assembly" if stale else "inputs unchanged",
    }


def freeze_map_product(record: MapProductRecord, *, frozen: bool = True) -> None:
    """Freeze/unfreeze a record: frozen records refuse clone/rerun/supersede.

    V9：freeze 同步显式 lifecycle（frozen 阶梯；unfreeze 回 draft——冻结
    解除即回到草稿语义，绝不停留在较高阶梯）。
    """
    record.frozen = bool(frozen)
    if frozen:
        lifecycle = effective_lifecycle(record)
        if lifecycle == LIFECYCLE_PUBLISHED:
            raise ValueError(
                f"product {record.id} is published — published products are "
                "immutable; supersede instead")
        record.lifecycle = LIFECYCLE_FROZEN
    else:
        record.lifecycle = LIFECYCLE_DRAFT


def supersede_map_product(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    successor: MapProductRecord,
) -> None:
    """Mark *record* superseded by *successor* (explicit, no re-assembly)."""
    if record is successor:
        raise ValueError("a product cannot supersede itself")
    if _record_is_frozen(record):
        raise ValueError(f"product {record.id} is frozen; unfreeze before superseding")
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        raise ValueError(
            f"product {record.id} is already superseded by "
            f"{record.superseded_by}; the first successor wins"
        )
    record.status = PRODUCT_STATUS_SUPERSEDED
    record.superseded_by = successor.id
    record.lifecycle = LIFECYCLE_SUPERSEDED


def promote_map_product(record: MapProductRecord, *, catalog: Any) -> str:
    """Promote the product's OUTPUT payload to a new immutable catalog version.

    Thin facade over the catalog authority — the product layer never copies
    payloads itself.
    """
    if catalog is None:
        raise ValueError("promote requires the data catalog")
    if not record.output_version_id:
        raise ValueError(f"product {record.id} has no output version to promote")
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        raise ValueError(
            f"product {record.id} is superseded; promote its successor instead"
        )
    version = catalog.promote_version(record.output_version_id)
    return str(version.id)


def publish_map_product(
    record: MapProductRecord,
    project: ProjectDocument,
    *,
    export_path: str | Path | None = None,
    accept_warnings: bool = True,
    catalog: Any = None,
    workspace_state: Any = None,
) -> dict[str, Any]:
    """Publish gate: refuse stale/superseded/unverifiable products (V6 §17).

    Fail-closed problems (ValueError): superseded, stale, an active QC
    report with status error, or an undeclared map CRS — those make the
    product scientifically unverifiable, not merely imperfect.

    Warnings (recorded on the report; pass ``accept_warnings=False`` to
    refuse on them too): factor units undeclared, unreviewed constraint
    diagnostics, missing uncertainty surfaces. The product publishes with
    its honesty record attached; nothing is dropped silently.

    V9 (goal §31): publish additionally requires the explicit lifecycle —
    only FROZEN products publish (draft/reviewed must review+freeze
    first), and any product-level BLOCKER finding (product_qa) refuses the
    publish regardless of ``accept_warnings``.
    """
    problems: list[str] = []
    warnings: list[str] = []
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        problems.append(f"superseded by {record.superseded_by}")
    lifecycle = effective_lifecycle(record)
    if lifecycle != LIFECYCLE_FROZEN:
        problems.append(
            f"lifecycle is {lifecycle} — only frozen products publish "
            "(review → freeze first; goal §31 ladder)"
        )
    # 产品级 QA：BLOCKER 一票否决（不可被 accept_warnings 豁免）。
    qa = product_qa(record, project, catalog=catalog,
                    workspace_state=workspace_state)
    for finding in qa.get("findings") or []:
        if finding.get("severity") == QA_BLOCKER:
            problems.append(f"[BLOCKER] {finding.get('message', '')}")
    staleness = product_staleness(record, project)
    if staleness["stale"]:
        problems.append(staleness["reason"])

    # QC status gate: the active quality report must not carry errors.
    active_qc = None
    active_qc_id = getattr(project, "active_quality_report_id", None)
    for report_obj in getattr(project, "quality_reports", None) or []:
        if active_qc_id is not None and getattr(report_obj, "id", None) == active_qc_id:
            active_qc = report_obj
            break
    if active_qc is not None and str(getattr(active_qc, "status", "")) == "error":
        problems.append(
            f"active quality report {getattr(active_qc, 'id', '?')} has status error — "
            "fix the reported issues before publishing"
        )
    # V8 M11: skipped QC rules must be visible at publish — a rule that
    # never evaluated is not a pass, and the publisher deserves to know
    # which guarantees the QC run could NOT make.
    if active_qc is not None:
        rule_status = dict(getattr(active_qc, "rule_status", None) or {})
        skipped_rules = sorted(
            rule for rule, entry in rule_status.items()
            if isinstance(entry, dict) and not entry.get("evaluated", False)
        )
        if skipped_rules:
            warnings.append(
                f"QC skipped {len(skipped_rules)} rule(s) — pass status does "
                f"not cover them: {skipped_rules}"
            )

    # kriging fallback honesty (V8 M1): a factor computed by the numpy
    # fallback fitter is degraded relative to the engine WLS authority.
    for task in project.factor_map_tasks:
        if task.id not in (record.factor_task_ids or []):
            continue
        algo = (task.grid_metadata or {}).get("algorithm_parameters") or {}
        if str(algo.get("method", "")) == "kriging_fallback" or (
            (task.parameters or {}).get("interp_backend") == "kriging_fallback"
        ):
            warnings.append(
                f"factor {task.name!r}: computed by the numpy kriging "
                "fallback (grid-OLS variogram fit, not engine WLS)"
            )

    # CRS verifiability (review R2-P0): PaleoMapDocument carries no CRS
    # field and the composition document is not addressable from the
    # project, so the CRS cannot be CONCLUSIVELY verified today — the
    # honest gate action is a recorded warning (documented limitation 13),
    # never a fabricated pass. The project-level CRS declaration is
    # reported for the caller to judge.
    project_crs = str(
        getattr(getattr(project, "coordinate", None), "project_crs", "") or ""
    ).strip()
    if record.composition_ref:
        warnings.append(
            "map CRS not verifiable from the composition reference "
            "(no CRS storage on the map document); "
            f"project CRS is {project_crs!r}"
        )
    else:
        warnings.append("no composition reference: map CRS cannot be verified")

    # Units + constraint diagnostics + uncertainty: warnings, never silent.
    if not (record.factor_task_ids or []):
        warnings.append("product references no factor tasks")
    for task in project.factor_map_tasks:
        if task.id not in (record.factor_task_ids or []):
            continue
        unit = (task.quality_metrics or {}).get("unit")
        if unit is None:
            unit = (task.parameters or {}).get("unit")
        if not str(unit or "").strip():
            warnings.append(f"factor {task.name!r}: unit undeclared")
        constraint_diag = (task.parameters or {}).get("constraint_diagnostics") or {}
        if constraint_diag.get("unsupported_constraints"):
            warnings.append(
                f"factor {task.name!r}: constraints "
                f"{constraint_diag['unsupported_constraints']} were ignored by "
                f"{constraint_diag.get('method', '?')} — review before relying on "
                "this product"
            )
        if (task.quality_metrics or {}).get("variance_min") is None:
            warnings.append(f"factor {task.name!r}: no uncertainty surface")

    if warnings and not accept_warnings:
        problems.extend(warnings)

    report = {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "staleness": staleness,
        "product_qa": qa,
        "lifecycle_before": lifecycle,
        "export_path": str(export_path) if export_path else None,
    }
    if problems:
        raise ValueError("product cannot be published: " + "; ".join(problems))
    record.lifecycle = LIFECYCLE_PUBLISHED  # 冻结阶梯顶点（不可再改）
    return report



