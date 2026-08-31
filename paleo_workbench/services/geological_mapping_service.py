"""Headless and UI-independent Application Service for Geological Mapping.

Provides a clean API for creating, interpolating, and compiling geological factor maps,
designed for direct invocation by UI controllers, batch background workers, and AI Harness.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Sequence

from paleo_workbench.mapping.geological_pipeline import (
    DEFAULT_GEOLOGICAL_PIPELINE,
    FACTOR_DEFAULTS,
    GeologicalFactorDataset,
    GeologicalMappingPipeline,
    InterpolationOptions,
)
from paleo_workbench.mapping.layers import MapDocument
from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
    WellTable,
    WellTableRow,
)

logger = logging.getLogger(__name__)


class GeologicalMappingService:
    """Application Service orchestrating Geological Factor Mapping."""

    def __init__(self, pipeline: GeologicalMappingPipeline | None = None) -> None:
        self.pipeline = pipeline or DEFAULT_GEOLOGICAL_PIPELINE

    def extract_well_factors(
        self,
        project: ProjectDocument,
        factor_name: str,
        *,
        target_horizon: str = "",
        well_table_id: str | None = None,
        unit: str | None = None,
    ) -> GeologicalFactorDataset:
        """Extract geological factor points from project well tables or well logs."""
        resolved_horizon = target_horizon or getattr(project.stratigraphy, "target_horizon", "") or "T1"
        records: list[dict[str, Any]] = []

        # 1. Search in matching WellTables
        matched_tables: list[WellTable] = []
        if well_table_id:
            matched_tables = [wt for wt in project.well_tables if wt.id == well_table_id]
        else:
            matched_tables = [
                wt for wt in project.well_tables
                if (not wt.target_horizon or wt.target_horizon == resolved_horizon)
            ]

        for wt in matched_tables:
            for r in wt.rows:
                records.append({
                    "well_id": r.well_id,
                    "name": r.name,
                    "x": r.x,
                    "y": r.y,
                    "z": r.z,
                    "H_s": r.H_s,
                    "H_t": r.H_t,
                    "R_s": r.R_s,
                    "qc_flag": r.qc_flag,
                    "attributes": r.attributes,
                    "properties": r.attributes,
                })

        # 2. Search in project domain wells (WellEntity)
        if not records:
            domain_wells = getattr(project, "wells", None) or []
            if not domain_wells and hasattr(project, "workarea") and project.workarea is not None:
                domain_wells = getattr(project.workarea, "wells", None) or []
            for well in domain_wells:
                wx = well.project_x if well.project_x is not None else well.surface_x
                wy = well.project_y if well.project_y is not None else well.surface_y
                if wx is None or wy is None:
                    continue
                try:
                    fx, fy = float(wx), float(wy)
                    if not (math.isfinite(fx) and math.isfinite(fy)):
                        continue
                except (TypeError, ValueError):
                    continue

                status = str(getattr(well, "coordinate_status", "ok") or "ok").lower()
                if status == "invalid":
                    continue

                meta = dict(getattr(well, "metadata", None) or {})
                attrs = dict(getattr(well, "attributes", None) or {})
                props = {**meta, **attrs}

                records.append({
                    "well_id": getattr(well, "id", "") or getattr(well, "uwi", "") or well.name,
                    "name": getattr(well, "name", "") or getattr(well, "uwi", "") or getattr(well, "id", ""),
                    "x": fx,
                    "y": fy,
                    "z": getattr(well, "surface_z", None),
                    "qc_flag": "ok",
                    "attributes": props,
                    "properties": props,
                    **props,
                })

        # 3. If no well table or domain well records, extract from sample points in existing factor tasks
        if not records:
            for task in project.factor_map_tasks:
                if (not task.target_horizon or task.target_horizon == resolved_horizon) and task.factor_type == factor_name:
                    pts = task.parameters.get("sample_points") or []
                    for pt in pts:
                        records.append({
                            "well_id": pt.get("well", ""),
                            "name": pt.get("well", ""),
                            "x": pt.get("x", 0.0),
                            "y": pt.get("y", 0.0),
                            "value": pt.get("value", 0.0),
                        })
                    if records:
                        break

        # 4. Fallback: synthesize realistic sample points across project extent if project has 0 well records
        synthesized = False
        if not records:
            from geoviz import synthetic_sample_points
            raw_pts = synthetic_sample_points(seed=42, factor_type=factor_name, count=12)
            for i, p in enumerate(raw_pts):
                records.append({
                    "well_id": str(p.get("well") or f"W{i+1}"),
                    "name": str(p.get("well") or f"井-{i+1}"),
                    "x": p["x"],
                    "y": p["y"],
                    "value": p["value"],
                })
            synthesized = True

        # #1050: the authoritative CRS is project.coordinate.project_crs
        # (pydantic schema, project/models.py) — ProjectDocument has no `crs`
        # attribute, so the previous `hasattr(project, "crs")` guard was always
        # False and every factor dataset silently rendered as EPSG:4326.
        # Fallback only when the field is absent/empty.
        project_crs = str(getattr(project.coordinate, "project_crs", "") or "").strip()
        dataset = self.pipeline.extract_factors(
            records,
            factor_name=factor_name,
            target_horizon=resolved_horizon,
            unit=unit,
            crs=project_crs or "EPSG:4326",
        )
        # Anti-laundering (#848 discipline): a dataset synthesized for an
        # empty project must never be stamped "real" downstream.
        dataset.metadata["synthesized"] = synthesized
        dataset.metadata["source_table_ids"] = [wt.id for wt in matched_tables]
        return dataset

    def create_factor_map(
        self,
        project: ProjectDocument,
        factor_name: str,
        *,
        target_horizon: str = "",
        method: str = "kriging",
        grid_n: int = 50,
        color_ramp: str | None = None,
        contour_levels: list[float] | None = None,
        contour_interval: float | None = None,
        include_grid: bool = True,
        include_contours: bool = True,
        include_wells: bool = True,
        include_polygons: bool = False,
        well_table_id: str | None = None,
        title: str | None = None,
    ) -> tuple[MapDocument, FactorMapTask]:
        """End-to-end service call: extracts factors, interpolates, builds MapDocument and records task."""
        resolved_horizon = target_horizon or getattr(project.stratigraphy, "target_horizon", "") or "T1"
        defaults = FACTOR_DEFAULTS.get(factor_name, {})
        resolved_ramp = color_ramp or defaults.get("color_ramp", "porosity")

        dataset = self.extract_well_factors(
            project,
            factor_name=factor_name,
            target_horizon=resolved_horizon,
            well_table_id=well_table_id,
        )

        options = InterpolationOptions(
            method=method,
            grid_n=grid_n,
            variogram_model="spherical",
            color_ramp=resolved_ramp,
            contour_levels=contour_levels,
            contour_interval=contour_interval,
            crs=dataset.crs,
        )

        # 1. Build GIS MapDocument
        doc_title = title or f"{resolved_horizon} {factor_name} 分布图"
        map_doc = self.pipeline.build_factor_map_document(
            dataset,
            options=options,
            include_grid=include_grid,
            include_contours=include_contours,
            include_wells=include_wells,
            include_polygons=include_polygons,
            title=doc_title,
        )

        # 2. Record FactorMapTask on project
        task_name = f"{resolved_horizon} {factor_name}"
        task = FactorMapTask(
            name=task_name,
            target_horizon=resolved_horizon,
            factor_type=factor_name,
            method=method,
            parameters={
                "grid_n": grid_n,
                "color_ramp": resolved_ramp,
                "sample_count": len(dataset.valid_points),
            },
            status="complete",
            source_kind="mock" if dataset.metadata.get("synthesized") else "real",
        )
        if dataset.metadata.get("synthesized"):
            task.quality_metrics = {
                **(task.quality_metrics or {}),
                "synthesized_fallback": True,
            }
        project.factor_map_tasks.append(task)

        # 3. Create or update PaleoMapDocument compatibility record.
        # The vector features below are the interoperable payload; the
        # continuous GridMapLayer stays reachable through the factor task
        # link instead of being silently dropped by the bridge (#1034).
        # The grid is registered live under the task id (same seam the
        # workflow interpolation paths use) so overlay rendering and the
        # save-time artifact externalization both resolve it.
        for lyr in map_doc.layers:
            if getattr(lyr, "layer_type", "") == "grid" and getattr(lyr, "grid_result", None) is not None:
                from paleo_workbench.project.factor_grid_artifacts import (
                    store_live_factor_grid,
                )

                store_live_factor_grid(task.id, lyr.grid_result)
                break
        paleo_map = PaleoMapDocument(
            id=map_doc.id,
            name=doc_title,
            linked_target_horizon=resolved_horizon,
            linked_factor_task_id=task.id,
            map_crs=map_doc.crs,
        )
        # Store layer representations
        for lyr in map_doc.layers:
            if hasattr(lyr, "features") and getattr(lyr, "features"):
                if lyr.layer_type == "contour":
                    paleo_map.line_features.extend([dict(f) for f in lyr.features])
                elif lyr.layer_type == "well_point":
                    paleo_map.well_overlays.extend([dict(f) for f in lyr.features])
                elif lyr.layer_type in ("polygon", "facies"):
                    paleo_map.facies_polygons.extend([dict(f) for f in lyr.features])

        project.paleomap_documents.append(paleo_map)

        logger.info("Created geological factor map %r with %d layers", doc_title, len(map_doc.layers))
        return map_doc, task


DEFAULT_GEOLOGICAL_MAPPING_SERVICE = GeologicalMappingService()
