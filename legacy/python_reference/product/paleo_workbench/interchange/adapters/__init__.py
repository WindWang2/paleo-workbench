"""Built-in interchange adapters and the default registry assembly."""

from __future__ import annotations

from paleo_workbench.interchange.adapters.geojson_adapter import GeoJSONAdapter
from paleo_workbench.interchange.adapters.las_adapter import LasAdapter
from paleo_workbench.interchange.adapters.model_adapter import AbaqusAdapter, Flac3dAdapter
from paleo_workbench.interchange.adapters.raster_adapter import RasterAdapter
from paleo_workbench.interchange.adapters.segy_adapter import SegyAdapter
from paleo_workbench.interchange.adapters.tabular_adapter import (
    CsvAdapter,
    ExcelAdapter,
    TsvAdapter,
)
from paleo_workbench.interchange.adapters.unavailable import (
    DlisAdapter,
    MeshExchangeAdapter,
    VtkModelAdapter,
)
from paleo_workbench.interchange.adapters.vector_adapter import VectorAdapter
from paleo_workbench.interchange.registry import InterchangeRegistry


def build_default_registry() -> InterchangeRegistry:
    """Register every built-in adapter; order matters for extension lookup
    (more specific adapters first)."""
    registry = InterchangeRegistry()
    registry.register(LasAdapter())
    registry.register(CsvAdapter())
    registry.register(TsvAdapter())
    registry.register(ExcelAdapter())
    registry.register(GeoJSONAdapter())
    registry.register(VectorAdapter())
    registry.register(RasterAdapter())
    registry.register(SegyAdapter())
    registry.register(Flac3dAdapter())
    registry.register(AbaqusAdapter())
    registry.register(DlisAdapter())
    registry.register(VtkModelAdapter())
    registry.register(MeshExchangeAdapter())
    return registry


__all__ = [
    "build_default_registry",
    "LasAdapter",
    "CsvAdapter",
    "TsvAdapter",
    "ExcelAdapter",
    "GeoJSONAdapter",
    "VectorAdapter",
    "RasterAdapter",
    "SegyAdapter",
    "Flac3dAdapter",
    "AbaqusAdapter",
    "DlisAdapter",
    "VtkModelAdapter",
    "MeshExchangeAdapter",
]
