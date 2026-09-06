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
    return False


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
    """Freeze/unfreeze a record: frozen records refuse clone/rerun/supersede."""
    record.frozen = bool(frozen)


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
) -> dict[str, Any]:
    """Publish gate: refuse stale or superseded products before an export.

    Publishing itself is the caller's export step; this function is the
    fail-closed gate plus its report.
    """
    problems: list[str] = []
    if record.status == PRODUCT_STATUS_SUPERSEDED:
        problems.append(f"superseded by {record.superseded_by}")
    staleness = product_staleness(record, project)
    if staleness["stale"]:
        problems.append(staleness["reason"])
    report = {
        "ok": not problems,
        "problems": problems,
        "staleness": staleness,
        "export_path": str(export_path) if export_path else None,
    }
    if problems:
        raise ValueError("product cannot be published: " + "; ".join(problems))
    return report
