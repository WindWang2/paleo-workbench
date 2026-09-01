"""Work-area map snapshot producer for the home page centerpiece (工区地图).

Pure producer: a :class:`~paleo_workbench.project.models.ProjectDocument` goes
in, an immutable
:class:`~paleo_workbench.mapping.map_render_backend.MapRenderSnapshot` comes
out.  No Qt widgets, no IO, no caching — refresh policy (``domain_signature``
invalidation) lives with the home page; this module only answers "what should
the work-area map look like right now?".

Layers (id prefix ``home_workarea:`` so they never collide with authoring-map
layers), bottom to top:

1. ``boundary``      — WorkArea outline (closed ring, solid stroke).
2. ``surveys``       — one closed-ring polygon per seismic-survey footprint
   (distinct dash style).  Survey corners live in the SURVEY CRS: a survey
   whose declared CRS does not match the project CRS is withheld — overlaying
   incompatible frames is never correct — and surfaced through
   :func:`workarea_crs_warnings` (§20: withholding must be visible).
3. ``survey_labels`` — transparent centroid points carrying the survey name
   labels.  The fallback renderer paints labels on point layers only, so
   without this companion layer a bridge-less install would draw nameless
   footprints.
4. ``wells`` / ``wells_flagged`` — projected well heads
   (``spatial_scope == "workarea"`` only) split by coordinate status so
   flagged wells keep their ⚠ colour vocabulary.

Status/CRS rules mirror ``ui/pages/project_well_map_page.py`` so both maps
tell one story about the same domain data.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
)
from paleo_workbench.project.domain import (
    CoordinateStatus,
    complete_survey_corners,
    crs_equivalent,
    domain_signature,
)

__all__ = [
    "BOUNDARY_LAYER_ID",
    "SURVEY_LABEL_LAYER_ID",
    "SURVEY_LAYER_ID",
    "WELLS_FLAGGED_LAYER_ID",
    "WELLS_LAYER_ID",
    "WORKAREA_LEGEND_ITEMS",
    "build_workarea_map_snapshot",
    "domain_signature",
    "snapshot_has_map_content",
    "workarea_crs_warnings",
    "workarea_view_extent",
]

# Own prefix so these layers never collide with mapping-page layers.
BOUNDARY_LAYER_ID = "home_workarea:boundary"
SURVEY_LAYER_ID = "home_workarea:surveys"
SURVEY_LABEL_LAYER_ID = "home_workarea:survey_labels"
WELLS_LAYER_ID = "home_workarea:wells"
WELLS_FLAGGED_LAYER_ID = "home_workarea:wells_flagged"

# Same colour vocabulary as the Well Location map so one data story keeps
# one look across pages.
_COLOR_WELL_OK = "#409cff"
_COLOR_WELL_FLAGGED = "#f59e0b"
_COLOR_BOUNDARY = "#64748b"
_COLOR_SURVEY = "#0d9488"

# (label, colour) pairs for the host canvas legend; kept beside the styles
# so the chrome can never drift from what the layers actually draw.
WORKAREA_LEGEND_ITEMS: tuple[tuple[str, str], ...] = (
    ("工区边界", _COLOR_BOUNDARY),
    ("地震工区", _COLOR_SURVEY),
    ("井位", _COLOR_WELL_OK),
    ("井位（坐标待处理）", _COLOR_WELL_FLAGGED),
)

_BOUNDARY_STYLE = VectorStyle(
    # Subtle interior tint turns the ring into a visible study-area shape
    # (#AARRGGBB, ~13% slate) while keeping the solid outline dominant.
    fill="#2264748b",
    stroke=_COLOR_BOUNDARY,
    stroke_width=2.0,
).to_dict()

_SURVEY_STYLE = VectorStyle(
    fill="transparent",
    stroke=_COLOR_SURVEY,
    stroke_width=1.5,
    line_pattern=LinePattern.DASH,
).to_dict()

_SURVEY_LABEL_STYLE = VectorStyle(
    fill="transparent",
    stroke="transparent",
    marker=MarkerSymbol.CIRCLE,
    marker_size=0.0,
    labels=TextStyle(
        field="name", size=20.0, color="#0f172a", bold=True,
        halo_color="#f8fafc", halo_width=3.0,
    ),
).to_dict()

_WELL_OK_STYLE = VectorStyle(
    fill=_COLOR_WELL_OK,
    stroke="#182431",
    stroke_width=1.4,
    marker=MarkerSymbol.WELL,
    marker_size=11.0,
    labels=TextStyle(
        field="name", size=8.0, color="#0f172a", halo_color="#f8fafc", halo_width=1.6
    ),
).to_dict()

_WELL_FLAGGED_STYLE = VectorStyle(
    fill=_COLOR_WELL_FLAGGED,
    stroke="#182431",
    stroke_width=1.4,
    marker=MarkerSymbol.WELL,
    marker_size=11.0,
    labels=TextStyle(
        field="name", size=8.0, color="#0f172a", halo_color="#f8fafc", halo_width=1.6
    ),
).to_dict()


def project_crs_of(project: Any) -> str:
    """Canonical project CRS (``ProjectDocument.coordinate.project_crs``)."""
    return str(getattr(getattr(project, "coordinate", None), "project_crs", "") or "")


def workarea_crs_warnings(project: Any) -> list[str]:
    """⚠ banner entries for domain overlays withheld due to a CRS mismatch.

    Mirrors ``project_well_map_page._refresh_crs_warnings``: every skipped
    frame becomes a visible warning instead of a silent omission.
    """
    if project is None:
        return []
    project_crs = project_crs_of(project)
    warnings: list[str] = []
    workarea = getattr(project, "workarea", None)
    boundary_crs = str(getattr(workarea, "boundary_crs", "") or "") if workarea else ""
    if (
        boundary_crs
        and getattr(workarea, "boundary", None)
        and not crs_equivalent(boundary_crs, project_crs)
    ):
        warnings.append(f"工区边界坐标系 {boundary_crs} 与工程不一致，未叠加")
    for survey in getattr(project, "seismic_surveys", None) or []:
        survey_crs = str(getattr(survey, "crs", "") or "")
        if (
            survey_crs
            and getattr(survey, "extent", None)
            and not crs_equivalent(survey_crs, project_crs)
        ):
            warnings.append(
                f"地震工区「{getattr(survey, 'name', '')}」坐标系 {survey_crs} 与工程不一致，未叠加"
            )
    return warnings


def build_workarea_map_snapshot(project: Any) -> MapRenderSnapshot:
    """Turn a project document into the home work-area map composition."""
    if project is None:
        return MapRenderSnapshot(project_crs="", layers=())
    project_crs = project_crs_of(project)
    layers: list[MapLayerSnapshot] = []
    for layer in (
        _boundary_layer(project, project_crs),
        _survey_layer(project, project_crs),
        _survey_label_layer(project, project_crs),
        _well_layer(project, project_crs, flagged=False),
        _well_layer(project, project_crs, flagged=True),
    ):
        if layer is not None:
            layers.append(layer)
    return MapRenderSnapshot(project_crs=project_crs, layers=tuple(layers))


def snapshot_has_map_content(snapshot: MapRenderSnapshot) -> bool:
    """True when at least one layer carries drawable features."""
    return any(layer.features for layer in snapshot.layers)


def workarea_view_extent(
    snapshot: MapRenderSnapshot,
    *,
    margin_ratio: float = 0.15,
) -> tuple[float, float, float, float] | None:
    """Padded full extent for the initial fit; ``None`` without content.

    Padding follows the same rule as the Well Location map's
    ``_set_bounds`` so a single-point or zero-span population still gets a
    sane viewport.
    """
    populated = [layer.extent for layer in snapshot.layers if layer.features]
    if not populated:
        return None
    xmin = min(extent[0] for extent in populated)
    ymin = min(extent[1] for extent in populated)
    xmax = max(extent[2] for extent in populated)
    ymax = max(extent[3] for extent in populated)
    dx = max(xmax - xmin, abs(xmin) * 1e-3, 1e-6) * margin_ratio
    dy = max(ymax - ymin, abs(ymin) * 1e-3, 1e-6) * margin_ratio
    return (xmin - dx, ymin - dy, xmax + dx, ymax + dy)


# ---------------------------------------------------------------------------
# layer builders
# ---------------------------------------------------------------------------


def _finite_xy(point: Any) -> tuple[float, float] | None:
    """First two coordinates as finite floats, or ``None`` when unusable."""
    try:
        if len(point) < 2:
            return None
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def _closed_ring(corners: Iterable[Any]) -> list[list[float]]:
    """Ring with first == last (GeoJSON polygon convention)."""
    points: list[tuple[float, float]] = []
    for corner in corners:
        xy = _finite_xy(corner)
        if xy is not None:
            points.append(xy)
    if len(points) >= 3 and points[0] != points[-1]:
        points.append(points[0])
    return [list(point) for point in points]


def _feature(
    feature_id: str, geometry: Mapping[str, Any], **properties: Any
) -> dict[str, Any]:
    return {"id": feature_id, "geometry": dict(geometry), "properties": properties}


def _extent_of_features(features: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for feature in features:
        coordinates = feature.get("geometry", {}).get("coordinates")
        for point in _iter_leaf_coordinates(coordinates):
            xs.append(point[0])
            ys.append(point[1])
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _iter_leaf_coordinates(node: Any) -> Iterable[tuple[float, float]]:
    """Yield (x, y) leaves of a nested GeoJSON coordinate structure."""
    if not isinstance(node, (list, tuple)):
        return
    if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
        xy = _finite_xy(node)
        if xy is not None:
            yield xy
        return
    for child in node:
        yield from _iter_leaf_coordinates(child)


def _content_revision(features: Sequence[Mapping[str, Any]]) -> int:
    """Content-derived ``data_revision``.

    The canvas skips re-render when a layer's revision is unchanged; a static
    revision would freeze the map after the first domain edit (a well moves,
    the boundary is redrawn) even though the page rebinds a fresh snapshot.
    Freezing the payload into a hashable tuple keeps it deterministic and
    cheap (domain changes only).
    """
    return hash(_freeze(features)) & 0x7FFFFFFF


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _boundary_layer(project: Any, project_crs: str) -> MapLayerSnapshot | None:
    workarea = getattr(project, "workarea", None)
    boundary = list(getattr(workarea, "boundary", None) or []) if workarea else []
    if not boundary:
        return None
    # Only draw when the boundary frame matches the project frame — never
    # silently overlay incompatible coordinate systems (§20).
    boundary_crs = str(getattr(workarea, "boundary_crs", "") or "")
    if boundary_crs and not crs_equivalent(boundary_crs, project_crs):
        return None
    ring = _closed_ring(boundary)
    if len(ring) < 4:  # closed triangle minimum
        return None
    name = str(getattr(workarea, "name", "") or "") or str(
        getattr(getattr(project, "meta", None), "name", "") or ""
    )
    features = (
        _feature(
            "boundary",
            {"type": "Polygon", "coordinates": [ring]},
            name=name or "工区范围",
        ),
    )
    return MapLayerSnapshot(
        id=BOUNDARY_LAYER_ID,
        name="工区边界",
        layer_type="vector",
        extent=_extent_of_features(features),
        crs=project_crs,
        data_revision=_content_revision(features),
        style_revision=1,
        features=features,
        style=_BOUNDARY_STYLE,
    )


def _survey_footprints(project: Any, project_crs: str) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    """Drawable, CRS-gated survey footprint polygons + their centroids."""
    features: list[dict[str, Any]] = []
    centroids: list[tuple[float, float]] = []
    for survey in getattr(project, "seismic_surveys", None) or []:
        survey_crs = str(getattr(survey, "crs", "") or "")
        # Survey corners live in the SURVEY frame; skip frames that don't
        # match the project instead of mis-aligning them silently (§20).
        if survey_crs and not crs_equivalent(survey_crs, project_crs):
            continue
        corners: list[tuple[float, float]] = []
        for corner in getattr(survey, "extent", None) or []:
            xy = _finite_xy(corner)
            if xy is not None:
                corners.append(xy)
        if len(corners) < 3:
            continue
        # 旧工程可能只有 3 角点（提取期设计），补出平行四边形第 4 角再画。
        corners = [
            (float(c[0]), float(c[1])) for c in complete_survey_corners(corners)
        ]
        survey_id = str(getattr(survey, "id", "") or "")
        name = str(getattr(survey, "name", "") or "")
        features.append(
            _feature(
                f"surveys:{survey_id}",
                {"type": "Polygon", "coordinates": [_closed_ring(corners)]},
                name=name,
                survey_id=survey_id,
            )
        )
        centroids.append(
            (sum(x for x, _ in corners) / len(corners), sum(y for _, y in corners) / len(corners))
        )
    return features, centroids


def _survey_layer(project: Any, project_crs: str) -> MapLayerSnapshot | None:
    features, _centroids = _survey_footprints(project, project_crs)
    if not features:
        return None
    return MapLayerSnapshot(
        id=SURVEY_LAYER_ID,
        name="地震工区",
        layer_type="vector",
        extent=_extent_of_features(features),
        crs=project_crs,
        data_revision=_content_revision(features),
        style_revision=1,
        features=tuple(features),
        style=_SURVEY_STYLE,
    )


def _survey_label_layer(project: Any, project_crs: str) -> MapLayerSnapshot | None:
    """Transparent centroid points so survey names render without the QGIS
    bridge (the fallback paints labels on point layers only)."""
    features, centroids = _survey_footprints(project, project_crs)
    if not centroids:
        return None
    label_features = tuple(
        _feature(
            f"survey_labels:{feature['properties']['survey_id']}",
            {"type": "Point", "coordinates": [x, y]},
            name=feature["properties"]["name"],
            survey_id=feature["properties"]["survey_id"],
        )
        for feature, (x, y) in zip(features, centroids)
    )
    return MapLayerSnapshot(
        id=SURVEY_LABEL_LAYER_ID,
        name="地震工区标注",
        layer_type="vector",
        extent=_extent_of_features(label_features),
        crs=project_crs,
        data_revision=_content_revision(label_features),
        style_revision=1,
        features=label_features,
        style=_SURVEY_LABEL_STYLE,
    )


def _well_layer(project: Any, project_crs: str, *, flagged: bool) -> MapLayerSnapshot | None:
    features: list[dict[str, Any]] = []
    for well in getattr(project, "wells", None) or []:
        # Reference wells stay governed project data but are withheld from
        # the WorkArea map, exactly as on the Well Location map.
        if str(getattr(well, "spatial_scope", "workarea") or "workarea") != "workarea":
            continue
        is_flagged = getattr(well, "coordinate_status", "") != CoordinateStatus.OK
        if is_flagged != flagged:
            continue
        xy = _finite_xy((getattr(well, "project_x", None), getattr(well, "project_y", None)))
        if xy is None:
            continue
        well_id = str(getattr(well, "id", "") or "")
        features.append(
            _feature(
                f"wells:{well_id}",
                {"type": "Point", "coordinates": [xy[0], xy[1]]},
                name=str(getattr(well, "name", "") or ""),
                well_id=well_id,
                coordinate_status=str(getattr(well, "coordinate_status", "") or ""),
            )
        )
    if not features:
        return None
    return MapLayerSnapshot(
        id=WELLS_FLAGGED_LAYER_ID if flagged else WELLS_LAYER_ID,
        name="井位（坐标待处理）" if flagged else "井位",
        layer_type="vector",
        extent=_extent_of_features(features),
        crs=project_crs,
        data_revision=_content_revision(features),
        style_revision=1,
        features=tuple(features),
        style=_WELL_FLAGGED_STYLE if flagged else _WELL_OK_STYLE,
    )
