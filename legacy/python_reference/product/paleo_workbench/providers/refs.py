"""Typed references exchanged with capability providers (P2-B).

Providers never receive bare paths or anonymous dicts. Every input is a
typed reference the executor resolved from the harness context (or the
caller constructed explicitly); every data output the catalog can own is a
``DataVersionRef`` from :mod:`paleo_workbench.catalog.types` — re-used, not
re-invented, so provenance stays on the existing authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WellRef:
    """Identity of one well in the open project."""

    well_id: str
    name: str = ""
    path: str | None = None  # LAS/XML backing file when known

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "well", "well_id": self.well_id, "name": self.name, "path": self.path}


@dataclass(frozen=True, slots=True)
class SeismicVolumeRef:
    """Identity of one seismic volume (zarr store or RAW SEG-Y path)."""

    volume_id: str
    path: str
    kind: str = "zarr"  # zarr | segy
    version_id: str | None = None  # catalog version when registered

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "seismic_volume",
            "volume_id": self.volume_id,
            "path": self.path,
            "store_kind": self.kind,
            "version_id": self.version_id,
        }


@dataclass(frozen=True, slots=True)
class MapDocumentRef:
    """Identity of one map document (project-owned)."""

    document_id: str
    title: str = ""
    run_id: str | None = None  # producing DataRun when known

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "map_document",
            "document_id": self.document_id,
            "title": self.title,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class FactorDatasetRef:
    """Handle to a geological factor dataset (extracted well factors)."""

    factor_name: str
    target_horizon: str = ""
    unit: str = ""
    well_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "factor_dataset",
            "factor_name": self.factor_name,
            "target_horizon": self.target_horizon,
            "unit": self.unit,
            "well_ids": list(self.well_ids),
        }


@dataclass(frozen=True, slots=True)
class FactorGridRef:
    """Handle to an interpolated factor grid (in-memory or artifact-backed)."""

    grid_key: str
    artifact_path: str | None = None
    version_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "factor_grid",
            "grid_key": self.grid_key,
            "artifact_path": self.artifact_path,
            "version_id": self.version_id,
        }


@dataclass(frozen=True, slots=True)
class PathRef:
    """A workspace file handle. Providers must not open paths that did not
    arrive through a ref — this is the SDK's filesystem boundary."""

    path: str
    label: str = ""
    mime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "path", "path": self.path, "label": self.label, "mime": self.mime}


@dataclass(slots=True)
class ArtifactRef:
    """One output artifact of a provider run.

    ``version`` is set when the artifact entered the catalog (the normal
    path for data outputs); ``value`` may carry an in-memory result object
    (grid array, MapDocument, …) for the immediate caller.
    """

    name: str
    kind: str  # e.g. "derived_store" | "grid" | "map_document" | "file"
    version: Any | None = None  # DataVersionRef when catalog-owned
    value: Any | None = None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        version = None
        if self.version is not None:
            to_dict = getattr(self.version, "to_dict", None)
            version = to_dict() if callable(to_dict) else str(self.version)
        return {
            "name": self.name,
            "kind": self.kind,
            "version": version,
            "path": self.path,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ProviderResult:
    """Uniform outcome of one provider execution."""

    artifacts: list[ArtifactRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [a.to_dict() for a in self.artifacts],
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
            "provenance": dict(self.provenance),
            "metrics": dict(self.metrics),
        }
