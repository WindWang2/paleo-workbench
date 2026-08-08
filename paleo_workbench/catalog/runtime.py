"""Runtime accessor for the active :class:`CatalogPort` backend.

Resolution order:

1. An explicit backend set via :func:`set_catalog` (tests, future Core wiring).
2. A backend configured via the ``PALEO_DATA_CATALOG`` import path env var.
3. A module-level :class:`~paleo_workbench.catalog.backend.InMemoryCatalog`
   singleton (the fallback while Core is absent).

Business modules call :func:`get_catalog` and never construct a backend
directly. When Kimi's Core lands, this function returns a Core-backed adapter
and nothing else changes.
"""

from __future__ import annotations

import os
from typing import Optional

from paleo_workbench.catalog.backend import InMemoryCatalog
from paleo_workbench.catalog.port import CatalogPort

# Module-level fallback singleton. Only instantiated lazily once.
_default: Optional[CatalogPort] = None


def _new_default() -> CatalogPort:
    """Build the fallback in-memory catalog (used until Core is wired)."""
    return InMemoryCatalog()


def get_catalog() -> CatalogPort:
    """Return the active catalog backend.

    Resolution:

    - An explicitly injected backend (``set_catalog``) wins.
    - The ``PALEO_DATA_CATALOG`` env var names a dotted path to a callable /
      class implementing :class:`CatalogPort`; it is imported and invoked.
    - Otherwise a process-wide :class:`InMemoryCatalog` singleton is used.

    The fallback is intentional and documented: this branch ships before the
    Core, so business integration must be testable against a reference backend.
    """
    global _default
    if _default is not None:
        return _default

    dotted = os.environ.get("PALEO_DATA_CATALOG")
    if dotted:
        backend = _import_dotted(dotted)
        if backend is not None:
            _default = backend
            return backend

    _default = _new_default()
    return _default


def set_catalog(catalog: CatalogPort | None) -> None:
    """Inject (or clear) the active catalog backend.

    Passing ``None`` resets to lazy resolution. Tests use this to install a
    fresh :class:`InMemoryCatalog` per case and to swap in Core-backed
    adapters later.
    """
    global _default
    _default = catalog


def reset_catalog() -> None:
    """Clear any injected backend so the next :func:`get_catalog` re-resolves."""
    global _default
    _default = None


def _import_dotted(dotted: str) -> CatalogPort | None:
    """Import ``module.attr`` and call it to produce a backend instance."""
    if ":" in dotted:
        module_name, attr = dotted.split(":", 1)
    elif "." in dotted:
        module_name, attr = dotted.rsplit(".", 1)
    else:
        return None
    try:
        import importlib

        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        return obj() if callable(obj) else obj  # type: ignore[return-value]
    except Exception:
        # A misconfigured env var must never crash business code; fall back.
        return None
