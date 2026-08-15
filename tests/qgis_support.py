"""Shared conditionalization for the optional QGIS render bridge (packaging #437).

The QGIS production renderer (``prefer_qgis=True``) builds a vendored QGIS
core via ``native/qgis_render_bridge`` and is deliberately **opt-in**: the main
CI gate installs neither QGIS nor the bridge, so every QGIS-path test below
self-skips there. This module is the single source of truth for that
conditional so the skip reason stays actionable and ``pytest -m qgis`` can
select the QGIS tests explicitly.
"""

from __future__ import annotations

# Shown in every QGIS skip so a developer knows exactly how to enable the
# path locally / in a QGIS CI leg.
QGIS_SKIP_REASON = (
    "optional qgis_render_bridge is not built; enable with: "
    "python -m pip install -e \".[qgis-renderer]\" && "
    "PALEO_WITH_QGIS_RENDERER=1 python -m pip install -e native/qgis_render_bridge"
)

# Marker name used with ``pytest -m qgis`` to select QGIS-only tests.
QGIS_MARKER = "qgis"


def qgis_bridge_available() -> bool:
    """True when the ``qgis_render_bridge`` extension is importable."""
    try:
        import qgis_render_bridge  # noqa: F401
    except ImportError:
        return False
    return True
