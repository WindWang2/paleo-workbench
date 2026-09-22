"""Install C++-accelerated render hooks into the geoviz engine.

Delegates hook installation to ``native_backend.install_all_hooks()``.
"""
from __future__ import annotations

from paleo_workbench.native_backend import _cpp_minmax_provider, install_all_hooks

_installed_provider = None


def install_geoviz_acceleration() -> None:
    """Inject the C++ providers into geoviz (idempotent)."""
    global _installed_provider
    if _installed_provider is not None:
        return
    install_all_hooks()
    _installed_provider = _cpp_minmax_provider
