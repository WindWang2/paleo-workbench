"""Production model package contract: validate + register (no training).

A package is a JSON/YAML-free plain dict or JSON file with:

- model_id, model_version, model_name, capability, provider
- artifact path + optional checksum
- input_schema / output_schema
- runtime, preprocessing_version, deterministic
- spatial_output_type
- scientific / demo_only flags

Registration uses the existing catalog Model/ModelVersion APIs.
Demo and heuristic providers cannot be registered as production packages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import Model, ModelVersion
from paleo_workbench.prediction.providers import (
    PROVIDER_DEMO,
    PROVIDER_LOCAL_ASSET,
)

# Providers that must never be packaged as scientific production.
NON_PROMOTABLE_PROVIDERS = frozenset({PROVIDER_DEMO, PROVIDER_LOCAL_ASSET})
NON_PROMOTABLE_MODEL_TYPES = frozenset({"demo", "heuristic"})

# Spatial output classes supported by the Stage-13 pipeline.
SPATIAL_VECTOR_POLYGONS = "VECTOR_POLYGONS"
SPATIAL_WELL_INTERVALS = "WELL_INTERVALS"
SPATIAL_CLASSIFIED_RASTER = "CLASSIFIED_RASTER"
SPATIAL_NONE = "NONE"

KNOWN_SPATIAL_TYPES = frozenset(
    {
        SPATIAL_VECTOR_POLYGONS,
        SPATIAL_WELL_INTERVALS,
        SPATIAL_CLASSIFIED_RASTER,
        SPATIAL_NONE,
        "",
    }
)


class ModelPackageError(ValueError):
    """Invalid model package manifest or registration request."""


@dataclass
class ModelPackageManifest:
    """Validated production (or test) model package metadata."""

    model_id: str
    model_version: str
    model_name: str
    capability: str
    provider: str
    artifact: str = ""
    checksum: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    preprocessing_version: str = ""
    runtime: str = "python_callable"
    deterministic: bool = True
    spatial_output_type: str = SPATIAL_VECTOR_POLYGONS
    model_type: str = "ml"
    demo_only: bool = False
    scientific: bool = True
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_name": self.model_name,
            "capability": self.capability,
            "provider": self.provider,
            "artifact": self.artifact,
            "checksum": self.checksum,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "preprocessing_version": self.preprocessing_version,
            "runtime": self.runtime,
            "deterministic": self.deterministic,
            "spatial_output_type": self.spatial_output_type,
            "model_type": self.model_type,
            "demo_only": self.demo_only,
            "scientific": self.scientific,
            "provenance": dict(self.provenance),
            "metadata": dict(self.metadata),
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest_dict(source: Path | str | dict[str, Any]) -> dict[str, Any]:
    """Load a package manifest from a dict or JSON path."""
    if isinstance(source, dict):
        return dict(source)
    path = Path(source)
    if not path.is_file():
        raise ModelPackageError(f"Manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelPackageError(f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelPackageError("Manifest root must be a JSON object")
    return data


def _strict_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    """Parse a manifest boolean field strictly (H4-1).

    Python truthiness would turn ``"false"``/``"0"``/``"no"`` into True and
    silently invert the author's declaration. Only real booleans (or the
    unambiguous strings ``"true"``/``"false"``) are accepted.
    """
    value = raw.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "false"}:
            return s == "true"
    raise ModelPackageError(f"{key} must be a boolean, got {value!r}")


def parse_model_package_manifest(
    source: Path | str | dict[str, Any],
    *,
    base_dir: Path | str | None = None,
) -> ModelPackageManifest:
    """Parse and validate a model package manifest (no catalog side effects)."""
    raw = load_manifest_dict(source)
    model_id = str(raw.get("model_id") or "").strip()
    model_version = str(raw.get("model_version") or raw.get("version") or "1").strip()
    model_name = str(raw.get("model_name") or raw.get("name") or model_id).strip()
    capability = str(raw.get("capability") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    if not model_id:
        raise ModelPackageError("model_id is required")
    if not model_name:
        raise ModelPackageError("model_name is required")
    if not capability:
        raise ModelPackageError("capability is required")
    if not provider:
        raise ModelPackageError("provider is required")

    model_type = str(raw.get("model_type") or "ml").strip() or "ml"
    demo_only = _strict_bool(raw, "demo_only", False)
    scientific = _strict_bool(raw, "scientific", not demo_only)
    deterministic = _strict_bool(raw, "deterministic", True)
    spatial = str(raw.get("spatial_output_type") or SPATIAL_VECTOR_POLYGONS).strip()
    if spatial not in KNOWN_SPATIAL_TYPES:
        raise ModelPackageError(f"Unknown spatial_output_type: {spatial!r}")

    artifact = str(raw.get("artifact") or raw.get("artifact_uri") or "").strip()
    if artifact and base_dir is not None:
        art_path = Path(artifact)
        if not art_path.is_absolute():
            artifact = str((Path(base_dir) / art_path).resolve())

    checksum = raw.get("checksum")
    if checksum is not None:
        checksum = str(checksum).strip() or None

    input_schema = raw.get("input_schema") or {}
    output_schema = raw.get("output_schema") or {}
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ModelPackageError("input_schema and output_schema must be objects")
    metadata_raw = raw.get("metadata") or {}
    provenance_raw = raw.get("provenance") or {}
    if not isinstance(metadata_raw, dict) or not isinstance(provenance_raw, dict):
        raise ModelPackageError("metadata and provenance must be objects")

    # Enrich output_schema with spatial type when absent.
    if spatial and "spatial_output_type" not in output_schema:
        output_schema = {**output_schema, "spatial_output_type": spatial}

    return ModelPackageManifest(
        model_id=model_id,
        model_version=model_version,
        model_name=model_name,
        capability=capability,
        provider=provider,
        artifact=artifact,
        checksum=checksum,
        input_schema=dict(input_schema),
        output_schema=dict(output_schema),
        preprocessing_version=str(raw.get("preprocessing_version") or ""),
        runtime=str(raw.get("runtime") or "python_callable"),
        deterministic=deterministic,
        spatial_output_type=spatial or SPATIAL_NONE,
        model_type=model_type,
        demo_only=demo_only,
        scientific=scientific,
        provenance=dict(provenance_raw),
        metadata=dict(metadata_raw),
    )


def validate_model_package(
    manifest: ModelPackageManifest,
    *,
    require_artifact: bool = True,
    allow_non_scientific: bool = False,
) -> list[str]:
    """Return validation error messages (empty list means OK)."""
    errors: list[str] = []
    if manifest.provider in NON_PROMOTABLE_PROVIDERS and not allow_non_scientific:
        errors.append(
            f"provider {manifest.provider!r} cannot be registered as a production package"
        )
    if manifest.model_type in NON_PROMOTABLE_MODEL_TYPES and not allow_non_scientific:
        errors.append(
            f"model_type {manifest.model_type!r} cannot be a production package"
        )
    if manifest.demo_only and not allow_non_scientific:
        errors.append("demo_only packages cannot be registered as production")
    if manifest.scientific is False and not allow_non_scientific:
        # The author explicitly declared this package non-scientific; a later
        # promote must not be able to flip the label (H4-3b).
        errors.append("scientific=false packages cannot be registered as production")
    if require_artifact:
        if not manifest.artifact:
            errors.append("artifact path is required for production packages")
        else:
            path = Path(manifest.artifact)
            if not path.is_file():
                errors.append(f"artifact file missing: {path}")
            else:
                digest = _sha256_file(path)
                if manifest.checksum and manifest.checksum != digest:
                    errors.append(
                        f"checksum mismatch: manifest={manifest.checksum} file={digest}"
                    )
                elif not manifest.checksum:
                    # Fill for registration when valid.
                    manifest.checksum = digest
    if not manifest.input_schema and not allow_non_scientific:
        # Soft: production packages should declare inputs; warn as error for gate.
        errors.append("input_schema is required for production packages")
    return errors


def register_model_package(
    service,
    source: Path | str | dict[str, Any],
    *,
    base_dir: Path | str | None = None,
    status: str = "demo",
    require_artifact: bool = True,
    allow_non_scientific: bool = False,
) -> tuple[Model, ModelVersion]:
    """Validate a package and register Model + ModelVersion in the catalog.

    Default ``status="demo"`` so packages are not production until explicit
    :meth:`promote_model` (with safety gates). Pass ``status="production"``
    only for carefully validated packages (e.g. test fixtures that also pass
    promote gates).
    """
    if isinstance(source, (str, Path)) and base_dir is None:
        base_dir = Path(source).resolve().parent
    manifest = parse_model_package_manifest(source, base_dir=base_dir)
    errors = validate_model_package(
        manifest,
        require_artifact=require_artifact,
        allow_non_scientific=allow_non_scientific,
    )
    if errors:
        raise ModelPackageError("; ".join(errors))

    meta = {
        **manifest.metadata,
        "scientific": manifest.scientific,
        "spatial_output_type": manifest.spatial_output_type,
        "package": True,
    }
    model = service.register_model(
        model_id=manifest.model_id,
        model_name=manifest.model_name,
        model_type=manifest.model_type,
        capability=manifest.capability,
        provider=manifest.provider,
        status=status if status != "production" else "demo",
        metadata=meta,
        provenance=manifest.provenance,
        force_status=False,
    )
    # Re-register path for versions: get or create, with identity checks (H4-2).
    # Registering the same (model_id, model_version) with a DIFFERENT artifact
    # or schema must raise instead of silently returning the old version.
    try:
        existing_version = service.get_model_version(
            manifest.model_id, manifest.model_version
        )
    except Exception:
        existing_version = None
    if existing_version is not None:
        conflicts: list[str] = []
        if manifest.checksum and existing_version.checksum and manifest.checksum != existing_version.checksum:
            conflicts.append(f"checksum {existing_version.checksum} != {manifest.checksum}")
        if (
            manifest.input_schema
            and existing_version.input_schema
            and manifest.input_schema != existing_version.input_schema
        ):
            conflicts.append("input_schema differs")
        if (
            manifest.output_schema
            and existing_version.output_schema
            and manifest.output_schema != existing_version.output_schema
        ):
            conflicts.append("output_schema differs")
        if (
            manifest.preprocessing_version
            and existing_version.preprocessing_version
            and manifest.preprocessing_version != existing_version.preprocessing_version
        ):
            conflicts.append("preprocessing_version differs")
        if existing_version.deterministic != manifest.deterministic:
            conflicts.append("deterministic differs")
        if existing_version.demo_only != manifest.demo_only:
            conflicts.append("demo_only differs")
        if conflicts:
            raise ModelPackageError(
                f"identity conflict for {manifest.model_id}@{manifest.model_version}: "
                + "; ".join(conflicts)
            )
        version = existing_version
    else:
        version = service.register_model_version(
            manifest.model_id,
            model_version=manifest.model_version,
            artifact_uri=manifest.artifact,
            checksum=manifest.checksum,
            input_schema=manifest.input_schema,
            output_schema=manifest.output_schema,
            preprocessing_version=manifest.preprocessing_version,
            runtime=manifest.runtime,
            deterministic=manifest.deterministic,
            demo_only=manifest.demo_only,
            status="demo" if status == "production" else status,
            metadata=meta,
            provenance=manifest.provenance,
        )
    if status == "production":
        # Explicit promote with safety (will reject demo/heuristic).
        version = service.promote_model(manifest.model_id, manifest.model_version)
        model = service.get_model(manifest.model_id)
    return model, version


def can_promote_to_production(
    service, model_id: str, model_version: str, *, require_input_schema: bool = True
) -> tuple[bool, str]:
    """Return (ok, reason) for promote gates (shared with catalog.promote_model).

    ``require_input_schema`` is a PROMOTE-time requirement: a version promoted
    before the schema contract existed must not silently disappear from
    find_production_model on upgrade (Agent L P2) — reads keep the other
    gates but tolerate the legacy empty-schema case.
    """
    try:
        model = service.get_model(model_id)
        version = service.get_model_version(model_id, model_version)
    except Exception as exc:  # CatalogError
        return False, str(exc)
    if version.demo_only:
        return False, "demo_only model versions cannot be promoted to production"
    # Case/alias-insensitive checks: "Demo"/"DEMO"/"local-asset" must not
    # slip past exact-match allowlists (H4-3c).
    provider_norm = (model.provider or "").strip().casefold()
    if provider_norm in {p.strip().casefold() for p in NON_PROMOTABLE_PROVIDERS}:
        return False, f"provider {model.provider!r} is not promotable to production"
    type_norm = (model.model_type or "").strip().casefold()
    if type_norm in {t.strip().casefold() for t in NON_PROMOTABLE_MODEL_TYPES}:
        return False, f"model_type {model.model_type!r} is not promotable to production"
    if model.metadata.get("scientific") is False:
        return False, "model metadata marks scientific=False"
    if version.metadata.get("scientific") is False:
        return False, "version metadata marks scientific=False (H4-3b)"
    if require_input_schema and not version.input_schema:
        return False, "input_schema is required for production promotion (H5-b)"
    return True, "ok"
