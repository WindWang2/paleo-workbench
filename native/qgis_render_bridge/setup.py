"""Optional pybind build for the vendored QGIS Core render bridge.

The extension is intentionally opt-in. Set ``PALEO_WITH_QGIS_RENDERER=1`` to
build the fixed in-tree QGIS source; no installed QGIS prefix is used.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup


HERE = Path(__file__).resolve().parent
QGIS_SOURCE = HERE.parents[1] / "third_party" / "qgis"


def _enabled() -> bool:
    return os.environ.get("PALEO_WITH_QGIS_RENDERER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _qt_include_dirs() -> list[str]:
    try:
        output = subprocess.check_output(
            ["pkg-config", "--cflags-only-I", "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Xml", "Qt6Svg"], text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Qt6Core, Qt6Gui, Qt6Widgets, Qt6Xml, and Qt6Svg pkg-config metadata is required for QGIS"
        ) from exc
    return [arg[2:] for arg in shlex.split(output) if arg.startswith("-I")]


def _vendor_build_dir() -> Path:
    configured = os.environ.get("PALEO_QGIS_BUILD_DIR", "").strip()
    return Path(configured) if configured else HERE / "build" / "qgis-vendor"


def _vendor_artifacts_present(build_dir: Path) -> bool:
    """True when a previously completed vendor build can be linked as-is."""
    return (
        _vendor_core_library(build_dir).is_file()
        and _vendor_gui_library(build_dir).is_file()
        and _vendor_analysis_library(build_dir).is_file()
        and (build_dir / "resources" / "srs.db").is_file()
    )


def _reuse_vendor_requested(build_dir: Path) -> bool:
    """Honour PALEO_QGIS_REUSE_VENDOR=1: link an existing vendor build.

    Multi-worktree development points PALEO_QGIS_BUILD_DIR at a sibling
    worktree's completed vendor build (same vendored-QGIS commit). Re-running
    cmake configure there would fail on the source-dir mismatch and rebuilding
    QGIS per worktree is exactly what the build-budget rules forbid, so an
    explicit opt-out of the configure step is required.
    """
    flag = os.environ.get("PALEO_QGIS_REUSE_VENDOR", "").strip().lower()
    return flag in {"1", "true", "yes", "on"} and _vendor_artifacts_present(build_dir)


def _vendor_core_library(build_dir: Path) -> Path:
    library_dir = build_dir / "output" / "lib"
    if sys.platform == "win32":
        return library_dir / "qgis_core.lib"
    if sys.platform == "darwin":
        return library_dir / "libqgis_core.dylib"
    return library_dir / "libqgis_core.so"


def _vendor_gui_library(build_dir: Path) -> Path:
    library_dir = build_dir / "output" / "lib"
    if sys.platform == "win32":
        return library_dir / "qgis_gui.lib"
    if sys.platform == "darwin":
        return library_dir / "libqgis_gui.dylib"
    return library_dir / "libqgis_gui.so"


def _vendor_analysis_library(build_dir: Path) -> Path:
    library_dir = build_dir / "output" / "lib"
    if sys.platform == "win32":
        return library_dir / "qgis_analysis.lib"
    if sys.platform == "darwin":
        return library_dir / "libqgis_analysis.dylib"
    return library_dir / "libqgis_analysis.so"


def _qgis_core_include_dirs(build_dir: Path) -> list[str]:
    core_source = QGIS_SOURCE / "src" / "core"
    header_dirs = {
        path.parent
        for pattern in ("*.h", "*.hpp")
        for path in core_source.rglob(pattern)
    }
    gui_source = QGIS_SOURCE / "src" / "gui"
    header_dirs.update(
        path.parent
        for pattern in ("*.h", "*.hpp")
        for path in gui_source.rglob(pattern)
    )
    analysis_source = QGIS_SOURCE / "src" / "analysis"
    header_dirs.update(
        path.parent
        for pattern in ("*.h", "*.hpp")
        for path in analysis_source.rglob(pattern)
    )
    return [
        str(core_source),
        str(gui_source),
        str(analysis_source),
        *[str(path) for path in sorted(header_dirs)],
        # Public QGIS headers pull vendored external headers (e.g.
        # qgsabstractgeometry.h → nlohmann/json_fwd.hpp); the QGIS build
        # itself consumed them via -isystem, the binding compile needs them
        # here too.
        str(QGIS_SOURCE / "external" / "nlohmann"),
        str(build_dir),
        str(build_dir / "src" / "core"),
        str(build_dir / "src" / "gui"),
        # uic-generated ui_*_base.h headers for the symbology dialogs.
        str(build_dir / "src" / "ui"),
    ]


def _build_vendored_qgis() -> tuple[Path, Path]:
    if not (QGIS_SOURCE / "UPSTREAM.md").is_file():
        raise RuntimeError(f"vendored QGIS source is missing: {QGIS_SOURCE}")

    build_dir = _vendor_build_dir()
    core_library = _vendor_core_library(build_dir)
    gui_library = _vendor_gui_library(build_dir)
    analysis_library = _vendor_analysis_library(build_dir)
    resource_database = build_dir / "resources" / "srs.db"
    jobs = os.environ.get("PALEO_QGIS_BUILD_JOBS", "2").strip() or "2"
    cmake_args = [
        "cmake",
        "-S",
        str(QGIS_SOURCE),
        "-B",
        str(build_dir),
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DWITH_PYTHON=OFF",
        "-DWITH_BINDINGS=OFF",
        "-DWITH_DESKTOP=OFF",
        "-DWITH_QGIS_PROCESS=OFF",
        "-DWITH_3D=OFF",
        "-DWITH_GUI=ON",
        "-DWITH_ANALYSIS=ON",
        "-DWITH_AUTH=ON",
        "-DWITH_CRASH_HANDLER=OFF",
        "-DWITH_SERVER=OFF",
        "-DWITH_CUSTOM_WIDGETS=OFF",
        "-DWITH_QUICK=OFF",
        "-DWITH_QTWEBENGINE=OFF",
        "-DWITH_QTPOSITIONING=OFF",
        # PDAL (point clouds) is irrelevant to the 2D render bridge and its
        # dev package is not in the CI apt list — the vendored default (ON)
        # made every bridge configure fail at FindPDAL (#935 follow-up).
        "-DWITH_PDAL=OFF",
        # Draco (mesh compression) likewise: default ON, fatal FindDraco on
        # runners without libdraco-dev.
        "-DWITH_DRACO=OFF",
        # Qt6SerialPort is GPS-field hardware support; default ON and a hard
        # requirement the runner image lacks.
        "-DWITH_QTSERIALPORT=OFF",
        "-DWITH_INTERNAL_SPATIALINDEX=ON",
        "-DUSE_OPENCL=OFF",
        "-DENABLE_TESTS=OFF",
        "-DENABLE_LOCAL_BUILD_SHORTCUTS=ON",
        "-DUSE_CCACHE=OFF",
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE",
        "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE",
    ]
    prefix = os.environ.get("PALEO_QGIS_CMAKE_PREFIX", "").strip()
    if not prefix:
        prefix = os.environ.get("CMAKE_PREFIX_PATH", "").strip().split(os.pathsep)[0]
    if prefix:
        cmake_args.append(f"-DCMAKE_PREFIX_PATH={prefix}")
    try:
        if _reuse_vendor_requested(build_dir):
            # Artifacts already validated by _reuse_vendor_requested; skip
            # configure/build entirely (cross-worktree vendor reuse).
            pass
        else:
            subprocess.run(cmake_args, check=True)
            if not all(
                library.is_file()
                for library in (core_library, gui_library, analysis_library)
            ) or not resource_database.is_file():
                subprocess.run(
                    [
                        "cmake", "--build", str(build_dir),
                        "--target", "resources", "qgis_core", "qgis_gui", "qgis_analysis",
                        "--parallel", jobs,
                    ],
                    check=True,
                )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("could not build the vendored QGIS core") from exc
    for library in (core_library, gui_library, analysis_library):
        if not library.is_file():
            raise RuntimeError(f"vendored QGIS library is missing: {library}")
    if not resource_database.is_file():
        raise RuntimeError(f"vendored QGIS resource database is missing: {resource_database}")
    return build_dir, core_library


def _extension() -> Pybind11Extension:
    build_dir, core_library = _build_vendored_qgis()
    gui_library = _vendor_gui_library(build_dir)
    analysis_library = _vendor_analysis_library(build_dir)
    prefix = build_dir / "output"
    include_dir = QGIS_SOURCE / "src" / "core"
    if not (include_dir / "qgsapplication.h").is_file():
        raise RuntimeError(f"vendored QGIS include directory is invalid: {include_dir}")
    if sys.platform == "win32":
        compile_args = ["/O2", "/std:c++20"]
        link_args = [str(core_library), str(gui_library), str(analysis_library)]
    else:
        compile_args = ["-O2", "-std=c++20", "-Wall", "-Wextra"]
        library_rpath = core_library.parent
        link_args = [
            str(core_library),
            str(gui_library),
            str(analysis_library),
            f"-Wl,-rpath,{library_rpath}",
        ]
    return Pybind11Extension(
        "qgis_render_bridge",
        [
            str(HERE / "src" / "qgis_render_bridge.cpp"),
            str(HERE / "src" / "style_codec.cpp"),
            str(HERE / "src" / "gui_service.cpp"),
            str(HERE / "src" / "geometry_service.cpp"),
            str(HERE / "src" / "map_stack_service.cpp"),
            str(HERE / "src" / "edit_tools.cpp"),
            str(HERE / "src" / "bindings.cpp"),
        ],
        include_dirs=[*_qgis_core_include_dirs(build_dir), *_qt_include_dirs()],
        libraries=["Qt6Svg"],
        extra_link_args=link_args,
        define_macros=[("PALEO_QGIS_PREFIX_PATH", f'\"{prefix}\"')],
        cxx_std=20,
        extra_compile_args=compile_args,
    )


setup(
    name="qgis_render_bridge",
    version="0.2.17a0",
    description="Optional narrow C++ QGIS renderer bridge for paleo-workbench",
    ext_modules=[_extension()] if _enabled() else [],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12,<3.14",
)
