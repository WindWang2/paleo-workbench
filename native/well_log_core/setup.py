from __future__ import annotations

from pathlib import Path
import sys

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

HERE = Path(__file__).resolve().parent

extra_compile_args = ["/O2", "/fp:fast"] if sys.platform == "win32" else ["-O3"]

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
