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
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass
class MapProductResult:
    product_name: str
    record_id: str
    output_version_id: str
    run_id: str
    scientific_fingerprint: str


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
        },
        generator=GENERATOR_ID,
    )
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

    record = MapProductRecord(
        product_name=assembly.product_name,
        factor_task_ids=list(assembly.factor_task_ids),
        interpretation_refs=list(assembly.interpretation_refs),
        composition_ref=assembly.composition_ref,
        notes=assembly.notes,
        output_version_id=version.id,
        run_id=run.id,
        scientific_fingerprint=fingerprint,
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
                "checksum": str(getattr(version, "checksum", "") or "") or None,
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
