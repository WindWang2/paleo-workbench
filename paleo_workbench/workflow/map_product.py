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
