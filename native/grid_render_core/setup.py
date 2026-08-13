from __future__ import annotations

from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

import sys

HERE = Path(__file__).resolve().parent


def _compile_args() -> list[str]:
    """Return compiler flags, detecting MSVC vs GCC/Clang on all platforms."""
    try:
        from setuptools.command.build_ext import build_ext as _be
        compiler = getattr(_be, "compiler_type", None)
    except Exception:
        compiler = None
    if sys.platform == "win32" and compiler != "unix":
        return ["/O2", "/fp:fast"]
    return ["-O3", "-ffast-math", "-fno-finite-math-only"]


extra_compile_args = _compile_args()

ext_modules = [
    Pybind11Extension(
        "grid_render_core",
        [
            str(HERE / "src" / "grid_render_core.cpp"),
            str(HERE / "src" / "scalar_grid_layer.cpp"),
            str(HERE / "src" / "bindings.cpp"),
        ],
        cxx_std=17,
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="grid_render_core",
    version="0.2.17a0",
    description="Native scalar-grid rasterisation hot path for paleo-workbench factor maps",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
