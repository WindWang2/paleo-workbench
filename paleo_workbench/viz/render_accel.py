"""Install C++-accelerated render hooks into the geoviz engine.

Delegates hook installation to ``native_backend.install_all_hooks()``.
"""
from __future__ import annotations

from paleo_workbench.native_backend import install_all_hooks


def install_geoviz_acceleration() -> None:
    """Inject the C++ providers into geoviz (idempotent)."""
    install_all_hooks()
