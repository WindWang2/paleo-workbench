"""Capability Provider SDK (P2-B, ADR 0055 track P.REG).

Public surface:

- contracts: :class:`ProviderDescriptor`, :class:`ProviderFamily`,
  :class:`ResourceProfile`, :func:`validate_descriptor`
- refs: typed inputs/outputs (:class:`WellRef`, :class:`SeismicVolumeRef`,
  :class:`MapDocumentRef`, …) and :class:`ProviderResult`
- registry: :class:`ProviderRegistry` + :func:`get_provider_registry`
  (built-ins auto-registered) + opt-in entry-point discovery
- execution: :func:`execute_provider` (validate → admit → execute →
  provenance) and :func:`validate_parameters`

Minimal provider example::

    from paleo_workbench.providers import (
        ProviderDescriptor, ProviderFamily, ResourceProfile, ProviderResult
    )
    from paleo_workbench.providers.registry import get_provider_registry

    class MyKriging:
        @property
        def descriptor(self):
            return ProviderDescriptor(
                provider_id="interpolation.mykriging",
                family=ProviderFamily.INTERPOLATION,
                version="1.0.0",
                display_name="My Kriging",
                input_types=("FactorDatasetRef",),
                output_types=("FactorGridRef",),
                parameters_schema={"type": "object", "properties": {"grid_n": {"type": "integer"}}},
                resource_profile=ResourceProfile(estimated_cpu_cores=2.0),
            )

        def execute(self, inputs, parameters, context):
            ...  # real computation over typed refs
            return ProviderResult()

    get_provider_registry().register(MyKriging())
"""
from __future__ import annotations

from paleo_workbench.providers.base import CapabilityProvider, ProviderContext
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
    TYPED_REFS,
    assert_valid_descriptor,
    validate_descriptor,
)
from paleo_workbench.providers.errors import (
    DuplicateProviderError,
    InvalidParametersError,
    InvalidProviderError,
    ProviderError,
    ProviderExecutionError,
    ProviderRejectedInputError,
    UnknownProviderError,
)
from paleo_workbench.providers.execution import execute_provider, validate_parameters
from paleo_workbench.providers.refs import (
    ArtifactRef,
    FactorDatasetRef,
    FactorGridRef,
    MapDocumentRef,
    PathRef,
    ProviderResult,
    SeismicVolumeRef,
    WellRef,
)
from paleo_workbench.providers.registry import (
    ProviderRegistry,
    ensure_builtin_providers,
    get_provider_registry,
    set_provider_registry,
)

__all__ = [
    "ArtifactRef",
    "CapabilityProvider",
    "DuplicateProviderError",
    "FactorDatasetRef",
    "FactorGridRef",
    "InvalidParametersError",
    "InvalidProviderError",
    "MapDocumentRef",
    "PathRef",
    "ProviderContext",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderExecutionError",
    "ProviderFamily",
    "ProviderRegistry",
    "ProviderRejectedInputError",
    "ProviderResult",
    "ResourceProfile",
    "SeismicVolumeRef",
    "TYPED_REFS",
    "UnknownProviderError",
    "WellRef",
    "assert_valid_descriptor",
    "ensure_builtin_providers",
    "execute_provider",
    "get_provider_registry",
    "set_provider_registry",
    "validate_descriptor",
    "validate_parameters",
]
