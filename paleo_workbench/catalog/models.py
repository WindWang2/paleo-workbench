"""Domain models for the Data Catalog / Data Lifecycle Core (ADR 0056).

This package is the canonical data architecture for asset lifecycle management:
DataAsset + immutable DataVersion + DataRun (provenance) + Tag. It is distinct
from ``paleo_workbench.resources.data_asset_registry.DataAssetRegistry`` (a
format/IO registry) and from ``VersionSet``/``VersionSnapshot`` (expert map
finalization semantics) — neither is replaced by these models.

Invariants enforced here and in ``service.DataCatalogService``:

- RAW managed versions are immutable once committed (ADR 0056).
- Any committed DataVersion is immutable; change produces a new version.
- Lifecycle stage is a first-class enum, never a plain tag.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
import unicodedata

from pydantic import BaseModel, Field

from paleo_workbench.project.models import _id, _now_iso

CATALOG_SCHEMA_VERSION = 1


class DataStage(str, Enum):
    """Formal data lifecycle stages. Never express these via tags."""

    RAW = "raw"
    DERIVED = "derived"
    INTERMEDIATE = "intermediate"
    OUTPUT = "output"


class ImmutableVersionError(RuntimeError):
    """Raised when an operation would mutate a committed DataVersion."""


class VersionMember(BaseModel):
    """One physical member file of a compound (multi-file) DataVersion.

    V11 compound-asset model (docs/development/data-fabric-v11/04): a version
    whose ``members`` list is non-empty is a bundle — ``DataVersion.path``
    then points at the member directory and each member is addressed by
    ``rel_path`` (POSIX, relative to that directory, never escaping it).
    A version's aggregate integrity credential is the re-hash of its sorted
    member checksums (see :func:`aggregate_member_sha256`).
    """

    name: str  # unique display key within the version
    rel_path: str
    member_role: str = ""  # data | index | attributes | projection | sidecar | part | manifest | ...
    ordinal: int = 0
    required: bool = True
    sha256: str | None = None
    size_bytes: int | None = None


def aggregate_member_sha256(members: list[VersionMember]) -> str | None:
    """Version-level integrity credential over ordered member checksums.

    ``sha256( "name:sha256" lines of the ordinally sorted members )`` —
    recomputable from the member table alone, stable under member insertion
    order changes, and sensitive to any member path/content change. Returns
    None when no member carries a checksum (nothing to aggregate honestly).
    """
    import hashlib

    lines: list[str] = []
    for member in sorted(members, key=lambda m: (m.ordinal, m.name)):
        if not member.sha256:
            return None
        lines.append(f"{member.name}:{member.sha256}")
    if not lines:
        return None
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


class RunPort(BaseModel):
    """One typed lineage endpoint binding on a DataRun.

    V11 typed lineage (docs/development/data-fabric-v11/06): ports annotate
    WHICH ROLE each consumed/produced version played (sonic log, time-depth
    curve, normalized output, …). The flat ``input_version_ids`` /
    ``output_version_ids`` lists stay authoritative and always remain a
    superset of the port version ids — old runs without ports are valid and
    read back with anonymous ``input``/``output`` roles.
    """

    role: str
    version_id: str
    ordinal: int = 0
    required: bool = True
    entity_type: str = ""
    entity_id: str = ""
    note: str = ""


class CatalogError(RuntimeError):
    """Base error for catalog operations (missing asset/version, conflicts)."""


class DataAsset(BaseModel):
    """A logical data asset: stable identity plus current-version pointer."""

    id: str = Field(default_factory=lambda: _id("asset"))
    name: str
    type: str = "unknown"
    description: str = ""
    current_version_id: str | None = None
    # Set when this asset is a migration projection of a legacy ResourceItem;
    # the asset id then reuses the legacy resource id so existing references
    # (FactorMap/Prediction/WellTable/JointAnalysis/ExportArtifact) keep working.
    legacy_resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    # Tombstone (soft delete): trashed assets are hidden from active listings
    # but fully recoverable (payload moved to ``trash/``, lineage retained).
    # Optional-with-default so pre-trash catalog.json documents still load
    # (CATALOG_SCHEMA_VERSION stays 1).
    trashed: bool = False
    trashed_at: str | None = None


class DataVersion(BaseModel):
    """An immutable, committed version of a DataAsset.

    ``path`` is a project-relative POSIX path for managed versions and an
    absolute path for external (unmanaged) versions. ``sha256`` is the source
    of truth for integrity; a missing value means "not yet verifiable".
    """

    id: str = Field(default_factory=lambda: _id("ver"))
    asset_id: str
    version_number: int
    stage: DataStage
    managed: bool = True
    path: str = ""
    source_uri: str | None = None
    format: str = ""
    size_bytes: int | None = None
    sha256: str | None = None
    parent_version_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    # Compound payload (V11): empty list = traditional single-file version.
    # When non-empty, ``path`` is the member directory and members address
    # files by ``rel_path`` relative to it.
    members: list[VersionMember] = Field(default_factory=list)
    # Tombstone (soft delete): see ``DataAsset.trashed``. ``metadata["trash"]``
    # records ``{reason, original_stage, original_path, trashed_at}``.
    trashed: bool = False
    trashed_at: str | None = None


class DataRun(BaseModel):
    """A processing run: the provenance record linking input/output versions.

    ``model_ref`` (optional) records which registered model produced this run:
    ``{"model_id", "model_version", "model_version_id"}``. It is additive so
    pre-registry catalog documents (and runs without a model) still load.
    """

    id: str = Field(default_factory=lambda: _id("run"))
    operation: str
    input_version_ids: list[str] = Field(default_factory=list)
    output_version_ids: list[str] = Field(default_factory=list)
    # Typed lineage ports (V11): role-annotated bindings over the flat id
    # lists above. Invariant (enforced by the single write-in
    # ``DataCatalogService.set_run_ports``): every port version id is a
    # member of the corresponding flat list. Runs predating V11 simply carry
    # empty port lists and are read as anonymous inputs/outputs.
    input_ports: list[RunPort] = Field(default_factory=list)
    output_ports: list[RunPort] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    generator: str = ""
    status: str = "completed"
    model_ref: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_now_iso)


class Model(BaseModel):
    """A logical computation model registered in the catalog (no ML-framework
    binding). ``model_id`` is the stable logical id (e.g. ``demo-facies-v1``);
    ``capability`` describes what the model does (e.g. ``facies_prediction``);
    ``provider`` names the backend implementing it (demo / local_asset / a
    future native or ONNX provider); ``status`` is one of ``demo`` /
    ``production`` / ``archived`` — only ``production`` models are found by
    :meth:`DataCatalogService.find_production_model`.
    """

    id: str = Field(default_factory=lambda: _id("model"))
    model_id: str
    model_name: str
    model_type: str = "unknown"  # heuristic | demo | ml | ...
    capability: str = ""
    provider: str = ""
    status: str = "demo"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ModelVersion(BaseModel):
    """A concrete, registered version of a :class:`Model`.

    ``artifact_uri`` is the model artifact location (may be empty for
    demo/heuristic providers with no artifact file). ``checksum`` hashes the
    artifact when one exists. ``demo_only`` marks a version that must never be
    presented as production output; ``status`` mirrors the ``Model`` lifecycle
    vocabulary. All fields except ``id``/``model_id`` are optional-with-default
    so old catalog documents load (CATALOG_SCHEMA_VERSION stays 1).
    """

    id: str = Field(default_factory=lambda: _id("mver"))
    model_id: str
    model_version: str = "1"
    artifact_uri: str = ""
    checksum: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    preprocessing_version: str = ""
    runtime: str = ""
    deterministic: bool = True
    demo_only: bool = False
    status: str = "production"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    provenance: dict[str, Any] = Field(default_factory=dict)


class Tag(BaseModel):
    """A normalized, queryable tag. ``name`` is unique after normalization."""

    id: str = Field(default_factory=lambda: _id("tag"))
    name: str
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_tag_name(name: str) -> str:
    """Normalize a tag name so one visual tag is one tag.

    Collapses whitespace, applies Unicode NFKC, then casefolds.

    ``casefold()`` alone handles case but not Unicode equivalence, so strings
    that render identically produced *distinct* tags — defeating the very
    uniqueness this function exists to provide (#884). NFKC folds both the
    canonical and the compatibility differences that users actually paste:

    * NFD vs NFC accents — ``cafe`` + U+0301 combining acute versus U+00E9 —
      which macOS (APFS/HFS+) and some input methods produce;
    * fullwidth versus ASCII Latin (U+FF43 ``ｃ`` versus ``c``), routinely
      emitted by CJK IMEs and visually near-identical in a proportional font.

    Without folding, the duplicates split ``asset_tags`` associations and tag
    counts, and a tag search matched only the spelling the user happened to type.

    NFKC (not NFC) is deliberate for this CJK-facing product so width variants
    unify too; the trade-off is that it also folds some intentional typographic
    distinctions (e.g. ``①`` -> ``1``), which is the right call for tag keys.
    Note this is the key derivation shared by the canonical ``catalog.json`` and
    the rebuildable SQLite index, so both agree by construction.
    """
    collapsed = " ".join(str(name).split())
    return unicodedata.normalize("NFKC", collapsed).casefold()


class CatalogDocument(BaseModel):
    """Root of the portable canonical store (``metadata/catalog.json``).

    This is the single source of truth for catalog data; the SQLite database
    is a rebuildable index over it, keyed by ``catalog_revision``.
    """

    schema_version: int = CATALOG_SCHEMA_VERSION
    catalog_revision: int = 0
    assets: list[DataAsset] = Field(default_factory=list)
    versions: list[DataVersion] = Field(default_factory=list)
    runs: list[DataRun] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    # Model registry (P2): additive lists — old documents load without them.
    models: list[Model] = Field(default_factory=list)
    model_versions: list[ModelVersion] = Field(default_factory=list)
    # Association maps: asset_id -> [tag_id], version_id -> [tag_id].
    asset_tags: dict[str, list[str]] = Field(default_factory=dict)
    version_tags: dict[str, list[str]] = Field(default_factory=dict)
