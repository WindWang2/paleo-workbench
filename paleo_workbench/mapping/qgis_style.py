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
    env_dir = os.environ.get("PALEO_QGIS_BUILD_DIR", "").strip()
    if env_dir:
        root = Path(env_dir)
        if root.is_dir():
            return root
    repo_root = Path(__file__).resolve().parents[2]
    root = repo_root / "native" / "qgis_render_bridge" / "build" / "qgis-vendor"
    return root if root.is_dir() else None


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

    Windows V7: the bridge ``.pyd`` imports ``qgis_core.dll`` from the vendor
    build's ``output/bin``; MSVC has no rpath, so the directory must join the
    DLL search path **before** the first ``import qgis_render_bridge``.

    Linux: drop a protobuf SONAME compatibility symlink onto qgis_core's
    RUNPATH so a distro ``libprotobuf-lite.so.36.1.0`` satisfies the
    vendored QGIS ``NEEDED libprotobuf-lite.so.36.0.0``.

    Idempotent. Dev-layout driven (editable install is the only supported
    mode): repo ``native/qgis_render_bridge/build/qgis-vendor`` or
    ``PALEO_QGIS_BUILD_DIR`` override.
    """
    global _DLL_DIRS_INJECTED
    if _DLL_DIRS_INJECTED:
        return
    _DLL_DIRS_INJECTED = True
    _ensure_linux_qgis_protobuf_compat()
    if os.name != "nt":
        return
    # MSVCP pre-pin (V7 loader investigation): numpy wheels ship a TRIMMED
    # msvcp140 (only the OpenBLAS-needed symbol subset). If numpy imports
    # first, its copy squats the process-wide MSVCP slot and the VS2022-built
    # QGIS DLLs fail with WinError 127 (missing symbols). Pre-pinning the
    # newest SYSTEM MSVCP makes numpy reuse it (superset-compatible) and
    # leaves the full symbol set for QGIS. Harmless when numpy is absent.
    try:
        import ctypes

        _system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        for _crt in (
            "msvcp140.dll",
            "msvcp140_1.dll",
            "msvcp140_2.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "concrt140.dll",
        ):
            _candidate = _system32 / _crt
            if _candidate.is_file():
                try:
                    ctypes.WinDLL(str(_candidate))
                except OSError:
                    continue
    except Exception:
        pass
    candidates: list[str] = []
    env_dir = os.environ.get("PALEO_QGIS_BUILD_DIR", "").strip()
    if env_dir:
        candidates.append(str(Path(env_dir) / "output" / "bin"))
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(
        str(repo_root / "native" / "qgis_render_bridge" / "build" / "qgis-vendor" / "output" / "bin")
    )
    # Qt runtime: the process Qt MUST be PySide6's own bundled Qt (single-Qt
    # rule — a second Qt 6.8.0 tree in C:/deps would load a mixed Qt and break
    # both the bridge and PySide6.QtWidgets). The vendored QGIS DLLs were
    # built against Qt 6.8.0 headers and run on PySide6's Qt 6.8.x via Qt's
    # minor-version forward binary compatibility. Do NOT add C:/deps Qt here.
    #
    # Locate the PySide6 dir WITHOUT importing the package: executing
    # PySide6/__init__ loads shiboken/pyside extensions, whose dependency
    # resolution is order-sensitive to the third-party dll dirs below (V7
    # loader bisection: import-PySide6-then-add-dirs breaks the bridge load,
    # add-dirs-without-importing works). find_spec only reads metadata.
    try:
        import importlib.util

        spec = importlib.util.find_spec("PySide6")
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        if locations:
            candidates.append(str(locations[0]))
    except (ImportError, AttributeError, ValueError):
        pass
    # Third-party runtimes consumed by the QGIS DLLs. NOTE: the vendor
    # output/bin is SELF-CONTAINED (every third-party DLL the QGIS build
    # consumed was deployed there, including the OpenSSL 3.0 pair that is
    # forward-compatible with the interpreter's libcrypto). The C:/deps
    # source trees are deliberately NOT on the runtime path: AddDllDirectory
    # resolves later-added dirs first, so source trees would shadow the
    # vendor-pinned versions (V7 loader bisection: vcpkg's OpenSSL 3.6.3
    # shadows the compatible 3.0 pair and breaks the load with WinError 127;
    # anaconda's tree ships shadowing Qt/CRT builds too). Build-time tools
    # (setup.py) keep using C:/deps; this is runtime only.
    #
    # Qt runtime: the process Qt MUST be PySide6's own bundled Qt (single-Qt
    # rule — a second Qt 6.8.0 tree in C:/deps would load a mixed Qt and break
    # both the bridge and PySide6.QtWidgets). The vendored QGIS DLLs were
    # built against Qt 6.8.0 headers and run on PySide6's Qt 6.8.x via Qt's
    # minor-version forward binary compatibility. Do NOT add C:/deps Qt here.
    candidates.extend(
        [
            # NOTE: no C:/deps source trees (see comment above) — vendor bin
            # is self-contained.
        ]
    )
    for directory in candidates:
        if directory and Path(directory).is_dir():
            try:
                os.add_dll_directory(directory)
            except OSError:
                continue
    # Single PATH prepend in candidate order (vendor bin FIRST): the loader
    # resolves in PATH order and per-directory prepends above would reverse
    # the priority (V7 loader bisection: vendor-first works, reversed fails).
    # Prepend also beats shadowing trees already on the system PATH (anaconda
    # ships conflicting Qt/CRT builds). Safe: the vendor output/bin carries
    # no CRT/API-set forwarders (removed at deploy time).
    valid = [d for d in candidates if d and Path(d).is_dir()]
    if valid:
        os.environ["PATH"] = os.pathsep.join(valid) + os.pathsep + os.environ.get("PATH", "")


def qgis_bridge_available() -> bool:
    """True when the optional native bridge module is importable."""
    ensure_qgis_bridge_dll_dirs()
    try:
        import qgis_render_bridge  # noqa: F401
    except ImportError:
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
