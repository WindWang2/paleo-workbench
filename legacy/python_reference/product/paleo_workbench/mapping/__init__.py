"""Mapping Engine 2.0: Core GIS layers, renderers, styling, and geological mapping pipeline."""

from typing import TYPE_CHECKING

from paleo_workbench.mapping.color_ramps import (
    ColorRamp,
    ColorStop,
    get_color_ramp,
    list_color_ramps,
    register_color_ramp,
)
from paleo_workbench.mapping.document_io import (
    apply_features_to_document,
    features_from_document,
)
from paleo_workbench.mapping.geological_pipeline import (
    DEFAULT_GEOLOGICAL_PIPELINE,
    FACTOR_DEFAULTS,
    GeologicalFactor,
    GeologicalFactorDataset,
    GeologicalMappingPipeline,
    IDWInterpolator,
    InterpolationOptions,
    Interpolator,
    KrigingInterpolator,
    calculate_nice_contour_levels,
    create_geological_factor_map_template,
    generate_contour_layer,
    generate_facies_polygon_layer,
    interpolate_factor,
)
from paleo_workbench.mapping.geometry_schema import (
    FeatureKind,
    new_feature_id,
    normalize_facies,
    normalize_label,
    normalize_line,
    normalize_well,
)
from paleo_workbench.mapping.layers import (
    ContourMapLayer,
    GridMapLayer,
    LayerType,
    MapDocument,
    MapLayer,
    PolygonMapLayer,
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderBackend,
    MapRenderSnapshot,
    QgisMapRenderBackend,
    RenderFrame,
    create_map_render_backend,
    qgis_backend_probe,
    shutdown_live_fallback_backends,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    STYLE_LIBRARY,
    TextStyle,
    VectorStyle,
    default_style_for,
    load_style_library,
    save_style_library,
    style_dict_revision,
)
from paleo_workbench.mapping.renderers import (
    DEFAULT_RENDERER_REGISTRY,
    CategorizedRenderer,
    ContourRenderer,
    GridRenderer,
    LayerRenderer,
    LegendItem,
    RenderContext,
    RendererRegistry,
    SingleSymbolRenderer,
    WellSymbolRenderer,
)

if TYPE_CHECKING:
    from paleo_workbench.mapping.reference_layers import (
        ReferenceLayerError,
        ReferenceLayerService,
    )

__all__ = [
    "CategorizedRenderer",
    "ColorRamp",
    "ColorStop",
    "ContourMapLayer",
    "ContourRenderer",
    "DEFAULT_GEOLOGICAL_PIPELINE",
    "DEFAULT_RENDERER_REGISTRY",
    "FACTOR_DEFAULTS",
    "FallbackMapRenderBackend",
    "FeatureKind",
    "GeologicalFactor",
    "GeologicalFactorDataset",
    "GeologicalMappingPipeline",
    "GridMapLayer",
    "GridRenderer",
    "IDWInterpolator",
    "InterpolationOptions",
    "Interpolator",
    "KrigingInterpolator",
    "LayerRenderer",
    "LayerType",
    "LegendItem",
    "LinePattern",
    "MapDocument",
    "MapLayer",
    "MapLayerSnapshot",
    "MapRenderBackend",
    "MapRenderSnapshot",
    "MarkerSymbol",
    "PolygonMapLayer",
    "QgisMapRenderBackend",
    "RasterMapLayer",
    "ReferenceLayerError",
    "ReferenceLayerService",
    "RenderContext",
    "RenderFrame",
    "RendererRegistry",
    "STYLE_LIBRARY",
    "SingleSymbolRenderer",
    "TextStyle",
    "VectorMapLayer",
    "VectorStyle",
    "WellPointMapLayer",
    "WellSymbolRenderer",
    "apply_features_to_document",
    "calculate_nice_contour_levels",
    "create_geological_factor_map_template",
    "create_map_render_backend",
    "default_style_for",
    "features_from_document",
    "generate_contour_layer",
    "generate_facies_polygon_layer",
    "get_color_ramp",
    "interpolate_factor",
    "list_color_ramps",
    "load_style_library",
    "new_feature_id",
    "normalize_facies",
    "normalize_label",
    "normalize_line",
    "normalize_well",
    "qgis_backend_probe",
    "register_color_ramp",
    "save_style_library",
    "shutdown_live_fallback_backends",
    "style_dict_revision",
]


def __getattr__(name: str):
    """Delay the GDAL-backed reference-layer adapter until a caller needs it."""
    if name in {"ReferenceLayerError", "ReferenceLayerService"}:
        from paleo_workbench.mapping.reference_layers import (
            ReferenceLayerError,
            ReferenceLayerService,
        )

        return {
            "ReferenceLayerError": ReferenceLayerError,
            "ReferenceLayerService": ReferenceLayerService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
