"""Capability provider contracts (P2-B).

A *capability provider* is the sanctioned extension unit of the workbench
(ADR 0055 track P.REG): a small object exposing a frozen
:class:`ProviderDescriptor` (structured metadata, never introspected Python
signatures) and an ``execute`` method over typed inputs/outputs whose data
outputs enter the catalog through :class:`paleo_workbench.catalog.port.CatalogPort`.

Design rules:

- **Descriptors are data**: provider_id/family/version, JSON-schema
  parameters, typed input/output names, resource profile, threading model.
  Stable, testable, JSON-serializable.
- **Typed inputs**: providers receive :class:`TypedRef` instances
  (``DataVersionRef``, ``WellRef``, ``SeismicVolumeRef``, …) — never random
  dicts to be guessed apart. Untyped payloads are rejected by the executor.
- **Outputs are results**: :class:`ProviderResult` with artifacts, warnings,
  diagnostics, provenance and metrics — one small object, not a god-class.
- **Families stay separate**: no mega ``BasePlugin``. The family only fixes
  vocabulary; behaviour contracts live with the deep seams each family wraps
  (CatalogPort, Interpolator, KERNELS, ModelProvider, MapRenderBackend…).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from paleo_workbench.providers.errors import InvalidProviderError

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")


class ProviderFamily(str, Enum):
    """Families with real production consumers today.

    ``DATA_FORMAT`` / ``PREVIEW`` / ``MAP_COMPONENT`` exist in the vocabulary
    because the seams are known (FormatSpec/PreviewRegistry/composer), but no
    built-in providers ship for them yet — the registry accepts them so
    third parties can register without a schema change.
    """

    INTERPOLATION = "interpolation"
    SEISMIC_ATTRIBUTE = "seismic_attribute"
    INFERENCE = "inference"
    VISUALIZATION = "visualization"
    EXPORTER = "exporter"
    IMPORTER = "importer"
    DATA_FORMAT = "data_format"
    PREVIEW = "preview"
    MAP_COMPONENT = "map_component"


#: Typed reference vocabulary. Keys are the names usable in
#: ``input_types``/``output_types``; values document what concrete type the
#: executor resolves them to. ``DataVersionRef`` is the catalog's own DTO —
#: the artifact authority — so every data output can be traced.
TYPED_REFS: dict[str, str] = {
    "DataVersionRef": "paleo_workbench.catalog.types.DataVersionRef (catalog version identity)",
    "WellRef": "paleo_workbench.providers.refs.WellRef (project well identity)",
    "SeismicVolumeRef": "paleo_workbench.providers.refs.SeismicVolumeRef (volume path/store identity)",
    "MapDocumentRef": "paleo_workbench.providers.refs.MapDocumentRef (map document identity)",
    "FactorDatasetRef": "paleo_workbench.providers.refs.FactorDatasetRef (factor dataset handle)",
    "FactorGridRef": "paleo_workbench.providers.refs.FactorGridRef (interpolated grid handle)",
    "PathRef": "paleo_workbench.providers.refs.PathRef (workspace-relative file handle)",
    # In-process domain objects providers may receive directly (typed, never
    # anonymous dicts):
    "GeologicalFactorDataset": "paleo_workbench.mapping.geological_pipeline.models.GeologicalFactorDataset",
    "MapDocument": "paleo_workbench.mapping.layers.MapDocument",
}


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    """Declared resource cost of one provider execution (estimates, not
    pre-allocation) — consumed by the ResourceGovernor for admission."""

    estimated_cpu_cores: float = 1.0
    estimated_ram_bytes: int = 0
    estimated_vram_bytes: int = 0
    io_weight: float = 1.0
    category: str = "background.compute"  # TaskCategory value for admission

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_cpu_cores": self.estimated_cpu_cores,
            "estimated_ram_bytes": self.estimated_ram_bytes,
            "estimated_vram_bytes": self.estimated_vram_bytes,
            "io_weight": self.io_weight,
            "category": self.category,
        }


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Structured, stable metadata for one provider (never guessed)."""

    provider_id: str
    family: ProviderFamily
    version: str
    display_name: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    input_types: tuple[str, ...] = ()
    output_types: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    resource_profile: ResourceProfile = field(default_factory=ResourceProfile)
    supports_cancel: bool = False
    supports_resume: bool = False
    deterministic: bool = True
    threading_model: str = "worker_thread"  # worker_thread | gui_thread | any

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "family": self.family.value,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "input_types": list(self.input_types),
            "output_types": list(self.output_types),
            "parameters_schema": self.parameters_schema,
            "resource_profile": self.resource_profile.to_dict(),
            "supports_cancel": self.supports_cancel,
            "supports_resume": self.supports_resume,
            "deterministic": self.deterministic,
            "threading_model": self.threading_model,
        }


def validate_descriptor(descriptor: ProviderDescriptor) -> list[str]:
    """Structural validation; returns a list of problems (empty = valid)."""
    problems: list[str] = []
    if not _ID_RE.match(descriptor.provider_id or ""):
        problems.append(f"provider_id {descriptor.provider_id!r} must match {_ID_RE.pattern}")
    if not _VERSION_RE.match(descriptor.version or ""):
        problems.append(f"version {descriptor.version!r} must be numeric dotted (e.g. 1.0.0)")
    if not isinstance(descriptor.family, ProviderFamily):
        problems.append(f"family {descriptor.family!r} is not a ProviderFamily")
    if not (descriptor.display_name or "").strip():
        problems.append("display_name must be a non-empty string")
    schema = descriptor.parameters_schema
    if not isinstance(schema, dict):
        problems.append("parameters_schema must be a dict (JSON schema)")
    else:
        if schema.get("type") not in (None, "object"):
            problems.append("parameters_schema must describe an object at the top level")
        props = schema.get("properties")
        if props is not None and not isinstance(props, dict):
            problems.append("parameters_schema.properties must be a dict")
        required = schema.get("required")
        if required is not None and not isinstance(required, list):
            problems.append("parameters_schema.required must be a list")
    for role, types in (("input_types", descriptor.input_types), ("output_types", descriptor.output_types)):
        for t in types:
            if t not in TYPED_REFS:
                problems.append(f"{role} entry {t!r} is not a known typed ref {sorted(TYPED_REFS)}")
    if descriptor.threading_model not in ("worker_thread", "gui_thread", "any"):
        problems.append(f"threading_model {descriptor.threading_model!r} invalid")
    profile = descriptor.resource_profile
    if not isinstance(profile, ResourceProfile):
        problems.append("resource_profile must be a ResourceProfile")
    else:
        if profile.estimated_cpu_cores <= 0:
            problems.append("resource_profile.estimated_cpu_cores must be > 0")
        if profile.io_weight < 0:
            problems.append("resource_profile.io_weight must be >= 0")
    return problems


def assert_valid_descriptor(descriptor: ProviderDescriptor) -> None:
    problems = validate_descriptor(descriptor)
    if problems:
        raise InvalidProviderError(descriptor.provider_id, problems)
