from __future__ import annotations

from pathlib import Path
import sys

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

HERE = Path(__file__).resolve().parent


def _compile_args() -> list[str]:
    if sys.platform == "win32":
        return ["/O2"]
    return ["-O3"]


setup(
    name="layer_model_core",
    version="0.2.17a0",
    description="Authoritative C++ layer model for paleo-workbench native maps",
    ext_modules=[
        Pybind11Extension(
            "layer_model_core",
            [
                str(HERE / "src" / "layer_model.cpp"),
                str(HERE / "src" / "bindings.cpp"),
            ],
            cxx_std=17,
            extra_compile_args=_compile_args(),
        )
    ],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.12,<3.13",
)
