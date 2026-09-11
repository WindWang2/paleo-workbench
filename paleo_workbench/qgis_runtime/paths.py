"""Filesystem discovery for the vendored-QGIS runtime (V10 M-A).

Single authority for "where is the vendor build / deps prefix / PySide6".
Every consumer (loader, proj_data, health, tests/conftest.py,
scripts/run_qgis_env.py) resolves through :func:`resolve_runtime_paths`.

Resolution order (first wins):

* vendor root — ``PALEO_QGIS_BUILD_DIR`` (if it is a directory), else the
  repo-relative ``native/qgis_render_bridge/build/qgis-vendor`` checkout
  default.
* deps prefix — ``PALEO_QGIS_DEPS_DIR``, else the conda-layout default that
  ``tests/conftest.py`` has documented since V8 (Windows only; the conda
  recipe is an explicit opt-in, so a machine default is only consulted when
  an operator asked for that recipe).
* PySide6 package dir — via ``importlib.util.find_spec`` WITHOUT importing
  PySide6 (importing it loads the wheel's Qt DLLs, which the conda recipe
  must not do before its own preload; V7 loader bisection).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Windows conda-unification default (mirrors tests/conftest.py:72-85; only
# consulted when PALEO_QGIS_CONDA_QT selects that recipe — see loader.py).
_WINDOWS_CONDA_DEPS_DEFAULT = r"C:\Users\wangj.KEVIN\paleo-qgis-deps"


def _env_dir(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def repo_root() -> Path:
    """The repository root that carries ``native/qgis_render_bridge``."""
    return Path(__file__).resolve().parents[2]


def vendor_root() -> Path | None:
    """Vendored-QGIS build root (contains ``output/`` and ``resources/``)."""
    override = _env_dir("PALEO_QGIS_BUILD_DIR")
    if override is not None:
        return override
    default = repo_root() / "native" / "qgis_render_bridge" / "build" / "qgis-vendor"
    return default if default.is_dir() else None


def deps_prefix() -> Path | None:
    """Conda deps prefix (Windows layout: ``<prefix>/Library/bin``)."""
    override = _env_dir("PALEO_QGIS_DEPS_DIR")
    if override is not None:
        return override
    if os.name == "nt":
        default = Path(_WINDOWS_CONDA_DEPS_DEFAULT)
        if default.is_dir():
            return default
    return None


def pyside_dir() -> Path | None:
    """PySide6 package dir without importing PySide6."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("PySide6")
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        return Path(locations[0]) if locations else None
    except (ImportError, AttributeError, ValueError):
        return None


@dataclass(frozen=True)
class QgisRuntimePaths:
    """Resolved runtime locations; ``None`` = honestly not present."""

    vendor_root: Path | None
    vendor_bin: Path | None
    vendor_srs_db: Path | None
    vendor_proj_data: Path | None
    deps_root: Path | None
    deps_bin: Path | None
    deps_proj_data: Path | None
    pyside_dir: Path | None

    @property
    def vendor_bin_exists(self) -> bool:
        return self.vendor_bin is not None and self.vendor_bin.is_dir()

    def proj_data_candidates(self) -> list[tuple[str, Path]]:
        """proj.db candidates in PROJ-search order (env → vendor → deps)."""
        candidates: list[tuple[str, Path]] = []
        for var in ("PROJ_DATA", "PROJ_LIB"):
            value = os.environ.get(var, "").strip()
            if value:
                candidates.append((f"env:{var}", Path(value)))
        if self.vendor_proj_data is not None:
            candidates.append(("vendor-relative", self.vendor_proj_data))
        if self.deps_proj_data is not None:
            candidates.append(("deps", self.deps_proj_data))
        return candidates


def resolve_runtime_paths() -> QgisRuntimePaths:
    """Discover every runtime location once, honestly (missing → None)."""

    def existing(path: Path | None) -> Path | None:
        return path if path is not None and path.is_dir() else None

    root = vendor_root()
    deps = deps_prefix()
    deps_library = deps / "Library" if deps is not None else None
    return QgisRuntimePaths(
        vendor_root=root,
        vendor_bin=existing(root / "output" / "bin") if root else None,
        vendor_srs_db=(
            root / "resources" / "srs.db"
            if root is not None and (root / "resources" / "srs.db").is_file()
            else None
        ),
        # What the vendored proj_9.dll finds RELATIVE TO ITSELF
        # (output/bin/../share/proj) — the ADR 0060-compliant data channel.
        vendor_proj_data=(root / "output" / "share" / "proj") if root else None,
        deps_root=deps,
        deps_bin=existing(deps_library / "bin") if deps_library else existing(deps / "bin") if deps else None,
        deps_proj_data=(
            (deps_library / "share" / "proj") if deps_library is not None and (deps_library / "share" / "proj").is_dir()
            else (deps / "share" / "proj") if deps is not None and (deps / "share" / "proj").is_dir()
            else None
        ),
        pyside_dir=existing(pyside_dir()),
    )
