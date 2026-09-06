"""Calibrated well-trace projection onto seismic sections (L5).

Projects a registered well trajectory onto inline/crossline sections as
POLYLINE OVERLAYS — display annotations only; the interpreted data never
comes from here. Fail-closed by construction:

* the well must be registered in the :class:`CoordinateTransformHub`;
* the TWT ordinate comes ONLY from the well's :class:`TimeDepthCalibration`
  — no constant-velocity shortcut, ever;
* the MD sampling window IS the calibration's calibrated range (outside it
  the answer is legitimately unavailable, so nothing is extrapolated);
* a section only receives points whose trajectory actually lies within
  ``max_line_offset`` of that section's plane — a well 2 km away never
  paints a fake trace on someone else's section.
"""

from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub

DEFAULT_MAX_POINTS = 240
DEFAULT_MAX_LINE_OFFSET = 1.0  # survey line units: within one neighbour bin


@dataclass(frozen=True)
class SectionOverlay:
    """One projected well trace on one section type (display-only)."""

    section: str  # "inline" | "crossline"
    h_values: tuple[float, ...]  # crossline (inline section) / inline (crossline section)
    v_values_twt_ms: tuple[float, ...]

    def as_engine_path(self, label: str, color: str = "#1f6feb") -> dict:
        return {
            "h_values": list(self.h_values),
            "v_values": list(self.v_values_twt_ms),
            "label": label,
            "color": color,
        }


def compute_well_section_overlays(
    hub: CoordinateTransformHub,
    well_id: str,
    *,
    inline_value: float | None = None,
    crossline_value: float | None = None,
    max_points: int = DEFAULT_MAX_POINTS,
    max_line_offset: float = DEFAULT_MAX_LINE_OFFSET,
) -> tuple[dict[str, SectionOverlay], str | None]:
    """Project one well onto the given inline/crossline section positions.

    Returns ``(overlays_by_section, unavailable_reason)`` — exactly one of
    the scientific states: overlays with reason ``None``, or empty overlays
    with an explicit reason. Reasons are stable, prefix-coded strings
    suitable for UI display and tests.
    """
    well_key = str(well_id)
    if well_key not in hub.registered_well_ids():
        return {}, f"well-not-registered:{well_key}"

    calibration = hub.time_depth_calibration(well_key)
    if calibration is None:
        return {}, f"no-calibration:{well_key}"
    md_lo = calibration.pairs[0][0]
    md_hi = calibration.pairs[-1][0]
    if md_hi <= md_lo:
        return {}, f"empty-calibration-range:{well_key}"

    n = max(2, min(int(max_points), 4000))
    mds = [md_lo + (md_hi - md_lo) * i / (n - 1) for i in range(n)]

    inline_pts: list[tuple[float, float]] = []  # (xl, twt) on the inline section
    crossline_pts: list[tuple[float, float]] = []  # (il, twt) on the crossline section
    try:
        for md in mds:
            twt = calibration.md_to_twt(md)
            if twt is None:  # pragma: no cover - window IS the calibrated range
                continue
            x, y, _tvd = hub.well_depth_to_map(well_key, md)
            il, xl = hub.map_to_seismic_xy(x, y)  # geometry only: no z↔TWT guess
            inline_pts.append((float(xl), float(twt)))
            crossline_pts.append((float(il), float(twt)))
    except KeyError:
        return {}, f"well-not-registered:{well_key}"
    except ValueError as exc:
        return {}, f"grid-unavailable:{exc}"

    overlays: dict[str, SectionOverlay] = {}
    if inline_value is not None and inline_pts:
        ils = [pt[0] for pt in crossline_pts]  # il per sample (same order)
        kept = [
            (xl, twt)
            for (xl, twt), il in zip(inline_pts, ils)
            if abs(il - float(inline_value)) <= max_line_offset
        ]
        if kept:
            overlays["inline"] = SectionOverlay(
                section="inline",
                h_values=tuple(p[0] for p in kept),
                v_values_twt_ms=tuple(p[1] for p in kept),
            )
    if crossline_value is not None and crossline_pts:
        xls = [pt[0] for pt in inline_pts]  # xl per sample (same order)
        kept = [
            (il, twt)
            for (il, twt), xl in zip(crossline_pts, xls)
            if abs(xl - float(crossline_value)) <= max_line_offset
        ]
        if kept:
            overlays["crossline"] = SectionOverlay(
                section="crossline",
                h_values=tuple(p[0] for p in kept),
                v_values_twt_ms=tuple(p[1] for p in kept),
            )
    if not overlays:
        return {}, "well-outside-section-window"
    return overlays, None
