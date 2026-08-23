from __future__ import annotations

from pathlib import Path
import sys

from pybind11.setup_helpers import Pybind11Extension
from setuptools import setup

HERE = Path(__file__).resolve().parent
_NATIVE = HERE.parent
if str(_NATIVE) not in sys.path:
    sys.path.insert(0, str(_NATIVE))
from native_compile_flags import NativeBuildExt  # noqa: E402

ext_modules = [
    Pybind11Extension(
        "grid_render_core",
        [
            str(HERE / "src" / "grid_render_core.cpp"),
            str(HERE / "src" / "scalar_grid_layer.cpp"),
            str(HERE / "src" / "bindings.cpp"),
        ],
        cxx_std=17,
    ),
]

setup(
    name="grid_render_core",
    version="0.2.17a0",
    description="Native scalar-grid rasterisation hot path for paleo-workbench factor maps",
    ext_modules=ext_modules,
    cmdclass={"build_ext": NativeBuildExt},
    zip_safe=False,
    python_requires=">=3.12,<3.13",
)
