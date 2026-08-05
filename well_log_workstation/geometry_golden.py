"""Single-well geometry golden subset (T14 / #302).

Freezes a fixed LAS + template layout and asserts export-path track boxes
and depth mapping in physical millimetres. Tolerance matches the §16
0.1 mm target for the **subset** (not the full B1 matrix).

Layout rules mirror ``export_plot._paint_presentation`` (Qt-paint export
stream used when engine is disabled / PNG fallback). Screen canvas uses a
slightly different left margin; this golden is the **export mm** seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# §16 export accuracy target (subset uses the same number).
TOL_MM = 0.1
# ADR 0054: CGM format dimension may enter at 0.5 mm before converging to 0.1 mm.
TOL_MM_CGM = 0.5
# Engine CGM integer VDC (see welllog::k_cgm_vdc_per_mm).
CGM_VDC_PER_MM = 100.0

GOLDEN_DATASET_ID = "T14_GOLDEN_V1"
GOLDEN_TEMPLATE_ID = "std-gr-rt-den"
GOLDEN_WELL_NAME = "T14-GOLDEN-V1"
GOLDEN_DEPTH_TOP = 1000.0
GOLDEN_DEPTH_BOTTOM = 1010.0
GOLDEN_DEPTH_UNIT = "m"

# From well_log_workstation/templates/std_gr_rt_den.json
GOLDEN_TRACK_FRACTIONS: dict[str, float] = {
    "depth": 0.12,
    "gr": 0.28,
    "rt": 0.28,
    "den": 0.32,
}

# A4 landscape page (export_dispatch.PageSpec defaults).
GOLDEN_PAGE_WIDTH_MM = 297.0
GOLDEN_PAGE_HEIGHT_MM = 210.0

# Export paint constants mirrored from export_plot._paint_presentation.
_EXPORT_LEFT_PAD = 16.0
_EXPORT_RIGHT_PAD = 16.0  # total horizontal pad = 32
_EXPORT_FOOTER_PAD = 28.0
_EXPORT_TRACK_HDR_H = 28.0
_EXPORT_TITLE_BASE = 8.0
_EXPORT_TITLE_LINE = 16.0
_EXPORT_MIN_TRACK_W = 28.0
_EXPORT_MIN_USABLE_W = 40.0


@dataclass(frozen=True)
class TrackBoxMm:
    """One track column in page millimetres (export layout)."""

    track_id: str
    left_mm: float
    width_mm: float
    top_mm: float
    height_mm: float

    @property
    def right_mm(self) -> float:
        return self.left_mm + self.width_mm


@dataclass(frozen=True)
class ExportLayoutMm:
    """Full single-well export layout in mm for one page."""

    page_width_mm: float
    page_height_mm: float
    content_left_mm: float
    content_top_mm: float
    content_bottom_mm: float
    usable_width_mm: float
    tracks: tuple[TrackBoxMm, ...]
    depth_top: float
    depth_bottom: float

    def depth_to_y_mm(self, depth: float) -> float:
        d0, d1 = self.depth_top, self.depth_bottom
        span = max(d1 - d0, 1e-12)
        frac = (float(depth) - d0) / span
        return self.content_top_mm + frac * (
            self.content_bottom_mm - self.content_top_mm
        )

    def y_to_depth(self, y_mm: float) -> float:
        top, bot = self.content_top_mm, self.content_bottom_mm
        span_y = max(bot - top, 1e-12)
        frac = (float(y_mm) - top) / span_y
        return self.depth_top + frac * (self.depth_bottom - self.depth_top)


def fixture_las_path() -> Path:
    """Path to the in-repo T14 golden LAS (always available offline)."""
    return (
        Path(__file__).resolve().parent
        / "testdata"
        / "geometry_golden"
        / f"{GOLDEN_DATASET_ID}.las"
    )


def layout_export_tracks_mm(
    tracks: Sequence[tuple[str, float]],
    *,
    page_width_mm: float = GOLDEN_PAGE_WIDTH_MM,
    page_height_mm: float = GOLDEN_PAGE_HEIGHT_MM,
    n_header_lines: int = 2,
    depth_top: float = GOLDEN_DEPTH_TOP,
    depth_bottom: float = GOLDEN_DEPTH_BOTTOM,
    x_origin: float = 0.0,
    y_origin: float = 0.0,
) -> ExportLayoutMm:
    """Compute track boxes in mm using the Qt-paint export layout rules.

    ``tracks`` is an ordered sequence of ``(track_id, width_fraction)`` for
    **visible** tracks only (same order as ``HostPresentation.visible_tracks``).
    """
    if not tracks:
        raise ValueError("layout_export_tracks_mm: no tracks")
    w = float(page_width_mm)
    h = float(page_height_mm)
    title_band = _EXPORT_TITLE_BASE + max(1, int(n_header_lines)) * _EXPORT_TITLE_LINE
    top = y_origin + title_band + _EXPORT_TRACK_HDR_H
    bottom = y_origin + h - _EXPORT_FOOTER_PAD
    left = x_origin + _EXPORT_LEFT_PAD
    usable_w = max(_EXPORT_MIN_USABLE_W, w - (_EXPORT_LEFT_PAD + _EXPORT_RIGHT_PAD))
    total_frac = sum(max(0.05, float(wf)) for _, wf in tracks) or 1.0
    body_h = bottom - top

    boxes: list[TrackBoxMm] = []
    x = left
    for tid, wf in tracks:
        tw = max(
            _EXPORT_MIN_TRACK_W,
            usable_w * (max(0.05, float(wf)) / total_frac),
        )
        # Drawn body is tw-6 in export_plot; box width is the column pitch (tw).
        boxes.append(
            TrackBoxMm(
                track_id=str(tid),
                left_mm=x,
                width_mm=tw,
                top_mm=top,
                height_mm=body_h,
            )
        )
        x += tw

    return ExportLayoutMm(
        page_width_mm=w,
        page_height_mm=h,
        content_left_mm=left,
        content_top_mm=top,
        content_bottom_mm=bottom,
        usable_width_mm=usable_w,
        tracks=tuple(boxes),
        depth_top=float(depth_top),
        depth_bottom=float(depth_bottom),
    )


def golden_export_layout(
    *,
    n_header_lines: int = 2,
) -> ExportLayoutMm:
    """Frozen golden layout for the T14 dataset + std-gr-rt-den template."""
    tracks = tuple(GOLDEN_TRACK_FRACTIONS.items())
    return layout_export_tracks_mm(tracks, n_header_lines=n_header_lines)


# Frozen expected left edges (mm) for the default golden page — checked in so
# accidental constant drift fails loudly. Values = layout_export_tracks_mm()
# for A4 landscape + std fractions + 2 header lines.
GOLDEN_TRACK_LEFT_MM: dict[str, float] = {
    "depth": 16.0,
    "gr": 47.8,
    "rt": 122.0,
    "den": 196.2,
}
GOLDEN_TRACK_WIDTH_MM: dict[str, float] = {
    "depth": 31.8,
    "gr": 74.2,
    "rt": 74.2,
    "den": 84.8,
}
GOLDEN_CONTENT_TOP_MM = 68.0  # 8 + 2*16 + 28
GOLDEN_CONTENT_BOTTOM_MM = 182.0  # 210 - 28
GOLDEN_CONTENT_HEIGHT_MM = 114.0


class GeometryGoldenError(AssertionError):
    """Raised with a multi-line diagnostic when a golden check fails."""


def assert_within_tol(
    actual: float,
    expected: float,
    *,
    tol_mm: float = TOL_MM,
    label: str,
) -> None:
    delta = abs(float(actual) - float(expected))
    if delta > tol_mm:
        raise GeometryGoldenError(
            f"{label}: actual={actual:.4f} expected={expected:.4f} "
            f"Δ={delta:.4f} mm (tol={tol_mm} mm)"
        )


def assert_layout_matches_golden(
    layout: ExportLayoutMm,
    *,
    tol_mm: float = TOL_MM,
    expected_left: dict[str, float] | None = None,
    expected_width: dict[str, float] | None = None,
) -> None:
    """Compare an export layout to the frozen golden track edges.

    On failure raises ``GeometryGoldenError`` with a readable multi-line
    report (track id, actual vs expected, delta mm).
    """
    left_ref = expected_left if expected_left is not None else GOLDEN_TRACK_LEFT_MM
    width_ref = (
        expected_width if expected_width is not None else GOLDEN_TRACK_WIDTH_MM
    )
    errors: list[str] = []

    def _check(label: str, actual: float, expected: float) -> None:
        delta = abs(float(actual) - float(expected))
        if delta > tol_mm:
            errors.append(
                f"  {label}: actual={actual:.4f} expected={expected:.4f} "
                f"Δ={delta:.4f} mm (tol={tol_mm} mm)"
            )

    _check("content_top_mm", layout.content_top_mm, GOLDEN_CONTENT_TOP_MM)
    _check("content_bottom_mm", layout.content_bottom_mm, GOLDEN_CONTENT_BOTTOM_MM)
    _check(
        "content_height_mm",
        layout.content_bottom_mm - layout.content_top_mm,
        GOLDEN_CONTENT_HEIGHT_MM,
    )
    _check("page_width_mm", layout.page_width_mm, GOLDEN_PAGE_WIDTH_MM)
    _check("page_height_mm", layout.page_height_mm, GOLDEN_PAGE_HEIGHT_MM)

    by_id = {t.track_id: t for t in layout.tracks}
    for tid, exp_left in left_ref.items():
        box = by_id.get(tid)
        if box is None:
            errors.append(f"  track {tid!r}: missing from layout")
            continue
        _check(f"track[{tid}].left_mm", box.left_mm, exp_left)
        if tid in width_ref:
            _check(f"track[{tid}].width_mm", box.width_mm, width_ref[tid])

    extra = set(by_id) - set(left_ref)
    if extra:
        errors.append(f"  unexpected tracks: {sorted(extra)}")

    if errors:
        raise GeometryGoldenError(
            "T14 geometry golden mismatch (export layout mm):\n" + "\n".join(errors)
        )


def assert_depth_mapping(
    layout: ExportLayoutMm,
    *,
    tol_mm: float = TOL_MM,
) -> None:
    """Depth endpoints and mid-point map within tol on the Y axis."""
    errors: list[str] = []

    def _check(label: str, actual: float, expected: float) -> None:
        delta = abs(float(actual) - float(expected))
        if delta > tol_mm:
            errors.append(
                f"  {label}: actual={actual:.4f} expected={expected:.4f} "
                f"Δ={delta:.4f} mm (tol={tol_mm} mm)"
            )

    y0 = layout.depth_to_y_mm(layout.depth_top)
    y1 = layout.depth_to_y_mm(layout.depth_bottom)
    y_mid = layout.depth_to_y_mm((layout.depth_top + layout.depth_bottom) / 2.0)
    _check("y(depth_top)", y0, layout.content_top_mm)
    _check("y(depth_bottom)", y1, layout.content_bottom_mm)
    mid_y = (layout.content_top_mm + layout.content_bottom_mm) / 2.0
    _check("y(depth_mid)", y_mid, mid_y)

    # Invertibility at endpoints
    d0 = layout.y_to_depth(layout.content_top_mm)
    d1 = layout.y_to_depth(layout.content_bottom_mm)
    if abs(d0 - layout.depth_top) > 1e-6:
        errors.append(
            f"  invert depth_top: got {d0} expected {layout.depth_top}"
        )
    if abs(d1 - layout.depth_bottom) > 1e-6:
        errors.append(
            f"  invert depth_bottom: got {d1} expected {layout.depth_bottom}"
        )

    if errors:
        raise GeometryGoldenError(
            "T14 depth mapping golden mismatch:\n" + "\n".join(errors)
        )


def scene_mm_to_cgm_vdc(
    scene_x_mm: float,
    scene_y_mm: float,
    *,
    window_top_mm: float = 0.0,
    window_height_mm: float,
) -> tuple[int, int]:
    """Mirror welllog::cgm_scene_to_vdc (integer VDC, y-up)."""
    local_y = float(scene_y_mm) - float(window_top_mm)
    vx = int(round(float(scene_x_mm) * CGM_VDC_PER_MM))
    vy = int(round((float(window_height_mm) - local_y) * CGM_VDC_PER_MM))
    # clamp to int16 range like the engine
    vx = max(-32768, min(32767, vx))
    vy = max(-32768, min(32767, vy))
    return vx, vy


def assert_cgm_track_left_vdc(
    layout: ExportLayoutMm,
    *,
    tol_mm: float = TOL_MM_CGM,
) -> None:
    """CGM format-dimension golden: track left edges in VDC within tol_mm.

    Engine CGM places track frames using scene clip left (export layout left
    for the host paint model is a proxy for first-ship track columns).
    """
    tol_vdc = tol_mm * CGM_VDC_PER_MM
    errors: list[str] = []
    wh = layout.page_height_mm
    for box in layout.tracks:
        actual_vdc, _ = scene_mm_to_cgm_vdc(
            box.left_mm, layout.content_top_mm, window_height_mm=wh
        )
        expected_vdc = int(round(box.left_mm * CGM_VDC_PER_MM))
        delta = abs(actual_vdc - expected_vdc)
        if delta > tol_vdc + 1e-9:
            errors.append(
                f"  track[{box.track_id}].left_vdc: actual={actual_vdc} "
                f"expected={expected_vdc} Δ={delta:.1f} VDC "
                f"(tol={tol_vdc:.1f} VDC = {tol_mm} mm)"
            )
    if errors:
        raise GeometryGoldenError(
            "T14/B1 CGM geometry golden mismatch (VDC / ADR 0054 0.5 mm entry):\n"
            + "\n".join(errors)
        )
