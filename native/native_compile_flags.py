"""Compiler flags for native extension setup.py files.

``setuptools.command.build_ext.build_ext.compiler_type`` is a per-instance
attribute created during ``run()``. Reading it off the command class at
import time is always ``None``, which made MinGW-on-Windows take MSVC flags.
"""

from __future__ import annotations

import sys

from pybind11.setup_helpers import build_ext


def _is_msvc_compiler(compiler_type: str | None, platform: str | None = None) -> bool:
    plat = sys.platform if platform is None else platform
    if plat != "win32":
        return False
    if compiler_type in ("unix", "mingw32", "cygwin"):
        return False
    return True


def compile_args_for(
    compiler_type: str | None,
    *,
    platform: str | None = None,
    openmp: bool = False,
) -> list[str]:
    is_msvc = _is_msvc_compiler(compiler_type, platform)
    if is_msvc:
        args = ["/O2", "/fp:fast", "/std:c++17", "/utf-8", "/EHsc"]
        if openmp:
            args.append("-openmp:llvm")
        return args
    args = ["-O3", "-ffast-math", "-fno-finite-math-only"]
    if openmp:
        args.append("-fopenmp")
    return args


def link_args_for(
    compiler_type: str | None,
    *,
    platform: str | None = None,
    openmp: bool = False,
) -> list[str]:
    is_msvc = _is_msvc_compiler(compiler_type, platform)
    if is_msvc or not openmp:
        return []
    return ["-fopenmp"]


class NativeBuildExt(build_ext):
    """Apply flags from the selected compiler instance at build time."""

    openmp = False

    def build_extensions(self) -> None:
        compiler_type = getattr(self.compiler, "compiler_type", None)
        compile_args = compile_args_for(compiler_type, openmp=self.openmp)
        link_args = link_args_for(compiler_type, openmp=self.openmp)
        for ext in self.extensions:
            current_compile = list(ext.extra_compile_args or [])
            for flag in compile_args:
                if flag not in current_compile:
                    current_compile.append(flag)
            ext.extra_compile_args = current_compile

            extra_link = list(ext.extra_link_args or [])
            for flag in link_args:
                if flag not in extra_link:
                    extra_link.append(flag)
            ext.extra_link_args = extra_link
        super().build_extensions()
