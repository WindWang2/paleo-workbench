"""Geological Mapping Pipeline package: Well Data → Kriging/IDW → Grid → Contour → Layers → MapDocument → Composer."""

from __future__ import annotations

from paleo_workbench.mapping.geological_pipeline.contouring import (
    calculate_nice_contour_levels,
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.interpolator import (
    IDWInterpolator,
    Interpolator,
    KrigingInterpolator,
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    DEFAULT_GEOLOGICAL_PIPELINE,
    FACTOR_DEFAULTS,
    GeologicalMappingPipeline,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    generate_facies_polygon_layer,
)
from paleo_workbench.mapping.geological_pipeline.templates import (
    create_geological_factor_map_template,
)

__all__ = [
    "DEFAULT_GEOLOGICAL_PIPELINE",
    "FACTOR_DEFAULTS",
    "GeologicalFactor",
    "GeologicalFactorDataset",
    "GeologicalMappingPipeline",
    "IDWInterpolator",
    "InterpolationOptions",
    "Interpolator",
    "KrigingInterpolator",
    "calculate_nice_contour_levels",
    "create_geological_factor_map_template",
    "generate_contour_layer",
    "generate_facies_polygon_layer",
    "interpolate_factor",
]
