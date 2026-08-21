"""Authoritative QGIS style payloads for map authoring layers.

The professional cartographic style of a vector layer is a serialized QGIS
renderer (``QgsFeatureRenderer`` XML owning the full ``QgsSymbol`` /
``QgsSymbolLayer`` tree) plus an optional serialized QGIS labeling
configuration.  The payload is stored inside the map document next to the
legacy flat ``VectorStyle`` dict, which remains for compatibility, fallback
rendering and old projects.

Payload contract (schema_version 1)::

    {
        "schema_version": 1,
        "renderer_xml": "<renderer ...>...</renderer>",
        "labeling_xml": "",            # optional PAL configuration
        "name": "Facies",              # optional style metadata
        "tags": ["lithology"],         # optional style metadata
        "revision": 3,                 # bumped on every edit
    }

This module is Qt-free and QGIS-free: it validates and versions payloads but
never interprets renderer XML (that is the native bridge's job).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "QGIS_STYLE_SCHEMA_VERSION",
    "QgisStylePayload",
    "migrate_legacy_style",
    "payload_from_legacy_style",
    "qgis_bridge_available",
]

QGIS_STYLE_SCHEMA_VERSION = 1


def qgis_bridge_available() -> bool:
    """True when the optional native bridge module is importable."""
    try:
        import qgis_render_bridge  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class QgisStylePayload:
    """One persisted QGIS authoring style with revision tracking."""

    renderer_xml: str
    labeling_xml: str = ""
    name: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    revision: int = 1
    schema_version: int = QGIS_STYLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.renderer_xml, str) or not self.renderer_xml.strip():
            raise ValueError("renderer_xml payload is required")
        if self.schema_version != QGIS_STYLE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported qgis_style schema version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "renderer_xml": self.renderer_xml,
            "labeling_xml": self.labeling_xml,
            "name": self.name,
            "tags": list(self.tags),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> QgisStylePayload | None:
        """Parse a persisted payload tolerantly; None when absent/invalid."""
        if not isinstance(data, Mapping):
            return None
        renderer_xml = data.get("renderer_xml")
        if not isinstance(renderer_xml, str) or not renderer_xml.strip():
            return None
        tags_raw = data.get("tags") or ()
        tags = tuple(str(tag) for tag in tags_raw if str(tag))
        try:
            revision = max(1, int(data.get("revision") or 1))
        except (TypeError, ValueError):
            revision = 1
        return cls(
            renderer_xml=renderer_xml,
            labeling_xml=str(data.get("labeling_xml") or ""),
            name=str(data.get("name") or ""),
            tags=tags,
            revision=revision,
            schema_version=int(data.get("schema_version") or QGIS_STYLE_SCHEMA_VERSION),
        )

    def bumped(self) -> QgisStylePayload:
        """Return the payload with its revision incremented."""
        return replace(self, revision=self.revision + 1)


def payload_from_legacy_style(
    style: Mapping[str, Any] | None, geometry_type: str
) -> QgisStylePayload | None:
    """Migrate one legacy VectorStyle dict into a QGIS payload.

    Requires the native bridge (the migration builds real QGIS objects).
    Returns None when the bridge is unavailable or the style cannot produce a
    renderer — callers keep the legacy representation in that case.
    """
    if not qgis_bridge_available():
        return None
    import qgis_render_bridge as native

    xml = native.legacy_style_to_renderer_xml(dict(style or {}), geometry_type)
    if not xml:
        return None
    return QgisStylePayload(renderer_xml=str(xml))


def migrate_legacy_style(
    style: Mapping[str, Any] | None, geometry_type: str
) -> QgisStylePayload | None:
    """legacy_to_qgis_renderer(): VectorStyle dict → authoritative payload.

    Preserves the legacy renderer vocabulary (single/categorized/graduated/
    rule presets, categories, ranges) inside real QGIS objects.  The legacy
    dict itself is never modified; old projects keep opening unchanged.
    """
    return payload_from_legacy_style(style, geometry_type)
