"""Optional pybind build for the QGIS Core render bridge.

The extension is intentionally opt-in so ordinary host installs and CI environments
without QGIS remain usable. Set ``PALEO_WITH_QGIS_RENDERER=1`` and provide a QGIS
prefix (or explicit include/core-library paths) to build it.
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
            ["pkg-config", "--cflags-only-I", "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Xml"], text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Qt6Core, Qt6Gui, Qt6Widgets, and Qt6Xml pkg-config metadata is required for QGIS") from exc
    return [arg[2:] for arg in shlex.split(output) if arg.startswith("-I")]


def _extension() -> Pybind11Extension:
    prefix = Path(os.environ.get("QGIS_PREFIX_PATH", "/usr"))
    include_dir = Path(os.environ.get("QGIS_INCLUDE_DIR", prefix / "include" / "qgis"))
    core_library = Path(os.environ.get("QGIS_CORE_LIBRARY", prefix / "lib" / "libqgis_core.so"))
    if not (include_dir / "qgsapplication.h").is_file():
        raise RuntimeError(f"QGIS include directory is invalid: {include_dir}")
    if not core_library.is_file():
        raise RuntimeError(f"QGIS Core library is invalid: {core_library}")
    if sys.platform == "win32":
        compile_args = ["/O2", "/std:c++20"]
    else:
        compile_args = ["-O2", "-std=c++20", "-Wall", "-Wextra"]
    return Pybind11Extension(
        "qgis_render_bridge",
        [
            str(HERE / "src" / "qgis_render_bridge.cpp"),
            str(HERE / "src" / "bindings.cpp"),
        ],
        include_dirs=[str(include_dir), *_qt_include_dirs()],
        extra_link_args=[str(core_library)],
        define_macros=[("PALEO_QGIS_PREFIX_PATH", f'\"{prefix}\"')],
        cxx_std=20,
        extra_compile_args=compile_args,
    )


setup(
    name="qgis_render_bridge",
    version="0.1.0",
    description="Optional narrow C++ QGIS renderer bridge for paleo-workbench",
    ext_modules=[_extension()] if _enabled() else [],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
