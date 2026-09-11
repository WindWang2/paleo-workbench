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

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = [
    "QGIS_STYLE_SCHEMA_VERSION",
    "QgisStylePayload",
    "ensure_qgis_bridge_dll_dirs",
    "migrate_legacy_style",
    "payload_from_legacy_style",
    "qgis_bridge_available",
]

QGIS_STYLE_SCHEMA_VERSION = 1

_DLL_DIRS_INJECTED = False


def _vendor_qgis_root() -> Path | None:
    # V10: discovery moved to paleo_workbench.qgis_runtime.paths (single
    # authority); kept as a thin alias for in-module callers.
    from paleo_workbench.qgis_runtime.paths import vendor_root

    return vendor_root()


def _ensure_linux_qgis_protobuf_compat() -> None:
    """Vendored libqgis_core NEEDED ``libprotobuf-lite.so.36.0.0``.

    Distro packages often ship 36.1.0 with a new SONAME. qgis_core's RUNPATH
    is the in-tree ``src/core`` / ``src/gui`` dirs (not ``output/lib``), so a
    compat symlink must live on those RUNPATHs or the native stack — including
    ``QgsVectorLayerProperties`` — fails to load.
    """
    if os.name == "nt":
        return
    root = _vendor_qgis_root()
    if root is None:
        return
    needed_name = "libprotobuf-lite.so.36.0.0"
    source = None
    for candidate in (
        Path("/usr/lib/libprotobuf-lite.so.36.0.0"),
        Path("/usr/lib/libprotobuf-lite.so.36.1.0"),
        Path("/usr/lib64/libprotobuf-lite.so.36.0.0"),
        Path("/usr/lib64/libprotobuf-lite.so.36.1.0"),
        Path("/usr/lib/libprotobuf-lite.so"),
        Path("/usr/lib64/libprotobuf-lite.so"),
    ):
        if candidate.is_file():
            source = candidate.resolve()
            break
    if source is None:
        return
    for directory in (
        root / "output" / "lib",
        root / "src" / "core",
        root / "src" / "gui",
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        dest = directory / needed_name
        if dest.exists() or dest.is_symlink():
            continue
        try:
            dest.symlink_to(source)
        except OSError:
            continue


def ensure_qgis_bridge_dll_dirs() -> None:
    """Put vendored-QGIS runtime libraries on the loader path.

    V10 M-A: the loader itself (both Windows recipes, MSVCP pre-pin, Linux
    protobuf symlink, conda preload set) now lives in
    :mod:`paleo_workbench.qgis_runtime.loader` — the single authority. This
    shim keeps the historical import surface for every existing call site
    and stays idempotent; see the loader module for the recipe contract.
    """
    from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

    prepare_bridge_load()


def qgis_bridge_available() -> bool:
    """True when the optional native bridge module is importable."""
    ensure_qgis_bridge_dll_dirs()
    try:
        import qgis_render_bridge  # noqa: F401
    except Exception:
        return False
    return True


def qgis_scalar_pipeline_ready() -> tuple[bool, str]:
    """Bridge AND the GDAL Python binding the scalar-raster mirror needs.

    Audit #925: ``qgis_bridge_available`` alone reported "ready" on installs
    where every scalar-grid composition then failed at runtime with a bare
    RuntimeError because ``osgeo.gdal`` was missing. Capability probes must
    cover what the feature actually imports.
    """
    if not qgis_bridge_available():
        return False, "qgis_render_bridge 未构建（可选组件）"
    try:
        from osgeo import gdal  # noqa: F401
    except ImportError:
        return (
            False,
            "QGIS 标量栅格管线需要 GDAL Python 绑定（osgeo）；"
            "当前环境未安装，栅格图层无法经 QGIS 渲染",
        )
    return True, ""


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
