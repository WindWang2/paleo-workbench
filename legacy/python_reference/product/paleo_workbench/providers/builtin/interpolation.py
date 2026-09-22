"""Built-in interpolation providers (P2-B).

Thin, honest adapters over the production interpolation engines
(:mod:`paleo_workbench.mapping.geological_pipeline.interpolator`) — the
Kriging/IDW implementations stay where they are; the provider adds only the
capability contract (descriptor, schema, admission profile, provenance).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from paleo_workbench.mapping.geological_pipeline.interpolator import interpolate_factor
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.providers.base import ProviderContext
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
)
from paleo_workbench.providers.errors import ProviderRejectedInputError
from paleo_workbench.providers.refs import (
    ArtifactRef,
    FactorDatasetRef,
    ProviderResult,
)

_INTERPOLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grid_n": {"type": "integer", "minimum": 4, "maximum": 2000, "description": "输出网格分辨率 (grid_n × grid_n)"},
        "power": {"type": "number", "minimum": 0.5, "maximum": 8.0, "description": "IDW 距离幂"},
        "variogram_model": {"type": "string", "enum": ["spherical", "exponential", "gaussian"]},
        "search_radius": {"type": "number", "minimum": 0.0},
        "min_neighbors": {"type": "integer", "minimum": 1, "maximum": 64},
        "max_neighbors": {"type": "integer", "minimum": 1, "maximum": 512},
        "color_ramp": {"type": "string"},
    },
    "additionalProperties": False,
}


class _InterpolationProviderBase:
    """Shared execution: dataset ref + points → engine → grid artifact."""

    _method: str = "kriging"

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        dataset = inputs.get("dataset")
        if isinstance(dataset, FactorDatasetRef):
            resolved = (context.extras or {}).get("factor_datasets", {}).get(dataset.factor_name)
            if resolved is None:
                raise ProviderRejectedInputError(
                    self.descriptor.provider_id,
                    f"factor dataset {dataset.factor_name!r} not present in context",
                )
            dataset = resolved
        if not isinstance(dataset, GeologicalFactorDataset):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'dataset' must be a GeologicalFactorDataset or FactorDatasetRef, got {type(dataset).__name__}",
            )
        if not dataset.points:
            raise ProviderRejectedInputError(self.descriptor.provider_id, "dataset has no points")

        options = InterpolationOptions(method=self._method)
        if "grid_n" in parameters:
            options.grid_n = int(parameters["grid_n"])
        if "power" in parameters and self._method == "idw":
            options.power = float(parameters["power"])
        if "variogram_model" in parameters and self._method == "kriging":
            options.variogram_model = str(parameters["variogram_model"])
        if "search_radius" in parameters:
            options.search_radius = float(parameters["search_radius"]) or None
        if "min_neighbors" in parameters:
            options.min_neighbors = int(parameters["min_neighbors"])
        if "max_neighbors" in parameters:
            options.max_neighbors = int(parameters["max_neighbors"])
        if "color_ramp" in parameters:
            options.color_ramp = str(parameters["color_ramp"])

        context.report_progress(0.05, f"{self.descriptor.display_name} 插值中")
        grid = interpolate_factor(dataset, options)
        context.report_progress(1.0, "插值完成")

        finite = grid.grid_z[np.isfinite(grid.grid_z)]
        diagnostics: dict[str, Any] = {
            "method": self._method,
            "grid_shape": list(grid.grid_z.shape),
            "point_count": len(dataset.points),
            "algorithm_id": grid.algorithm_id,
        }
        if finite.size:
            diagnostics["finite_ratio"] = round(float(finite.size) / float(grid.grid_z.size), 4)
            diagnostics["value_min"] = float(finite.min())
            diagnostics["value_max"] = float(finite.max())

        grid_key = f"{dataset.factor_name}:{self._method}:{options.grid_n}"
        return ProviderResult(
            artifacts=[
                ArtifactRef(
                    name=f"{dataset.factor_name}-{self._method}-grid",
                    kind="grid",
                    value=grid,
                    metadata={"grid_key": grid_key, "unit": dataset.unit},
                )
            ],
            diagnostics=diagnostics,
            provenance={
                "factor_name": dataset.factor_name,
                "unit": dataset.unit,
                "target_horizon": dataset.target_horizon,
            },
        )


class KrigingProvider(_InterpolationProviderBase):
    _method = "kriging"

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="interpolation.kriging",
            family=ProviderFamily.INTERPOLATION,
            version="1.0.0",
            display_name="克里金插值 (Kriging)",
            description="Ordinary kriging with fitted variogram over well factor points; wraps the production KrigingInterpolator.",
            capabilities=("interpolation", "variogram_fit"),
            input_types=("FactorDatasetRef", "GeologicalFactorDataset"),
            output_types=("FactorGridRef",),
            parameters_schema=_INTERPOLATION_SCHEMA,
            resource_profile=ResourceProfile(
                estimated_cpu_cores=2.0,
                estimated_ram_bytes=512 * 1024**2,
                io_weight=0.5,
                category="background.compute",
            ),
            deterministic=True,
        )


class IDWProvider(_InterpolationProviderBase):
    _method = "idw"

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="interpolation.idw",
            family=ProviderFamily.INTERPOLATION,
            version="1.0.0",
            display_name="IDW 反距离加权插值",
            description="Inverse-distance-weighted interpolation over well factor points; wraps the production IDWInterpolator.",
            capabilities=("interpolation",),
            input_types=("FactorDatasetRef", "GeologicalFactorDataset"),
            output_types=("FactorGridRef",),
            parameters_schema=_INTERPOLATION_SCHEMA,
            resource_profile=ResourceProfile(
                estimated_cpu_cores=1.5,
                estimated_ram_bytes=256 * 1024**2,
                io_weight=0.5,
                category="background.compute",
            ),
            deterministic=True,
        )
