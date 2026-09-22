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

# HAS_CPP probe (CONV-20): True only when the optional `pwb_mapping_kernel`
# pybind11 module is importable. The thin facade lives in `native_bind`;
# importing it here must stay LAST — its imports reach back into this package
# and into paleo_workbench.mapping while this __init__ is still executing.
from paleo_workbench.mapping.geological_pipeline.native_bind import (  # noqa: E402
    HAS_CPP,
)

__all__ = [
    "DEFAULT_GEOLOGICAL_PIPELINE",
    "FACTOR_DEFAULTS",
    "GeologicalFactor",
    "GeologicalFactorDataset",
    "GeologicalMappingPipeline",
    "HAS_CPP",
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
