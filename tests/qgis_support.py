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

        return True
    except ImportError:
        return False


def require_qgis():
    """Import and return qgis_render_bridge, respecting PALEO_REQUIRE_QGIS."""
    import os
    import pytest

    strict = os.environ.get("PALEO_REQUIRE_QGIS", "").strip().lower() in {"1", "true", "yes"}
    if strict:
        import qgis_render_bridge

        return qgis_render_bridge
    return pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)


def require_mapstack():
    """Import and return qgis_render_bridge.mapstack, respecting PALEO_REQUIRE_QGIS."""
    import os
    import pytest

    strict = os.environ.get("PALEO_REQUIRE_QGIS", "").strip().lower() in {"1", "true", "yes"}
    if strict:
        import qgis_render_bridge.mapstack as mapstack

        return mapstack
    return pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)


def qgis_env_status() -> dict[str, object]:
    """Return runtime diagnostic metadata for QGIS test harness."""
    import os

    return {
        "available": qgis_bridge_available(),
        "strict_mode": os.environ.get("PALEO_REQUIRE_QGIS", "").strip().lower() in {"1", "true", "yes"},
        "skip_reason": QGIS_SKIP_REASON,
    }
