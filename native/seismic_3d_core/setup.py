from __future__ import annotations

from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

import sys

HERE = Path(__file__).resolve().parent

extra_compile_args = ["/O2", "/fp:fast"] if sys.platform == "win32" else ["-O3"]

ext_modules = [
    Pybind11Extension(
        "seismic_3d_core",
        [str(HERE / "src" / "seismic_3d_core.cpp")],
        cxx_std=17,
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="seismic_3d_core",
    version="0.1.0",
    description="Native 3D seismic volume processing and slice extraction acceleration",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
