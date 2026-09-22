"""Multiscale (相 / 亚相 / 微相) facies hierarchy service for the 古地理 map host.

``geo-viz-engine`` exposes an interactive, zoom-driven 3-level facies map
(``PaleoMapCanvas.load_hierarchy`` + ``FaciesHierarchy``). The workbench host
integrates it natively: when the map payload's facies features carry hierarchy
metadata (``level`` + ``parent_id`` GeoJSON properties), the host builds a
``FaciesHierarchy`` and switches the canvas to level-based display; otherwise it
keeps today's flat ``load_features`` path unchanged (backward compatible).

This module is the headless, Qt-free core (hierarchy detection / building /
level metadata) so it can be unit-tested without a canvas. The ``PaleoMapHost``
binds it to the live widget.
"""

from __future__ import annotations

from typing import Any, Sequence

# Facies hierarchy levels, ordered coarse → fine. These match the level names
# used by geo-viz-engine's PaleoMapCanvas (_LEVEL_ORDER) and FaciesHierarchy.
FACIES_LEVELS: tuple[str, ...] = ("facies", "sub_facies", "micro_facies")
LEVEL_DISPLAY: dict[str, str] = {
    "facies": "相（1 级）",
    "sub_facies": "亚相（2 级）",
    "micro_facies": "微相（3 级）",
}
#: UI sentinel for "choose level automatically from the map scale".
AUTO_LEVEL = "auto"


def _feature_level(feature: dict[str, Any]) -> str | None:
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        return None
    raw = props.get("level") or props.get("facies_level")
    if raw is None:
        return None
    level = str(raw).strip().lower()
    return level if level in FACIES_LEVELS else None


def hierarchy_levels_present(features: Sequence[dict[str, Any]]) -> list[str]:
    """Ordered list of hierarchy levels present in *features* (coarse → fine)."""
    present: set[str] = set()
    for feat in features or []:
        level = _feature_level(feat)
        if level is not None:
            present.add(level)
    return [lvl for lvl in FACIES_LEVELS if lvl in present]


def is_hierarchical_feature_set(features: Sequence[dict[str, Any]]) -> bool:
    """True when at least one feature carries recognized facies-level metadata.

    Flat facies data (no ``level`` property) returns False so the host keeps its
    existing flat ``load_features`` rendering. Only explicit multi/ single-level
    metadata opts into the hierarchy path.
    """
    return any(_feature_level(feat) is not None for feat in features or [])


def build_facies_hierarchy(features: Sequence[dict[str, Any]]):
    """Build a geo-viz-engine ``FaciesHierarchy`` from GeoJSON-like features.

    Imported lazily so the service stays importable in headless contexts and so
    importing this module never forces a Qt widget construction. Raises
    ``ValueError`` when the feature set is not hierarchical.
    """
    if not is_hierarchical_feature_set(features):
        raise ValueError("feature set carries no facies-level metadata")
    # Imported through the public geoviz facade (workbench architecture rule:
    # production code must not import geoviz_* subpackages directly).
    from geoviz import FaciesHierarchy

    return FaciesHierarchy.from_features(list(features))


def level_choices(features: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """UI combo choices for the level selector: ``[(value, label), ...]``.

    Always leads with the ``auto`` choice (zoom-driven); followed by the levels
    actually present. Returns an empty list for non-hierarchical feature sets
    (the selector is hidden then).
    """
    if not is_hierarchical_feature_set(features):
        return []
    choices: list[tuple[str, str]] = [(AUTO_LEVEL, "自动（按比例尺切换）")]
    for lvl in hierarchy_levels_present(features):
        choices.append((lvl, LEVEL_DISPLAY.get(lvl, lvl)))
    return choices
