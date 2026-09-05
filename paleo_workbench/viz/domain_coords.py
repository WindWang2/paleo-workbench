"""Typed coordinate/domain contract V2 (linked-interpretation L1).

Every cross-domain value carries its domain (MD/TVD/TVDSS, TWT, map XY),
its unit (m/ft for lengths, ms for TWT) and — where a conversion needs an
authority — the conversion result names that authority (time-depth
calibration, bin-grid geometry, or an *explicit* velocity assumption).

Fail-closed rules (mirroring ``TimeDepthCalibration``):

* depth↔time conversions REQUIRE a calibration; there is no constant-velocity
  fallback on this path. An explicit velocity assumption exists only as
  :class:`VelocityAssumption`, must be constructed deliberately and marks
  every result it produces as approximate;
* unit conversion happens only through declared factors (``m`` ↔ ``ft``);
* CRS handling is honest: a :class:`MapPoint` carries its CRS tag, and a
  conversion between two differently-tagged points is refused
  (``CRS_MISMATCH``) instead of silently treating coordinates as equal.

This module is the typed front door. The legacy tuple API on
:class:`~paleo_workbench.viz.coordinate_hub.CoordinateTransformHub` keeps
working for existing callers, but new code goes through here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)

# Exact definition of the foot (international yard and pound agreement).
FT_TO_M = 0.3048


class DepthDomain(str, Enum):
    """Well depth domains. TWT is NOT a depth domain (see TwtCoordinate)."""

    MD = "MD"
    TVD = "TVD"
    TVDSS = "TVDSS"


class LengthUnit(str, Enum):
    M = "m"
    FT = "ft"


class ConversionFailure(str, Enum):
    """Machine-readable reason codes for unavailable conversions."""

    UNKNOWN_WELL = "unknown_well"
    NO_CALIBRATION = "no_calibration"
    OUT_OF_CALIBRATION_RANGE = "out_of_calibration_range"
    NO_TRAJECTORY = "no_trajectory"
    CRS_MISMATCH = "crs_mismatch"
    CRS_UNKNOWN = "crs_unknown"
    DEGENERATE_GRID = "degenerate_grid"
    OUT_OF_GRID = "out_of_grid"
    VELOCITY_ASSUMPTION_REQUIRED = "velocity_assumption_required"
    INVALID_INPUT = "invalid_input"
    NOT_IMPLEMENTED = "not_implemented"


T = TypeVar("T")


def _as_length_unit(unit: "LengthUnit | str") -> LengthUnit:
    """Normalize a unit argument; accepts a member or its value ('m'/'ft').

    ``str(member)`` on a str-mixin enum is the MEMBER repr in Python ≥3.12,
    so the string path must only be used for caller-supplied values.
    """
    if isinstance(unit, LengthUnit):
        return unit
    return LengthUnit(str(unit))


@dataclass(frozen=True)
class ConversionOutcome(Generic[T]):
    """Result of one cross-domain conversion.

    ``ok`` is the single truth: when False, ``value`` is None and
    ``reason`` carries the :class:`ConversionFailure` code with a human
    readable ``detail``. When True, ``authority`` names what authorized the
    conversion (``"time-depth:checkshot:<asset>"``, ``"bin-grid-geometry"``,
    ``"velocity-assumption:2000 m/s"`` …) so provenance travels with the
    number.
    """

    value: T | None = None
    ok: bool = False
    authority: str | None = None
    reason: ConversionFailure | None = None
    detail: str | None = None

    @classmethod
    def available(cls, value: T, *, authority: str) -> "ConversionOutcome[T]":
        return cls(value=value, ok=True, authority=authority)

    @classmethod
    def unavailable(
        cls, reason: ConversionFailure, detail: str
    ) -> "ConversionOutcome[T]":
        return cls(value=None, ok=False, reason=reason, detail=detail)


@dataclass(frozen=True)
class DepthCoordinate:
    """A well depth with an explicit domain and unit.

    The stored value is canonicalized to meters; ``unit`` records what the
    source declared so display/round-tripping stay faithful.
    """

    value_m: float
    domain: DepthDomain
    unit: LengthUnit = LengthUnit.M
    source_unit_value: float | None = None

    @classmethod
    def from_source(
        cls, value: float, domain: DepthDomain, unit: LengthUnit | str = LengthUnit.M
    ) -> "DepthCoordinate":
        unit = _as_length_unit(unit)
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"depth value must be finite, got {value}")
        if unit is LengthUnit.FT:
            return cls(
                value_m=value * FT_TO_M,
                domain=domain,
                unit=unit,
                source_unit_value=value,
            )
        return cls(value_m=value, domain=domain, unit=unit, source_unit_value=value)

    def in_unit(self, unit: LengthUnit | str) -> float:
        unit = _as_length_unit(unit)
        if unit is LengthUnit.M:
            return self.value_m
        return self.value_m / FT_TO_M

    def describe(self) -> str:
        return f"{self.value_m:.3f} m {self.domain.value}"


@dataclass(frozen=True)
class TwtCoordinate:
    """Two-way time in milliseconds (seismic vertical axis)."""

    value_ms: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value_ms):
            raise ValueError(f"TWT must be finite, got {self.value_ms}")

    def in_seconds(self) -> float:
        return self.value_ms / 1000.0


@dataclass(frozen=True)
class MapPoint:
    """A map-space position with an explicit CRS tag.

    ``crs`` is an identifier string (``"EPSG:32650"``, WKT, or a project
    CRS name). ``None`` means "unlabelled" — legal for project-local
    geometry, but strict conversions may refuse to mix it with labelled
    points.
    """

    x: float
    y: float
    crs: str | None = None


@dataclass(frozen=True)
class SeismicPosition:
    """A seismic bin-grid location (inline/crossline numbers)."""

    inline: int
    crossline: int


@dataclass(frozen=True)
class SeismicCursorPosition:
    """Inline/crossline plus a vertical time — what a seismic pick gives."""

    inline: int
    crossline: int
    twt: TwtCoordinate

    @classmethod
    def from_tuple(cls, cursor: tuple[int, int, float]) -> "SeismicCursorPosition":
        il, xl, twt = cursor
        return cls(
            inline=int(il), crossline=int(xl), twt=TwtCoordinate(float(twt))
        )

    def to_tuple(self) -> tuple[int, int, float]:
        return (self.inline, self.crossline, self.twt.value_ms)


@dataclass(frozen=True)
class CalibrationIdentity:
    """Stable identity of a time-depth calibration authority.

    ``version_id`` is the catalog DataVersion id when the calibration was
    saved through the interpretation lifecycle; ``fingerprint`` is the
    scientific fingerprint of the calibration artifact.
    """

    well_id: str
    provenance: str
    version_id: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class VelocityAssumption:
    """An EXPLICIT constant-velocity assumption (display/approximate only).

    Constructing one is a deliberate act; conversions made under it are
    always reported with ``authority="velocity-assumption:<v> m/s"`` and
    must never be presented as calibrated depth/time.
    """

    velocity_m_per_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.velocity_m_per_s) or self.velocity_m_per_s <= 0.0:
            raise ValueError(
                f"velocity must be a positive finite number, got {self.velocity_m_per_s}"
            )

    def twt_ms_to_depth_m(self, twt: TwtCoordinate) -> float:
        return twt.in_seconds() * self.velocity_m_per_s / 2.0

    def depth_m_to_twt_ms(self, depth_m: float) -> float:
        return (2.0 * float(depth_m) / self.velocity_m_per_s) * 1000.0

    @property
    def authority(self) -> str:
        return f"velocity-assumption:{self.velocity_m_per_s:g} m/s"


@dataclass(frozen=True)
class WellMapPosition:
    """Resolved well position in map space: XY plus TVD at that MD."""

    point: MapPoint
    tvd_m: float


def calibration_identity(cal: TimeDepthCalibration) -> CalibrationIdentity:
    return CalibrationIdentity(
        well_id=cal.well_id,
        provenance=cal.provenance,
        version_id=getattr(cal, "version_id", None),
        fingerprint=getattr(cal, "fingerprint", None),
    )


# ---------------------------------------------------------------------------
# Typed conversions (single front door for scientific routing)
# ---------------------------------------------------------------------------


class DomainCoordinationService:
    """Typed conversion facade over one :class:`CoordinateTransformHub`.

    One service instance per hub (the app has exactly one hub). All methods
    return :class:`ConversionOutcome`; none ever raises for missing
    authorities — refusing is data, not an exception. Invalid *inputs*
    (non-finite numbers, wrong types) raise as programming errors.
    """

    def __init__(self, hub: CoordinateTransformHub, *, project_crs: str | None = None):
        self._hub = hub
        self._project_crs = project_crs

    @property
    def hub(self) -> CoordinateTransformHub:
        return self._hub

    @property
    def project_crs(self) -> str | None:
        return self._project_crs

    def set_project_crs(self, crs: str | None) -> None:
        self._project_crs = crs

    # -- well registry ------------------------------------------------------

    def known_wells(self) -> tuple[str, ...]:
        return self._hub.registered_well_ids()

    # -- depth (MD) → map ---------------------------------------------------

    def well_md_to_map(
        self, well_id: str, md: DepthCoordinate
    ) -> ConversionOutcome[WellMapPosition]:
        """MD (any declared unit) → map XY + TVD (meters).

        Trajectory geometry is the authority; the TWT domain is not touched
        here (see :meth:`well_md_to_seismic`).
        """
        if md.domain is not DepthDomain.MD:
            return ConversionOutcome.unavailable(
                ConversionFailure.INVALID_INPUT,
                f"expected MD coordinate, got {md.domain.value}",
            )
        try:
            x, y, tvd = self._hub.well_depth_to_map(well_id, md.value_m)
        except KeyError:
            return ConversionOutcome.unavailable(
                ConversionFailure.UNKNOWN_WELL,
                f"well {well_id!r} is not registered in the coordinate hub",
            )
        return ConversionOutcome.available(
            WellMapPosition(
                point=MapPoint(float(x), float(y), self._project_crs), tvd_m=float(tvd)
            ),
            authority="well-trajectory-geometry",
        )

    def well_md_to_tvdss(
        self, well_id: str, md: DepthCoordinate
    ) -> ConversionOutcome[DepthCoordinate]:
        try:
            tvdss = self._hub.well_depth_to_tvdss(well_id, md.value_m)
        except KeyError:
            return ConversionOutcome.unavailable(
                ConversionFailure.UNKNOWN_WELL,
                f"well {well_id!r} is not registered in the coordinate hub",
            )
        return ConversionOutcome.available(
            DepthCoordinate.from_source(tvdss, DepthDomain.TVDSS, LengthUnit.M),
            authority=f"kb-elevation:{well_id}",
        )

    # -- depth (MD) ↔ TWT: calibration-gated, fail-closed --------------------

    def well_md_to_twt(
        self, well_id: str, md: DepthCoordinate
    ) -> ConversionOutcome[TwtCoordinate]:
        cal = self._hub.time_depth_calibration(well_id)
        if cal is None:
            return ConversionOutcome.unavailable(
                ConversionFailure.NO_CALIBRATION,
                f"well {well_id!r} has no time-depth calibration; refusing to guess",
            )
        twt = cal.md_to_twt(md.value_m)
        if twt is None:
            return ConversionOutcome.unavailable(
                ConversionFailure.OUT_OF_CALIBRATION_RANGE,
                f"MD {md.value_m:.2f} m outside calibrated range "
                f"[{cal.pairs[0][0]:.2f}, {cal.pairs[-1][0]:.2f}] m "
                f"({cal.provenance})",
            )
        return ConversionOutcome.available(
            TwtCoordinate(float(twt)), authority=f"time-depth:{cal.provenance}"
        )

    def twt_to_well_md(
        self, well_id: str, twt: TwtCoordinate
    ) -> ConversionOutcome[DepthCoordinate]:
        cal = self._hub.time_depth_calibration(well_id)
        if cal is None:
            return ConversionOutcome.unavailable(
                ConversionFailure.NO_CALIBRATION,
                f"well {well_id!r} has no time-depth calibration; refusing to guess",
            )
        md = cal.twt_to_md(twt.value_ms)
        if md is None:
            return ConversionOutcome.unavailable(
                ConversionFailure.OUT_OF_CALIBRATION_RANGE,
                f"TWT {twt.value_ms:.1f} ms outside calibrated range "
                f"[{cal.pairs[0][1]:.1f}, {cal.pairs[-1][1]:.1f}] ms "
                f"({cal.provenance})",
            )
        return ConversionOutcome.available(
            DepthCoordinate.from_source(md, DepthDomain.MD, LengthUnit.M),
            authority=f"time-depth:{cal.provenance}",
        )

    def calibration_for(self, well_id: str) -> CalibrationIdentity | None:
        cal = self._hub.time_depth_calibration(well_id)
        return calibration_identity(cal) if cal is not None else None

    # -- well → seismic: geometry always, time only via calibration ----------

    def well_md_to_seismic(
        self, well_id: str, md: DepthCoordinate
    ) -> ConversionOutcome[SeismicCursorPosition]:
        """Well MD → (IL, XL, TWT).

        IL/XL come from trajectory geometry; the TWT exists ONLY through the
        well's calibration — no calibration or out-of-range MD refuses the
        whole conversion (fail-closed), never a velocity guess.
        """
        twt_out = self.well_md_to_twt(well_id, md)
        if not twt_out.ok:
            return ConversionOutcome.unavailable(twt_out.reason, twt_out.detail)  # type: ignore[arg-type]
        pos_out = self.well_md_to_map(well_id, md)
        if not pos_out.ok:
            return ConversionOutcome.unavailable(pos_out.reason, pos_out.detail)  # type: ignore[arg-type]
        grid_out = self.map_to_seismic_xy(pos_out.value.point)  # type: ignore[union-attr]
        if not grid_out.ok:
            return ConversionOutcome.unavailable(grid_out.reason, grid_out.detail)  # type: ignore[arg-type]
        return ConversionOutcome.available(
            SeismicCursorPosition(
                inline=grid_out.value.inline,  # type: ignore[union-attr]
                crossline=grid_out.value.crossline,  # type: ignore[union-attr]
                twt=twt_out.value,  # type: ignore[union-attr]
            ),
            authority=f"time-depth:{self._cal_provenance(well_id)}",
        )

    def _cal_provenance(self, well_id: str) -> str:
        cal = self._hub.time_depth_calibration(well_id)
        return cal.provenance if cal is not None else "unknown"

    # -- map ↔ seismic bin grid: pure geometry --------------------------------

    def map_to_seismic_xy(
        self, point: MapPoint
    ) -> ConversionOutcome[SeismicPosition]:
        """Map XY → nearest (inline, crossline). Pure bin-grid geometry."""
        if point.crs is not None and self._project_crs is not None:
            if str(point.crs).strip() != str(self._project_crs).strip():
                return ConversionOutcome.unavailable(
                    ConversionFailure.CRS_MISMATCH,
                    f"point CRS {point.crs!r} differs from project CRS "
                    f"{self._project_crs!r}; reproject before converting",
                )
        try:
            il, xl = self._hub.map_to_seismic_xy(float(point.x), float(point.y))
        except ValueError as exc:
            return ConversionOutcome.unavailable(
                ConversionFailure.DEGENERATE_GRID, str(exc)
            )
        return ConversionOutcome.available(
            SeismicPosition(inline=int(il), crossline=int(xl)),
            authority="bin-grid-geometry",
        )

    def seismic_to_map_xy(
        self, position: SeismicPosition
    ) -> ConversionOutcome[MapPoint]:
        """(inline, crossline) → map XY. Pure bin-grid geometry."""
        try:
            x, y = self._hub.seismic_to_map_xy(int(position.inline), int(position.crossline))
        except ValueError as exc:
            return ConversionOutcome.unavailable(
                ConversionFailure.DEGENERATE_GRID, str(exc)
            )
        return ConversionOutcome.available(
            MapPoint(float(x), float(y), self._project_crs),
            authority="bin-grid-geometry",
        )

    def seismic_cursor_to_map(
        self, cursor: SeismicCursorPosition
    ) -> ConversionOutcome[MapPoint]:
        """Seismic cursor → map XY. The TWT is deliberately DROPPED: turning
        it into a depth needs a velocity authority nobody has on this path
        (see :meth:`seismic_twt_to_depth`)."""
        return self.seismic_to_map_xy(
            SeismicPosition(inline=cursor.inline, crossline=cursor.crossline)
        )

    # -- TWT → depth: only under explicit authorities --------------------------

    def seismic_twt_to_depth(
        self, twt: TwtCoordinate, *, assumption: VelocityAssumption
    ) -> ConversionOutcome[DepthCoordinate]:
        """TWT → depth under an explicit velocity assumption (approximate).

        This is the ONLY sanctioned constant-velocity path, and it exists so
        display code can say "≈ depth at 2000 m/s" — never to masquerade as
        a calibrated depth.
        """
        return ConversionOutcome.available(
            DepthCoordinate.from_source(
                assumption.twt_ms_to_depth_m(twt), DepthDomain.TVD, LengthUnit.M
            ),
            authority=assumption.authority,
        )

    def seismic_twt_to_well_md(
        self, well_id: str, twt: TwtCoordinate
    ) -> ConversionOutcome[DepthCoordinate]:
        """Seismic TWT → well MD through THAT well's calibration."""
        return self.twt_to_well_md(well_id, twt)

    # -- nearest well ----------------------------------------------------------

    def nearest_well(
        self, point: MapPoint, *, max_radius_m: float = 50.0
    ) -> ConversionOutcome[str]:
        well_id = self._hub.map_to_well(
            float(point.x), float(point.y), max_radius=max_radius_m
        )
        if well_id is None:
            return ConversionOutcome.unavailable(
                ConversionFailure.NO_TRAJECTORY,
                f"no registered well within {max_radius_m:g} m of "
                f"({point.x:.1f}, {point.y:.1f})",
            )
        return ConversionOutcome.available(
            well_id, authority="nearest-well-geometry"
        )
