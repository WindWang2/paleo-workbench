from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

import sys

HERE = Path(__file__).resolve().parent


def _cxx() -> str:
    import os
    import shutil

    return os.environ.get("CXX") or shutil.which("c++") or "c++"


def _openmp_available(cxx: str) -> bool:
    """Probe whether the toolchain can compile AND link OpenMP.

    clang ships without libomp on several hosts (``cannot find -lomp``); the
    extension's pragmas are fully guarded by ``#if defined(_OPENMP)``, so a
    serial build is functionally identical and preferable to a hard failure.
    """
    if sys.platform == "win32":
        return True  # MSVC /openmp needs no extra runtime probe here.
    source = (
        "#include <omp.h>\n"
        "int main() { return omp_get_max_threads() > 0 ? 0 : 1; }\n"
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "probe.cpp"
            src.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [cxx, str(src), "-fopenmp", "-o", str(Path(tmp) / "probe")],
                capture_output=True,
                timeout=120,
            )
            return result.returncode == 0
    except Exception:
        return False


_OPENMP = _openmp_available(_cxx())


def _compile_args() -> list[str]:
    """Return compiler flags, detecting MSVC vs GCC/Clang on all platforms."""
    try:
        from setuptools.command.build_ext import build_ext as _be
        compiler = getattr(_be, 'compiler_type', None)
    except Exception:
        compiler = None
    # On Windows default to MSVC unless evidence of GCC/MinGW
    if sys.platform == "win32" and compiler != "unix":
        return ["/O2", "/fp:fast", "/openmp"]
    args = ["-O3", "-ffast-math", "-fno-finite-math-only"]
    if _OPENMP:
        args.append("-fopenmp")
    return args


def _link_args() -> list[str]:
    if sys.platform == "win32":
        return []
    return ["-fopenmp"] if _OPENMP else []


extra_compile_args = _compile_args()
extra_link_args = _link_args()

ext_modules = [
    Pybind11Extension(
        "seismic_3d_core",
        [str(HERE / "src" / "seismic_3d_core.cpp")],
        cxx_std=17,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
    ),
]

setup(
    name="seismic_3d_core",
    version="0.2.17a0",
    description="Native 3D seismic volume processing and slice extraction acceleration",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
