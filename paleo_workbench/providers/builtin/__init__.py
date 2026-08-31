"""Built-in capability providers (P2-B).

Factories are individually guarded by :func:`ensure_builtin_providers` so a
missing optional engine (onnxruntime, QGIS bridge) never blocks the rest.
Every factory returns a provider wrapping an existing production seam —
no built-in exists merely to fill a family slot. A factory may return a
single provider or a list (probe-driven families register several).
"""
from __future__ import annotations

from collections.abc import Callable

from paleo_workbench.providers.base import CapabilityProvider

ProviderFactory = Callable[[], "CapabilityProvider | list[CapabilityProvider]"]


def _kriging() -> CapabilityProvider:
    from paleo_workbench.providers.builtin.interpolation import KrigingProvider

    return KrigingProvider()


def _idw() -> CapabilityProvider:
    from paleo_workbench.providers.builtin.interpolation import IDWProvider

    return IDWProvider()


def _attribute_kernels() -> list[CapabilityProvider]:
    from paleo_workbench.providers.builtin.seismic_attribute import (
        make_attribute_providers,
    )

    return make_attribute_providers()


def _tiled_onnx() -> CapabilityProvider:
    from paleo_workbench.providers.builtin.inference import TiledOnnxCapabilityProvider

    return TiledOnnxCapabilityProvider()


def _map_export() -> CapabilityProvider:
    from paleo_workbench.providers.builtin.map_export import MapProductExportProvider

    return MapProductExportProvider()


def _visualization_backends() -> list[CapabilityProvider]:
    from paleo_workbench.providers.builtin.map_export import (
        make_visualization_providers,
    )

    return make_visualization_providers()


BUILTIN_PROVIDER_FACTORIES: tuple[ProviderFactory, ...] = (
    _kriging,
    _idw,
    _attribute_kernels,
    _tiled_onnx,
    _map_export,
    _visualization_backends,
)

__all__ = ["BUILTIN_PROVIDER_FACTORIES", "ProviderFactory"]
