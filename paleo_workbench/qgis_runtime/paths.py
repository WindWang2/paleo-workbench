"""Filesystem discovery for the vendored-QGIS runtime (V10 M-A).

Single authority for "where is the vendor build / deps prefix / PySide6".
Every consumer (loader, proj_data, health, tests/conftest.py,
scripts/run_qgis_env.py) resolves through :func:`resolve_runtime_paths`.

Resolution order (first wins):

* vendor root — ``PALEO_QGIS_BUILD_DIR`` (if it is a directory), else the
  repo-relative ``native/qgis_render_bridge/build/qgis-vendor`` checkout
  default.
* deps prefix — ``PALEO_QGIS_DEPS_DIR``, else the repo-relative
  ``native/qgis_render_bridge/build/qgis-deps`` default (the same
  "build next to the bridge" convention as the vendor root). V10 review
  follow-up（#1263）：这里**不再**硬编码开发者本机绝对路径——旧实现
  ``C:\\Users\\<developer>\\paleo-qgis-deps`` 只在作者机器上成立，换机/
  换账号时静默返回 ``None``，真实病因（deps 前缀缺失）被掩盖成
  "qgis_render_bridge 不可导入"。
* PySide6 package dir — via ``importlib.util.find_spec`` WITHOUT importing
  PySide6 (importing it loads the wheel's Qt DLLs, which the conda recipe
  must not do before its own preload; V7 loader bisection).

``deps_prefix()`` 在两条通道都落空时返回 ``None`` 并记一条可操作的警告
（"设 PALEO_QGIS_DEPS_DIR 或走默认 build 目录"），不再静默。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: 仓库内 deps 前缀约定（与 vendor_root 的 build/ 同级；仅 Windows 的
#: conda-统一配方会用到，见 loader.py）。
_DEPS_BUILD_SUBDIR = ("native", "qgis_render_bridge", "build", "qgis-deps")


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
    """Conda deps prefix (Windows layout: ``<prefix>/Library/bin``).

    V10 review follow-up（#1263）：两条通道都是**可移植**的——显式
    ``PALEO_QGIS_DEPS_DIR``，或仓库内 ``build/qgis-deps`` 约定。都落空时
    返回 ``None`` 并给出可操作警告（不静默失败、不含任何本机绝对路径）。
    """
    override = _env_dir("PALEO_QGIS_DEPS_DIR")
    if override is not None:
        return override
    if os.name == "nt":
        default = repo_root().joinpath(*_DEPS_BUILD_SUBDIR)
        if default.is_dir():
            return default
        logger.warning(
            "未找到 QGIS deps 前缀：PALEO_QGIS_DEPS_DIR 未设置（或指向非目录），"
            "且默认位置 %s 不存在——conda-统一配方将无法解析依赖。"
            "请设置 PALEO_QGIS_DEPS_DIR，或把 deps 前缀放到该默认路径。",
            default,
        )
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
