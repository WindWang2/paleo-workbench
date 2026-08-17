"""#628: native extension flags must follow the selected compiler, not a class attr."""

from __future__ import annotations

import importlib.util
from pathlib import Path

def _load_helper():
    helper = Path(__file__).resolve().parents[1] / "native" / "native_compile_flags.py"
    spec = importlib.util.spec_from_file_location("native_compile_flags", helper)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compile_args_for, mod.link_args_for


def test_win32_mingw_uses_unix_flags_not_msvc():
    compile_args_for, _ = _load_helper()
    args = compile_args_for("unix", platform="win32")
    assert "/O2" not in args
    assert "-O3" in args
    assert "-ffast-math" in args
    assert "-fno-finite-math-only" in args


def test_win32_msvc_keeps_msvc_flags():
    compile_args_for, _ = _load_helper()
    args = compile_args_for("msvc", platform="win32")
    assert args[0] == "/O2"
    assert "/fp:fast" in args
    assert "-O3" not in args


def test_win32_missing_compiler_type_defaults_to_msvc():
    compile_args_for, _ = _load_helper()
    args = compile_args_for(None, platform="win32")
    assert "/O2" in args


def test_openmp_dialect_follows_compiler():
    compile_args_for, link_args_for = _load_helper()
    assert "/openmp" in compile_args_for("msvc", platform="win32", openmp=True)
    assert "-fopenmp" in compile_args_for("unix", platform="win32", openmp=True)
    assert link_args_for("msvc", platform="win32", openmp=True) == []
    assert "-fopenmp" in link_args_for("unix", platform="linux", openmp=True)
    assert link_args_for("unix", platform="linux", openmp=False) == []
