from __future__ import annotations

from pathlib import Path
import sys

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

HERE = Path(__file__).resolve().parent

def _compile_args() -> list[str]:
    """Return compiler flags, detecting MSVC vs GCC/Clang on all platforms."""
    try:
        from setuptools.command.build_ext import build_ext as _be
        compiler = getattr(_be, 'compiler_type', None)
    except Exception:
        compiler = None
    # On Windows default to MSVC unless evidence of GCC/MinGW
    if sys.platform == "win32" and compiler != "unix":
        return ["/O2", "/fp:fast"]
    # -ffast-math implies -ffinite-math-only, which lets the compiler assume
    # NaN/Inf never occur — optimising std::isnan/std::isinf to constant false.
    # The extension deliberately filters NaN/Inf (LAS token parsing, null
    # masking, downsample bucketing), so re-enable finite-math handling with
    # -fno-finite-math-only while keeping the rest of -ffast-math's wins.
    return ["-O3", "-ffast-math", "-fno-finite-math-only"]

extra_compile_args = _compile_args()

ext_modules = [
    Pybind11Extension(
        "well_log_core",
        [str(HERE / "src" / "well_log_core.cpp")],
        cxx_std=17,
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="well_log_core",
    version="0.1.0",
    description="Native well log curve processing, LOD downsampling and fast LAS parsing acceleration",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
