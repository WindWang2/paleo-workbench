from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension
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

HERE_NATIVE = HERE.parent
if str(HERE_NATIVE) not in sys.path:
    sys.path.insert(0, str(HERE_NATIVE))
from native_compile_flags import NativeBuildExt  # noqa: E402


class BuildExt(NativeBuildExt):
    openmp = _OPENMP


ext_modules = [
    Pybind11Extension(
        "seismic_3d_core",
        [str(HERE / "src" / "seismic_3d_core.cpp")],
        cxx_std=17,
    ),
]

setup(
    name="seismic_3d_core",
    version="0.2.17a0",
    description="Native 3D seismic volume processing and slice extraction acceleration",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExt},
    zip_safe=False,
    python_requires=">=3.12,<3.13",
)
