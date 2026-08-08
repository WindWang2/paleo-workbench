"""Runtime accessor for the active :class:`CatalogPort` backend.

Resolution order:

1. An explicit backend set via :func:`set_catalog` (the project controller
   installs a :class:`~paleo_workbench.catalog.adapter.CoreCatalogAdapter`
   when a project is opened; tests inject fakes).
2. A backend configured via the ``PALEO_DATA_CATALOG`` import path env var.
3. ``None`` — no catalog is active (e.g. no project open). Business hooks
   degrade gracefully in that case; the legacy code path keeps working.

There is deliberately NO production in-memory fallback: the authoritative
runtime backend is always the Core
:class:`~paleo_workbench.catalog.service.DataCatalogService` (via the
adapter). The ``InMemoryCatalog`` reference fake lives under ``tests/fakes``.
"""

from __future__ import annotations

import os
from typing import Optional

from paleo_workbench.catalog.port import CatalogPort

# Module-level active backend. Only instantiated via set_catalog / env var.
_active: Optional[CatalogPort] = None


def get_catalog() -> CatalogPort | None:
    """Return the active catalog backend, or None when no project catalog is wired.

    Resolution:

    - An explicitly injected backend (``set_catalog``) wins.
    - The ``PALEO_DATA_CATALOG`` env var names a dotted path to a callable /
      class implementing :class:`CatalogPort`; it is imported and invoked.
    - Otherwise ``None`` (callers must degrade gracefully).
    """
    global _active
    if _active is not None:
        return _active

    dotted = os.environ.get("PALEO_DATA_CATALOG")
    if dotted:
        backend = _import_dotted(dotted)
        if backend is not None:
            _active = backend
            return backend
    return None


def get_catalog_service():
    """Return the active Core ``DataCatalogService``, or None.

    Convenience for UI code that needs service operations beyond the
    :class:`CatalogPort` surface (import / materialize / working copies).
    Returns None when the active backend is not a Core adapter.
    """
    catalog = get_catalog()
    service = getattr(catalog, "service", None)
    return service


def set_catalog(catalog: CatalogPort | None) -> None:
    """Inject (or clear) the active catalog backend.

    Passing ``None`` resets to lazy resolution. The project controller calls
    this with a Core adapter on project open and clears it on project close;
    tests use it to install fakes.
    """
    global _active
    _active = catalog


def reset_catalog() -> None:
    """Clear any injected backend so the next :func:`get_catalog` re-resolves."""
    global _active
    _active = None


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
        # A misconfigured env var must never crash business code.
        return None
