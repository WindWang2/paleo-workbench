"""Compatibility re-export: the mirror lives in mapping/ (M7 layering).

Snapshot → QGIS mirror sync is document-domain work (mapping → bridge), not
UI-domain; the import path is kept for existing callers and tests.
"""
from paleo_workbench.mapping.qgis_mirror import (  # noqa: F401
    mirror_snapshot_to_stack,
)

__all__ = ["mirror_snapshot_to_stack"]
