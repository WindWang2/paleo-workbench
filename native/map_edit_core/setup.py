"""Build the map_edit_core pybind11 extension.

Install (from repo root)::

    python -m pip install -e native/map_edit_core

Or build in-place::

    cd native/map_edit_core && python setup.py build_ext --inplace
"""

from __future__ import annotations

from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

import sys

HERE = Path(__file__).resolve().parent

extra_compile_args = ["/O2", "/fp:fast"] if sys.platform == "win32" else ["-O3"]

ext_modules = [
    Pybind11Extension(
        "map_edit_core",
        [str(HERE / "src" / "map_edit_core.cpp")],
        cxx_std=17,
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="map_edit_core",
    version="0.1.0",
    description="Native geometry hot path for paleo mapping editor",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12",
)
