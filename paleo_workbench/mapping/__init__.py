"""Mapping editor adapters: geometry schema and PaleoMapDocument I/O."""

from typing import TYPE_CHECKING

from paleo_workbench.mapping.document_io import (
    apply_features_to_document,
    features_from_document,
)
from paleo_workbench.mapping.geometry_schema import (
    FeatureKind,
    new_feature_id,
    normalize_facies,
    normalize_label,
    normalize_line,
    normalize_well,
)
if TYPE_CHECKING:
    from paleo_workbench.mapping.reference_layers import (
        ReferenceLayerError,
        ReferenceLayerService,
    )

__all__ = [
    "FeatureKind",
    "apply_features_to_document",
    "features_from_document",
    "new_feature_id",
    "normalize_facies",
    "normalize_label",
    "normalize_line",
    "normalize_well",
    "ReferenceLayerError",
    "ReferenceLayerService",
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
