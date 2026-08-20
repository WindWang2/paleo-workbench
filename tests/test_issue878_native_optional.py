"""The application must import and start without the opt-in native cores (#878).

``grid_render_core`` and ``layer_model_core`` are opt-in C++ builds that no
declared dependency installs (``pyproject.toml`` ships only ``pybind11`` in the
``native`` extra; the cores live in separate distributions under ``native/``).
They were imported at module scope by ``paleo_workbench.viz.native_factor_map``
and ``paleo_workbench.ui.native_layer_tree``, so the ``paleo-workbench`` entry
point died with ``ModuleNotFoundError`` on any install that had not built them.

CI builds all cores as required steps, which is exactly why this regressed
unnoticed — so these tests run in a subprocess with the two modules forcibly
blocked, reproducing a fallback-only install even when the extensions *are*
present in the current environment.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

_BLOCKER = """
import sys

_BLOCKED = {"grid_render_core", "layer_model_core"}


class _Blocker:
    '''Simulate an install where the opt-in native cores were never built.'''

    def find_module(self, fullname, path=None):  # legacy API, harmless
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname in _BLOCKED:
            raise ImportError(f"blocked for test: {fullname}")
        return None


for _name in list(sys.modules):
    if _name in _BLOCKED:
        del sys.modules[_name]
sys.meta_path.insert(0, _Blocker())

import importlib.util
for _name in sorted(_BLOCKED):
    try:
        importlib.util.find_spec(_name)
    except ImportError:
        pass
    else:
        raise AssertionError(f"{_name} was not blocked; the test setup is invalid")
"""


def _run(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_app_shell_imports_without_native_cores() -> None:
    """The Qt shell — and so the entry point — must import with no cores built."""
    proc = _run(
        """
        from paleo_workbench.ui.app_shell import AppShell
        assert AppShell is not None
        print("OK")
        """
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


@pytest.mark.parametrize(
    "module",
    ["paleo_workbench.viz.native_factor_map", "paleo_workbench.ui.native_layer_tree"],
)
def test_native_backed_modules_import_without_cores(module: str) -> None:
    """Neither module may import its C++ core at module scope."""
    proc = _run(
        f"""
        import importlib
        importlib.import_module({module!r})
        print("OK")
        """
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


def test_map_scene_reports_missing_cores_with_install_guidance() -> None:
    """Constructing a scene without the cores fails loudly and actionably.

    ``MapScene`` wraps stateful C++ objects (``LayerRegistry``,
    ``ScalarGridLayer``) that have no pure-Python counterpart, so it genuinely
    cannot operate without the extensions. The contract is a diagnostic
    ``RuntimeError`` naming both modules and the install command — never an
    opaque ``ModuleNotFoundError`` at import time.
    """
    proc = _run(
        """
        from paleo_workbench.viz.native_factor_map import (
            MapScene, native_scene_available, require_native_scene,
        )
        assert native_scene_available() is False

        for call in (MapScene, require_native_scene):
            try:
                call()
            except RuntimeError as exc:
                message = str(exc)
            else:
                raise AssertionError(f"{call!r} should have raised RuntimeError")
            assert "layer_model_core" in message, message
            assert "grid_render_core" in message, message
            assert "pip install -e native/" in message, message
        print("OK")
        """
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout
