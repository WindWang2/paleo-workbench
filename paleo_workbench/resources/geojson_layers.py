"""GeoJSON vector metadata and three-layer facies-result grouping."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import ResourceItem

FACIES_LAYER_SPECS: dict[str, tuple[str, int]] = {
    "facies": ("相", 1),
    "subfacies": ("亚相", 2),
    "microfacies": ("微相", 3),
}

_ROLE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("microfacies", ("microfacies", "micro_facies", "micro-facies", "微相")),
    ("subfacies", ("subfacies", "sub_facies", "sub-facies", "亚相")),
    ("facies", ("facies", "相图", "相")),
)
_EXPLICIT_ROLE_KEYS = ("layer_role", "facies_level", "hierarchy_level", "level")
_EXPLICIT_PRODUCT_KEYS = ("product_id", "result_id", "facies_product_id")


def normalize_facies_layer_role(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    for role, aliases in _ROLE_ALIASES:
        if text == role or text in aliases:
            return role
    return None


def facies_layer_role_from_name(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    for role, aliases in _ROLE_ALIASES:
        if any(alias in stem for alias in aliases):
            return role
    return None


def facies_layer_summary_from_name(filename: str) -> dict[str, Any]:
    """Return hierarchy metadata inferred from a conventional layer filename."""
    role = facies_layer_role_from_name(filename)
    if role is None:
        return {}
    label, level = FACIES_LAYER_SPECS[role]
    return {
        "geojson_layer_role": role,
        "geojson_layer_label": label,
        "geojson_layer_level": level,
    }


def geojson_document_summary(payload: object, filename: str) -> dict[str, Any]:
    """Return bounded, UI-friendly metadata for one parsed GeoJSON document."""
    if not isinstance(payload, dict):
        return {"geojson_valid": False, "geojson_error": "根节点不是对象"}
    features = payload.get("features")
    valid = payload.get("type") == "FeatureCollection" and isinstance(features, list)
    summary: dict[str, Any] = {"geojson_valid": bool(valid)}
    if not valid:
        summary["geojson_error"] = "根节点必须是 FeatureCollection"
        return summary

    geometry_types = sorted(
        {
            str(geometry.get("type"))
            for feature in features
            if isinstance(feature, dict)
            for geometry in [feature.get("geometry")]
            if isinstance(geometry, dict) and geometry.get("type")
        }
    )
    summary["geometry_types"] = geometry_types

    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit_role = None
    for key in _EXPLICIT_ROLE_KEYS:
        explicit_role = normalize_facies_layer_role(
            metadata.get(key) or payload.get(key)
        )
        if explicit_role is not None:
            break
    role = explicit_role or facies_layer_role_from_name(filename)
    if role:
        label, level = FACIES_LAYER_SPECS[role]
        summary.update(
            {
                "geojson_layer_role": role,
                "geojson_layer_label": label,
                "geojson_layer_level": level,
            }
        )

    product_source_id = next(
        (
            str(metadata.get(key) or payload.get(key)).strip()
            for key in _EXPLICIT_PRODUCT_KEYS
            if str(metadata.get(key) or payload.get(key) or "").strip()
        ),
        "",
    )
    if product_source_id:
        summary["facies_product_source_id"] = product_source_id
    return summary


def _group_stem(filename: str, role: str) -> str:
    stem = Path(filename).stem.lower()
    aliases = next(aliases for name, aliases in _ROLE_ALIASES if name == role)
    for alias in aliases:
        stem = stem.replace(alias, "")
    stem = re.sub(r"(?:图层|layer|map|result|成果|图)$", "", stem)
    stem = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", stem).strip("-")
    return stem or "facies-product"


def _group_key(resource: ResourceItem) -> str | None:
    summary = _effective_layer_summary(resource)
    role = normalize_facies_layer_role(summary.get("geojson_layer_role"))
    if role is None:
        return None
    explicit = str(summary.get("facies_product_source_id") or "").strip()
    if explicit:
        return f"id:{explicit}"
    path = Path(str(resource.path or resource.name))
    return f"path:{path.parent.as_posix()}:{_group_stem(resource.name, role)}"


def _effective_layer_summary(resource: ResourceItem) -> dict[str, Any]:
    """Parsed summary with the filename-inferred role folded in (read-only).

    Same inference rule as ``annotate_facies_product_groups``: only unknown /
    legacy summaries fall back to the filename convention; an explicit parse
    failure is never promoted.
    """
    summary = dict(resource.parsed_summary or {})
    if (
        not normalize_facies_layer_role(summary.get("geojson_layer_role"))
        and summary.get("geojson_valid") is not False
    ):
        summary.update(facies_layer_summary_from_name(resource.name))
    return summary


def facies_layer_role(resource: ResourceItem) -> str | None:
    """Effective hierarchy role (facies / subfacies / microfacies) of a layer."""
    return normalize_facies_layer_role(
        _effective_layer_summary(resource).get("geojson_layer_role")
    )


def facies_group_members(
    resource: ResourceItem, resources: Iterable[ResourceItem]
) -> list[ResourceItem]:
    """The clicked 相图 layer plus its same-group siblings, ordered 相→亚相→微相.

    Grouping reuses the product-group identity: annotated
    ``facies_product_group_id`` when present, else the stable digest of the
    directory + role-stripped-stem key. Layers without a recognizable role
    never join a group (the clicked layer alone is returned).
    """
    def member_gid(res: ResourceItem) -> str | None:
        key = _group_key(res)
        if key is None:
            return None
        annotated = str(
            (res.parsed_summary or {}).get("facies_product_group_id") or ""
        ).strip()
        return annotated or _stable_group_id(key)

    target_gid = member_gid(resource)
    if target_gid is None:
        return [resource]
    members = [
        res
        for res in resources
        if res.type == "geojson"
        and str(res.format).lower() in {"geojson", "json"}
        and member_gid(res) == target_gid
    ]
    members.sort(
        key=lambda res: FACIES_LAYER_SPECS[facies_layer_role(res) or "facies"][1]
    )
    return members or [resource]


def _stable_group_id(group_key: str) -> str:
    digest = sha256(group_key.encode("utf-8")).hexdigest()[:16]
    return f"facies_product_{digest}"


def annotate_facies_product_groups(
    added: Iterable[ResourceItem],
    existing: Iterable[ResourceItem] = (),
) -> list[str]:
    """Annotate complete 相/亚相/微相 GeoJSON sibling groups in-place.

    Standalone layers remain ordinary inputs. A group becomes an output only
    when it contains exactly one resource for every required hierarchy role.
    """
    added_items = list(added)
    all_items = [*list(existing), *added_items]
    added_object_ids = {id(resource) for resource in added_items}
    groups: dict[str, list[ResourceItem]] = defaultdict(list)
    for resource in all_items:
        if resource.type != "geojson" or resource.format.lower() not in {
            "geojson",
            "json",
        }:
            continue
        summary = dict(resource.parsed_summary or {})
        # Old projects and deliberately bounded probes may not yet carry the
        # new hierarchy fields.  A current parse failure is never promoted,
        # while an unknown/legacy state can still use the established filename
        # convention so importing the third sibling completes the group.
        if (
            not summary.get("geojson_layer_role")
            and summary.get("geojson_valid") is not False
        ):
            summary.update(facies_layer_summary_from_name(resource.name))
            resource.parsed_summary = summary
        key = _group_key(resource)
        if key:
            groups[key].append(resource)

    warnings: list[str] = []
    required_roles = set(FACIES_LAYER_SPECS)
    for key, members in groups.items():
        by_role: dict[str, list[ResourceItem]] = defaultdict(list)
        for resource in members:
            role = normalize_facies_layer_role(
                (resource.parsed_summary or {}).get("geojson_layer_role")
            )
            if role:
                by_role[role].append(resource)
        complete = set(by_role) == required_roles and all(
            len(by_role[role]) == 1 for role in required_roles
        )
        group_id = _stable_group_id(key)
        for resource in members:
            summary = dict(resource.parsed_summary or {})
            summary.update(
                {
                    "facies_product_group_id": group_id,
                    "facies_product_complete": complete,
                    "facies_product_layer_count": len(by_role),
                }
            )
            resource.parsed_summary = summary
            if complete:
                role = str(summary.get("geojson_layer_role") or "")
                label = FACIES_LAYER_SPECS[role][0]
                resource.artifact_role = "output"
                other_tags = [
                    tag
                    for tag in (resource.tags or [])
                    if tag not in {"input", "reference", "output"}
                ]
                resource.tags = list(
                    dict.fromkeys(["output", "facies-map", label, *other_tags])
                )

        if not complete and len(members) >= 2 and any(
            id(member) in added_object_ids for member in members
        ):
            missing = [
                FACIES_LAYER_SPECS[role][0]
                for role in ("facies", "subfacies", "microfacies")
                if role not in by_role
            ]
            duplicates = [
                FACIES_LAYER_SPECS[role][0]
                for role in required_roles
                if len(by_role.get(role, [])) > 1
            ]
            detail = []
            if missing:
                detail.append("缺少" + "、".join(missing))
            if duplicates:
                detail.append("重复" + "、".join(sorted(duplicates)))
            warnings.append(
                f"GeoJSON 相图成果组不完整（{'；'.join(detail) or '层级无法识别'}）"
            )
    return warnings
