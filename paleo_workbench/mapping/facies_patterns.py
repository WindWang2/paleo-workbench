"""Sedimentary-facies → SVG pattern data contract (map polygon fills).

This module is the data-contract layer for "fill facies polygons on the map
with SVG patterns".  It owns only the *mapping* from a facies name to a
pattern asset — it never renders anything, so it stays pure Python with no
Qt/QGIS dependency and is importable from any environment.

Pattern assets live in the geo-viz-engine package
(``assets/patterns/facies/*.svg``): 32x32 viewBox transparent-background
black linework tiles designed to overlay a base fill colour.

A *pattern id* is the SVG file stem (file name without the ``.svg``
extension), e.g. ``"delta"`` for ``delta.svg``.  The render side resolves an
id to a file as ``FACIES_PATTERN_DIR / f"{pattern_id}.svg"`` (see
:func:`pattern_path_for_facies`).
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "FACIES_PATTERN_DIR",
    "FACIES_PATTERN_MAP",
    "pattern_id_for_facies",
    "pattern_path_for_facies",
]

#: Absolute directory of the facies SVG pattern tiles.  Resolved from the
#: repo-relative location (same idiom as
#: ``paleo_workbench.viz.prediction_tracks._SVG_TEXTURE_DIR``).
FACIES_PATTERN_DIR = (
    Path(__file__).resolve().parents[2]
    / "geo-viz-engine"
    / "packages"
    / "geoviz_well_log"
    / "geoviz_well_log"
    / "assets"
    / "patterns"
    / "facies"
)

#: Facies name → pattern id (SVG stem, no extension).  Names cover the 9
#: ``geological_symbols._FACIES_CLASSES`` English ids, the 4
#: ``mock_facies.MOCK_FACIES_CLASSES`` Chinese classes, and generic Chinese
#: aliases.  Exact matches map directly; approximate ones pick the nearest
#: geological semantics (reasons in the comments).  ``volcanic``/``other``
#: (and ``火山岩``/``其他``) have no tile and are deliberately absent —
#: lookups for them return ``None``.
FACIES_PATTERN_MAP: dict[str, str] = {
    # -- English ids with an exact tile -------------------------------------
    "alluvial_fan": "alluvial_fan",
    "fluvial": "fluvial",
    "lacustrine": "lacustrine",
    "delta": "delta",
    "shallow_marine": "shallow_marine",
    "deep_marine": "deep_marine",
    # "shoreline" has no exact tile: the nearshore/shoreface zone is the
    # wave-dominated shoreline deposit, so the shoreface tile is nearest.
    "shoreline": "shoreface",
    # -- mock Chinese classes ------------------------------------------------
    # 扇三角洲 (fan delta) is a delta-front depositional system → delta tile.
    "扇三角洲": "delta",
    # 三角洲前缘 (delta front) is the frontal subfacies of a delta → delta.
    "三角洲前缘": "delta",
    # 滨浅湖 (lake-margin + shallow-lake) is a lacustrine sub-environment,
    # not a marine shoreline → lacustrine, not shoreface.
    "滨浅湖": "lacustrine",
    # 湖相泥 (lake mud) is profundal/sublacustrine mud → lacustrine.
    "湖相泥": "lacustrine",
    # -- generic Chinese aliases ---------------------------------------------
    "冲积扇": "alluvial_fan",
    "河流": "fluvial",
    "湖泊": "lacustrine",
    "三角洲": "delta",
    # 岸线带 is the Chinese legend label of the "shoreline" id → shoreface.
    "岸线带": "shoreface",
    "浅海": "shallow_marine",
    "深海": "deep_marine",
}


def pattern_id_for_facies(name: str) -> str | None:
    """Return the pattern id for a facies name, or ``None`` when unmapped.

    Pure table lookup (no filesystem access); use
    :func:`pattern_path_for_facies` when you need the resolved file.
    """
    return FACIES_PATTERN_MAP.get(str(name).strip())


def pattern_path_for_facies(name: str) -> Path | None:
    """Return the existing SVG path for a facies name, or ``None``.

    ``None`` means either the name has no mapping or the mapped file is
    missing from :data:`FACIES_PATTERN_DIR`.
    """
    pattern_id = pattern_id_for_facies(name)
    if pattern_id is None:
        return None
    path = FACIES_PATTERN_DIR / f"{pattern_id}.svg"
    return path if path.is_file() else None
