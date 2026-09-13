"""The one bridge loader (V10 M-A): both Windows recipes + Linux quirks.

Recipes (V8 D6 lineage, unchanged semantics — now resolved in ONE place):

* **default (self-contained vendor)** — ``vendor/output/bin`` carries every
  third-party runtime the QGIS DLLs need; the process Qt is PySide6's own
  wheel copy (single-Qt rule). Loader: MSVCP pre-pin + ``[vendor_bin,
  pyside_dir]``.
* **``PALEO_QGIS_CONDA_QT=1`` (conda-Qt unification)** — minimal neutral
  vendor + conda deps prefix; the conda Qt set is preloaded by absolute path
  BEFORE PySide6 is first imported (ADR 0059 private-ABI rule), so callers
  on this recipe must run :func:`prepare_bridge_load` at boot, before any
  ``import PySide6.*`` (``paleo_workbench/main.py`` does).

Idempotent; never raises; returns a :class:`LoadReport` so health/UI can
show *why* a load would fail instead of a bare ImportError later.
"""

from __future__ import annotations

import ctypes
import glob
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from paleo_workbench.qgis_runtime.paths import (
    QgisRuntimePaths,
    resolve_runtime_paths,
)

_TRUTHY = {"1", "true", "yes", "on"}

# conftest.py V8 conda recipe preload list (single source, mirrored here):
# core Qt set first (PySide6 + QGIS then share this one Qt — never the
# wheel-bundled copy), then QGIS satellite deps, then the geo C libs
# (bisected order: native extensions otherwise pin incompatible
# sqlite3/zlib/expat process-wide and qgis_core fails with
# ERROR_MOD_NOT_FOUND).
_CONDA_PRELOAD_NAMES = (
    "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Multimedia", "qca-qt6", "qt6keychain",
    "Qt6Core5Compat", "libprotobuf-lite", "Qt6Network", "Qt6Sql", "Qt6Concurrent",
    "Qt6Xml", "Qt6Svg", "Qt6PrintSupport", "spatialindex-64", "exiv2", "zip",
    "sqlite3", "zlib", "libexpat", "gdal", "geos_c", "proj_9", "spatialite", "zstd",
)


class LoadRecipe(str, Enum):
    VENDOR = "vendor"
    CONDA_QT = "conda_qt"


@dataclass(frozen=True)
class LoadReport:
    recipe: LoadRecipe
    prepared: bool
    paths: QgisRuntimePaths
    dll_dirs: tuple[str, ...] = ()
    preload_failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    @property
    def vendor_missing(self) -> bool:
        return self.paths.vendor_bin is None


def resolve_recipe() -> LoadRecipe:
    if os.environ.get("PALEO_QGIS_CONDA_QT", "").strip().lower() in _TRUTHY:
        return LoadRecipe.CONDA_QT
    return LoadRecipe.VENDOR


_PREPARED = False


def _msvcp_pre_pin(warnings: list[str]) -> None:
    """Pre-pin the SYSTEM MSVCP before numpy can squat a trimmed copy.

    V7 loader investigation: numpy wheels ship a trimmed msvcp140 (OpenBLAS
    subset); imported first it squats the process-wide MSVCP slot and the
    VS2022-built QGIS DLLs fail with WinError 127.
    """
    if os.name != "nt":
        return
    try:
        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        for crt in (
            "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
            "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll",
        ):
            candidate = system32 / crt
            if candidate.is_file():
                try:
                    ctypes.WinDLL(str(candidate))
                except OSError:
                    continue
    except Exception:  # pragma: no cover - defensive, pre-pin is best-effort
        warnings.append("msvcp pre-pin failed (continuing)")


def _ensure_linux_protobuf_compat(paths: QgisRuntimePaths, warnings: list[str]) -> None:
    """Vendored qgis_core needs ``libprotobuf-lite.so.36.0.0``; distros ship
    a newer SONAME — drop a compat symlink on qgis_core's RUNPATH dirs."""
    if os.name == "nt" or paths.vendor_root is None:
        return
    needed = "libprotobuf-lite.so.36.0.0"
    source: Path | None = None
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
        paths.vendor_root / "output" / "lib",
        paths.vendor_root / "src" / "core",
        paths.vendor_root / "src" / "gui",
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        dest = directory / needed
        if dest.exists() or dest.is_symlink():
            continue
        try:
            dest.symlink_to(source)
        except OSError:
            continue


def _conda_preload(deps_bin: Path, warnings: list[str]) -> list[str]:
    # ctypes.WinDLL is Windows-only. Conda recipe docs are Windows-only too,
    # but prepare_bridge_load must never raise (#1265).
    if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
        warnings.append(
            "conda DLL preload skipped "
            "(ctypes.WinDLL is Windows-only)"
        )
        return []
    failures: list[str] = []
    for name in _CONDA_PRELOAD_NAMES:
        hits = glob.glob(str(deps_bin / f"{name}.dll"))
        if not hits:
            continue
        try:
            ctypes.WinDLL(hits[0])
        except OSError as exc:
            failures.append(f"{name}: {exc}")
    return failures


def prepare_bridge_load(*, force: bool = False) -> LoadReport:
    """Put the vendored QGIS runtime on the loader path (idempotent).

    Call before the first ``import qgis_render_bridge``; on the conda recipe
    also before the first ``import PySide6.*`` (boot hook in main.py).
    """
    global _PREPARED
    paths = resolve_runtime_paths()
    recipe = resolve_recipe()
    warnings: list[str] = []
    if _PREPARED and not force:
        return LoadReport(
            recipe=recipe, prepared=True, paths=paths,
            warnings=("already prepared",)
        )

    _ensure_linux_protobuf_compat(paths, warnings)
    if recipe is LoadRecipe.VENDOR:
        # MSVCP pre-pin is a VENDOR-recipe mechanism (numpy's trimmed msvcp140
        # squats the slot before the VS2022-built vendor DLLs load). In the
        # conda recipe the System32 pin actively BREAKS the load: conda's own
        # CRT build must win its slots — V10 loader bisection (the legacy
        # conftest conda branch never pre-pinned).
        _msvcp_pre_pin(warnings)

    if paths.vendor_bin is None:
        warnings.append(
            "vendored-QGIS build not found: set PALEO_QGIS_BUILD_DIR to a "
            "completed vendor build (native/qgis_render_bridge/build/qgis-vendor)"
        )

    candidates: list[Path] = []
    preload_failures: list[str] = []
    if recipe is LoadRecipe.CONDA_QT:
        if paths.vendor_bin is not None:
            candidates.append(paths.vendor_bin)
        if paths.deps_bin is not None:
            candidates.append(paths.deps_bin)
        else:
            warnings.append(
                "conda recipe selected but PALEO_QGIS_DEPS_DIR is absent — "
                "the bridge will not resolve its Qt/geo dependencies"
            )
    else:
        if paths.vendor_bin is not None:
            candidates.append(paths.vendor_bin)
        if paths.pyside_dir is not None:
            candidates.append(paths.pyside_dir)

    valid: list[str] = []
    # Windows DLL search (PEP 739 / 3.8+). POSIX has no add_dll_directory —
    # the dynamic loader / LD_LIBRARY_PATH owns shared objects. Never raise:
    # this function is called from ``import paleo_workbench`` (#1265).
    register_dll = os.name == "nt" and hasattr(os, "add_dll_directory")
    if candidates and not register_dll:
        warnings.append(
            "POSIX: DLL search-path registration skipped "
            "(os.add_dll_directory is Windows-only); shared libraries resolve "
            "via the dynamic loader / LD_LIBRARY_PATH"
        )
    for directory in candidates:
        if register_dll:
            try:
                os.add_dll_directory(str(directory))
            except OSError:
                warnings.append(f"add_dll_directory failed: {directory}")
                continue
        valid.append(str(directory))
    # Single PATH prepend in candidate order (loader resolves in PATH order;
    # per-directory prepends would reverse priority — V7 bisection).
    if valid:
        os.environ["PATH"] = (
            os.pathsep.join(valid) + os.pathsep + os.environ.get("PATH", "")
        )
    # Conda preload AFTER the directories/PATH are registered — the preloaded
    # DLLs resolve their own dependencies through those paths; preloading
    # earlier lets a wrong sqlite3/zlib (venv, System32, …) squat the process
    # and the bridge later fails with ENTRYPOINT_NOT_FOUND (V10 loader
    # bisection; the legacy conftest recipe had this order all along).
    if recipe is LoadRecipe.CONDA_QT and paths.deps_bin is not None:
        preload_failures = _conda_preload(paths.deps_bin, warnings)
    _PREPARED = True
    return LoadReport(
        recipe=recipe,
        prepared=True,
        paths=paths,
        dll_dirs=tuple(valid),
        preload_failures=tuple(preload_failures),
        warnings=tuple(warnings),
    )
