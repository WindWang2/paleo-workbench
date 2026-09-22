"""Unified single-factor map product model (M1).

``FactorMapSpec`` is the explicit *input* contract of one single-factor map and
``FactorMapOutput`` the assembled *output* bundle. Both compose existing
authorities — a spec views a ``FactorMapTask``'s inputs, an output wraps the
canonical ``FactorGridResult`` — so no second grid authority is introduced.

Spec fields an operator (or harness action) must be able to state explicitly:

* factor identity + unit (unit is *declared*; ``None`` means undeclared,
  never guessed — see ``workflow.factor_units``)
* target horizon
* source versions (catalog asset/version ids) and the producing task id
* bounds / user domain mask / exclusion polygons
* fault (break) polylines
* method label + algorithm parameters
* CRS + the distance policy the method's maths assume (decision D5)
* optional derived-factor provenance (decision D11)

The output bundle pairs the grid with its QC diagnostics and provenance so a
consumer (composer, MapProduct assembly, QA) needs exactly one object to
answer "what is this map, how was it made, how good is it".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from paleo_workbench.workflow.factor_units import (
    unit_for_factor,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "FactorMapSpec",
    "FactorMapOutput",
    "spec_from_task",
]

# Distance policies the interpolation maths may assume (decision D5):
# ``planar``        — coordinates are map/project metres (default expectation).
# ``planar_degrees``— explicit operator exemption: geographic degrees treated
#                     as planar; legal for small extents, results are annotated.
# ``projected``     — inputs were reprojected to a projected CRS beforehand.
DISTANCE_POLICIES = ("planar", "planar_degrees", "projected")


@dataclass(frozen=True, slots=True)
class FactorMapSpec:
    """Explicit, serialisable, fingerprintable input contract of one factor map."""

    factor_name: str
    method: str
    target_horizon: str = ""
    unit: str | None = None
    crs: str | None = None
    distance_policy: str = "planar"
    parameters: dict[str, Any] = field(default_factory=dict)
    bounds: tuple[float, float, float, float] | None = None
    mask_polygon: list[list[float]] | None = None
    exclusion_polygons: list[list[list[float]]] = field(default_factory=list)
    fault_polylines: list[list[list[float]]] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    task_id: str | None = None
    derived_rule: str | None = None

    def __post_init__(self) -> None:
        if self.distance_policy not in DISTANCE_POLICIES:
            raise ValueError(
                f"distance_policy must be one of {DISTANCE_POLICIES}, "
                f"got {self.distance_policy!r}"
            )

    # ----- serialisation -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "factor_name": self.factor_name,
            "method": self.method,
            "target_horizon": self.target_horizon,
            "unit": self.unit,
            "crs": self.crs,
            "distance_policy": self.distance_policy,
            "parameters": self.parameters,
            "bounds": list(self.bounds) if self.bounds is not None else None,
            "mask_polygon": self.mask_polygon,
            "exclusion_polygons": self.exclusion_polygons,
            "fault_polylines": self.fault_polylines,
            "source_refs": list(self.source_refs),
            "task_id": self.task_id,
            "derived_rule": self.derived_rule,
        }
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FactorMapSpec":
        def _ring(ring, what: str) -> list[list[float]]:
            pts = [[float(v) for v in pt] for pt in ring]
            for pt in pts:
                if len(pt) != 2:
                    raise ValueError(f"{what} points must be (x, y) pairs")
                import math as _math

                if not (_math.isfinite(pt[0]) and _math.isfinite(pt[1])):
                    raise ValueError(f"{what} points must be finite")
            return pts

        bounds = data.get("bounds")
        if bounds is not None:
            values = [float(v) for v in bounds]
            import math as _math

            if len(values) != 4 or not all(_math.isfinite(v) for v in values):
                raise ValueError(
                    "bounds must be exactly 4 finite numbers (xmin, ymin, xmax, ymax)"
                )
            bounds = tuple(values)
        mask = data.get("mask_polygon")
        if mask is not None:
            mask = _ring(mask, "mask_polygon")
            if len(mask) < 3:
                raise ValueError("mask_polygon needs at least 3 vertices")
        exclusions = [
            _ring(ring, "exclusion_polygons")
            for ring in (data.get("exclusion_polygons") or [])
        ]
        faults = [
            _ring(line, "fault_polylines")
            for line in (data.get("fault_polylines") or [])
        ]
        return cls(
            factor_name=str(data["factor_name"]),
            method=str(data["method"]),
            target_horizon=str(data.get("target_horizon") or ""),
            unit=data.get("unit"),
            crs=data.get("crs"),
            distance_policy=str(data.get("distance_policy") or "planar"),
            parameters=dict(data.get("parameters") or {}),
            bounds=bounds,
            mask_polygon=mask,
            exclusion_polygons=exclusions,
            fault_polylines=faults,
            source_refs=list(data.get("source_refs") or []),
            task_id=data.get("task_id"),
            derived_rule=data.get("derived_rule"),
        )

    def fingerprint(self) -> str:
        """Stable SHA-256 over the scientific content of the spec (order-sensitive
        for point lists, key-sorted for parameters)."""
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def with_declared_unit(self) -> "FactorMapSpec":
        """Return a spec whose undeclared unit is resolved from the factor
        defaults authority (an unknown factor keeps ``None``)."""
        if self.unit is not None:
            return self
        return FactorMapSpec(
            factor_name=self.factor_name,
            method=self.method,
            target_horizon=self.target_horizon,
            unit=unit_for_factor(self.factor_name),
            crs=self.crs,
            distance_policy=self.distance_policy,
            parameters=dict(self.parameters),
            bounds=self.bounds,
            mask_polygon=self.mask_polygon,
            exclusion_polygons=list(self.exclusion_polygons),
            fault_polylines=list(self.fault_polylines),
            source_refs=list(self.source_refs),
            task_id=self.task_id,
            derived_rule=self.derived_rule,
        )


@dataclass(slots=True)
class FactorMapOutput:
    """Assembled output bundle of one single-factor map run.

    ``grid`` is the canonical ``FactorGridResult``; ``qc``/``provenance`` carry
    the diagnostics and lineage that surround it. Map layers are materialised
    on demand through the geological pipeline adapters (lazy import keeps this
    module importable without PySide6).
    """

    spec: FactorMapSpec
    grid: FactorGridResult
    qc: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    # ----- assembly ------------------------------------------------------------
    @classmethod
    def from_task_result(
        cls,
        spec: FactorMapSpec,
        grid: FactorGridResult,
        *,
        task_parameters: Mapping[str, Any] | None = None,
        extra_qc: Mapping[str, Any] | None = None,
    ) -> "FactorMapOutput":
        """Assemble the output bundle from a spec + its canonical grid result.

        QC/provenance are read from what the run actually recorded (task
        parameters + grid algorithm parameters) — never re-invented here.
        """
        params = dict(task_parameters or {})
        qc: dict[str, Any] = {
            "r_squared": grid.algorithm_parameters.get("r_squared"),
            "n_points": grid.algorithm_parameters.get("n_points")
            or len(grid.input_points),
            "variance_min": grid.algorithm_parameters.get("variance_min"),
            "variance_max": grid.algorithm_parameters.get("variance_max"),
            "duplicate_wells_dropped": params.get("duplicate_wells_dropped"),
        }
        if extra_qc:
            qc.update(extra_qc)
        provenance: dict[str, Any] = {
            "generator_version": grid.generator_version,
            "algorithm_id": grid.algorithm_id,
            "algorithm_parameters": dict(grid.algorithm_parameters),
            "source_refs": list(grid.source_refs),
            "run_ref": grid.run_ref,
            "spec_fingerprint": spec.fingerprint(),
            "unit_declared": grid.unit is not None,
            "crs_declared": grid.crs is not None,
        }
        if spec.derived_rule:
            provenance["derived_rule"] = spec.derived_rule
        return cls(spec=spec, grid=grid, qc=qc, provenance=provenance)

    # ----- consumers -----------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """JSON-safe summary for product descriptions and QA surfaces."""
        return {
            "spec": self.spec.to_dict(),
            "grid": self.grid.to_descriptor(),
            "qc": self.qc,
            "provenance": self.provenance,
        }

    def build_map_layers(
        self,
        *,
        include_grid: bool = True,
        include_contours: bool = True,
        include_wells: bool = True,
        include_polygons: bool = False,
    ) -> list:
        """Materialise the standard GIS layers for this factor map.

        Delegates to the geological pipeline (single layer-construction
        authority); the lazy import keeps module import free of PySide6.
        """
        from paleo_workbench.mapping.geological_pipeline.pipeline import (
            GeologicalMappingPipeline,
        )
        from paleo_workbench.mapping.geological_pipeline.models import (
            GeologicalFactor,
            GeologicalFactorDataset,
        )

        pipeline = GeologicalMappingPipeline()
        dataset = GeologicalFactorDataset(
            factor_name=self.grid.factor_name,
            unit=self.grid.unit or "",
            target_horizon=self.spec.target_horizon,
            crs=self.grid.crs or "",
            points=[
                GeologicalFactor(
                    name=self.grid.factor_name,
                    value=float(pt.get("z", 0.0)),
                    unit=self.grid.unit or "",
                    well_id=str(pt.get("well_id") or ""),
                    well_name=str(pt.get("name") or pt.get("well_id") or ""),
                    x=float(pt.get("x", 0.0)),
                    y=float(pt.get("y", 0.0)),
                    crs=self.grid.crs or "",
                )
                for pt in self.grid.input_points
                if isinstance(pt, Mapping)
            ],
        )
        layers: list = []
        clip_ring = self.spec.mask_polygon
        if include_grid:
            layers.append(pipeline.create_grid_layer(self.grid))
        if include_polygons:
            layers.append(
                pipeline.create_polygon_layer(self.grid, clip_ring=clip_ring)
            )
        if include_contours:
            layers.append(
                pipeline.create_contour_layer(self.grid, clip_ring=clip_ring)
            )
        if include_wells:
            layers.append(pipeline.create_well_point_layer(dataset))
        return layers


def spec_from_task(task, *, project=None) -> FactorMapSpec:
    """Build a :class:`FactorMapSpec` view over a ``FactorMapTask``.

    The task remains the persisted authority (project document); the spec is
    the typed, fingerprintable contract derived from it. Unit is declared on
    the task parameters when present, otherwise resolved from the factor
    defaults authority (unknown factor → ``None``, never guessed).
    """
    params = dict(getattr(task, "parameters", None) or {})
    factor_name = str(getattr(task, "factor_type", None) or task.name or "")
    method = str(
        params.get("method")
        or getattr(task, "method", None)
        or "IDW"
    )
    declared_unit = params.get("unit")
    if declared_unit is None:
        declared_unit = unit_for_factor(factor_name)
    crs = None
    if project is not None:
        crs = getattr(project.coordinate, "project_crs", None)
    spec = FactorMapSpec(
        factor_name=factor_name,
        method=method,
        target_horizon=str(getattr(task, "target_horizon", None) or ""),
        unit=declared_unit,
        crs=crs,
        distance_policy=str(params.get("distance_policy") or "planar"),
        parameters={
            key: value
            for key, value in params.items()
            if key in ("grid_n", "power", "azimuth_deg", "semi_major", "semi_minor")
        },
        bounds=None,
        mask_polygon=params.get("mask_polygon"),
        exclusion_polygons=list(params.get("exclusion_polygons") or []),
        fault_polylines=list(params.get("break_polylines") or []),
        source_refs=list(getattr(task, "input_resource_ids", None) or []),
        task_id=getattr(task, "id", None),
        derived_rule=params.get("derived_rule"),
    )
    return spec
