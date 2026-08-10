"""Unified single-factor grid result contract.

``FactorGridResult`` is the *single* typed structure produced by every single-factor
interpolation method (IDW, Kriging, 样条/Spline, 方向趋势/Directional, and the vendored
Haiyou constrained-IDW) and consumed by the native renderer / layer model. It replaces
the informal dict convention that previously diverged between the engine
(:func:`geoviz_plots.factor.interpolation.interpolate_factor_grid`, which encodes
non-finite cells as JSON ``None``) and the constrained-IDW adapter
(:func:`paleo_workbench.workflow.constrained_idw_adapter.run_constrained_idw`, which
encodes them as ``NaN``).

Design rules (enforced here):

* **Data only — no style.** Color ramp, range, opacity and contour styling live on the
  *layer*, not on the result. Mutating style must therefore never re-run interpolation.
  This separation is what makes the cache key (data revision) independent of the style
  revision.
* **Canonical nodata = NaN.** Both ``None`` (engine) and ``NaN`` (adapter) inputs are
  normalised to ``NaN`` in a contiguous ``float32`` buffer — the buffer the native
  rasteriser consumes.
* **CRS is explicit, never guessed.** ``crs=None`` means "source XY with no declared
  coordinate reference system"; consumers must not silently treat it as geographic or
  projected.
* **No invented data.** ``variance_grid`` is populated only when the algorithm produces
  one (Kriging). There is no fabricated "uncertainty" field.

This module depends only on NumPy and the standard library so it can be imported,
unit-tested, and consumed by the C++ binding without pulling in PySide6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = ["FactorGridResult", "GridStatistics"]

# Sentinel: the canonical nodata value stored inside ``grid_z`` / ``variance_grid``.
NODATA = float("nan")


@dataclass(frozen=True, slots=True)
class GridStatistics:
    """Summary statistics over the *finite* cells of a factor grid.

    Computed in float64 to avoid accumulation error; stored values are plain Python
    floats so the object is JSON-serialisable via ``dataclasses.asdict``.
    """

    min: float
    max: float
    mean: float
    std: float
    valid_count: int
    total_count: int

    @classmethod
    def from_grid(cls, grid_z: np.ndarray) -> "GridStatistics":
        total = int(grid_z.size)
        finite = np.isfinite(grid_z)
        valid = int(finite.sum())
        if valid == 0:
            return cls(
                min=math.nan,
                max=math.nan,
                mean=math.nan,
                std=math.nan,
                valid_count=0,
                total_count=total,
            )
        values = grid_z[finite].astype(np.float64, copy=False)
        return cls(
            min=float(values.min()),
            max=float(values.max()),
            mean=float(values.mean()),
            std=float(values.std()),
            valid_count=valid,
            total_count=total,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "std": self.std,
            "valid_count": self.valid_count,
            "total_count": self.total_count,
        }


def _to_float32_grid(
    raw: Any, *, height: int, width: int
) -> np.ndarray:
    """Coerce a 2-D grid (lists with ``None``/``NaN`` sentinels, or an ndarray) into a
    contiguous ``float32`` ``(height, width)`` array where non-finite cells are ``NaN``.

    Accepts both legacy encodings: the engine's ``None`` sentinel and the adapter's raw
    ``NaN``. ``None``, ``math.nan`` and non-finite floats all become ``NaN``.
    """
    arr = np.asarray(raw, dtype=np.float32)
    if arr.shape != (height, width):
        # Tolerate a flat list that reshapes cleanly (defensive; both producers emit 2-D).
        try:
            arr = arr.reshape(height, width)
        except ValueError as err:
            raise ValueError(
                f"grid_z shape {arr.shape} does not match expected ({height}, {width})"
            ) from err
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    # Normalise any non-finite value (inf/-inf from upstream included) to NaN, the
    # canonical nodata marker consumed by the native rasteriser.
    arr[~np.isfinite(arr)] = NODATA
    return arr


def _coerce_xy(values: Sequence[float], *, name: str) -> np.ndarray:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1-D coordinate vector, got shape {arr.shape}")
    return arr


@dataclass(slots=True)
class FactorGridResult:
    """Authoritative, renderer-facing single-factor grid result.

    Construct via the ``from_*`` classmethods rather than building the dataclass by
    hand, so that nodata normalisation and shape validation run consistently.
    """

    # --- core grid (canonical) -------------------------------------------------
    grid_z: np.ndarray  # float32, shape (height, width), NaN = nodata
    grid_x: np.ndarray  # float64, shape (width,)  — column coordinates
    grid_y: np.ndarray  # float64, shape (height,) — row coordinates

    # --- identity / provenance -------------------------------------------------
    factor_name: str
    algorithm_id: str  # "idw" | "kriging" | "spline" | "directional" | "constrained_idw"
    algorithm_parameters: dict[str, Any] = field(default_factory=dict)
    crs: str | None = None  # None == source XY, no declared CRS (must not be guessed)
    unit: str | None = None
    generator_version: str | None = None
    source_refs: list[str] = field(default_factory=list)  # catalog asset/version ids
    run_ref: str | None = None  # catalog DataRun id
    created_at: str | None = None  # ISO-8601, optional

    # --- optional algorithm outputs (only when the method actually produces them)
    variance_grid: np.ndarray | None = None  # Kriging variance, float32 (height, width)
    boundary: list[tuple[float, float]] | None = None  # closed domain ring (constrained-IDW)

    # --- cached statistics (set by ``_finalise``) ------------------------------
    statistics: GridStatistics = field(init=False)

    # ----- properties ----------------------------------------------------------
    @property
    def width(self) -> int:
        return int(self.grid_z.shape[1])

    @property
    def height(self) -> int:
        return int(self.grid_z.shape[0])

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """Axis-aligned extent as ``(xmin, ymin, xmax, ymax)`` derived from the axes.

        This is the data extent in the declared ``crs`` (or source XY if unknown); it is
        not a projected bounding box and must not be used to silently mix CRSes.
        """
        xs = self.grid_x
        ys = self.grid_y
        return (
            float(np.min(xs)),
            float(np.min(ys)),
            float(np.max(xs)),
            float(np.max(ys)),
        )

    @property
    def mask(self) -> np.ndarray:
        """Boolean ``(height, width)`` mask: ``True`` where the cell is a valid value."""
        return np.isfinite(self.grid_z)

    @property
    def crs_is_known(self) -> bool:
        return self.crs is not None

    # ----- construction --------------------------------------------------------
    def __post_init__(self) -> None:
        self._finalise()

    def _finalise(self) -> None:
        if self.grid_z.ndim != 2:
            raise ValueError(
                f"grid_z must be 2-D, got shape {self.grid_z.shape}"
            )
        h, w = self.grid_z.shape
        if self.grid_x.shape != (w,):
            raise ValueError(
                f"grid_x length {self.grid_x.shape} must match grid_z width {w}"
            )
        if self.grid_y.shape != (h,):
            raise ValueError(
                f"grid_y length {self.grid_y.shape} must match grid_z height {h}"
            )
        if self.grid_z.dtype != np.float32:
            self.grid_z = np.ascontiguousarray(self.grid_z, dtype=np.float32)
        if self.variance_grid is not None and self.variance_grid.shape != (h, w):
            raise ValueError(
                f"variance_grid shape {self.variance_grid.shape} must match "
                f"grid_z {(h, w)}"
            )
        self.statistics = GridStatistics.from_grid(self.grid_z)

    # ----- public constructors -------------------------------------------------
    @classmethod
    def from_engine_dict(
        cls,
        data: dict[str, Any],
        *,
        factor_name: str,
        crs: str | None = None,
        unit: str | None = None,
        algorithm_id: str | None = None,
        generator_version: str | None = None,
        source_refs: Iterable[str] | None = None,
        run_ref: str | None = None,
        created_at: str | None = None,
    ) -> "FactorGridResult":
        """Build a result from the ``interpolate_factor_grid`` engine dict.

        The engine encodes non-finite cells as JSON ``None``; those are normalised to
        ``NaN`` here. ``algorithm_id`` defaults to ``data["backend"]``.
        """
        grid_x = _coerce_xy(data["grid_x"], name="grid_x")
        grid_y = _coerce_xy(data["grid_y"], name="grid_y")
        grid_z = _to_float32_grid(
            data["grid_z"], height=int(grid_y.size), width=int(grid_x.size)
        )
        algo = algorithm_id or str(data.get("backend", ""))
        params: dict[str, Any] = {
            "r_squared": data.get("r_squared"),
            "grid_label": data.get("grid"),
            "n_points": data.get("n_points"),
        }
        # Method-specific real outputs (pass-through only — never invented).
        variance_grid: np.ndarray | None = None
        if data.get("grid_var") is not None:
            variance_grid = _to_float32_grid(
                data["grid_var"], height=int(grid_y.size), width=int(grid_x.size)
            )
            params["variance_min"] = data.get("variance_min")
            params["variance_max"] = data.get("variance_max")
        for key in ("power", "azimuth_deg", "semi_major", "semi_minor"):
            if data.get(key) is not None:
                params[key] = data.get(key)
        return cls(
            grid_z=grid_z,
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name=factor_name,
            algorithm_id=algo,
            algorithm_parameters=params,
            crs=crs,
            unit=unit,
            generator_version=generator_version,
            source_refs=list(source_refs or []),
            run_ref=run_ref,
            created_at=created_at,
            variance_grid=variance_grid,
        )

    @classmethod
    def from_constrained_idw_dict(
        cls,
        data: dict[str, Any],
        *,
        factor_name: str,
        crs: str | None = None,
        unit: str | None = None,
        generator_version: str | None = None,
        source_refs: Iterable[str] | None = None,
        run_ref: str | None = None,
        created_at: str | None = None,
    ) -> "FactorGridResult":
        """Build a result from the Haiyou constrained-IDW adapter dict.

        The adapter keeps non-finite cells as raw ``NaN`` floats (which serialise to
        non-standard JSON ``NaN``); those pass through the canonical nodata path here.
        The resolved domain ``boundary`` ring and direction/barrier counts are preserved
        as real algorithm outputs.
        """
        grid_x = _coerce_xy(data["grid_x"], name="grid_x")
        grid_y = _coerce_xy(data["grid_y"], name="grid_y")
        grid_z = _to_float32_grid(
            data["grid_z"], height=int(grid_y.size), width=int(grid_x.size)
        )
        raw_boundary = data.get("boundary")
        boundary: list[tuple[float, float]] | None = None
        if raw_boundary:
            boundary = [(float(x), float(y)) for x, y in raw_boundary]
        params: dict[str, Any] = {
            "r_squared": data.get("r_squared"),
            "grid_n": data.get("grid_n"),
            "n_points": data.get("n_points"),
            "n_break_lines": data.get("n_break_lines", 0),
            "n_direction_lines": data.get("n_direction_lines", 0),
        }
        return cls(
            grid_z=grid_z,
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name=factor_name,
            algorithm_id="constrained_idw",
            algorithm_parameters=params,
            crs=crs,
            unit=unit,
            generator_version=generator_version,
            source_refs=list(source_refs or []),
            run_ref=run_ref,
            created_at=created_at,
            boundary=boundary,
        )

    @classmethod
    def from_legacy_task_parameters(
        cls,
        parameters: dict[str, Any],
        *,
        factor_name: str,
        crs: str | None = None,
        unit: str | None = None,
    ) -> "FactorGridResult":
        """Adapter for legacy projects whose ``grid_x/grid_y/grid_z`` live inline in
        ``FactorMapTask.parameters``. Handles both ``None`` and ``NaN`` encodings so old
        projects keep opening without data loss.
        """
        backend = str(parameters.get("interp_backend") or parameters.get("backend") or "")
        algorithm_id = backend or "unknown"
        grid_x = _coerce_xy(parameters["grid_x"], name="grid_x")
        grid_y = _coerce_xy(parameters["grid_y"], name="grid_y")
        grid_z = _to_float32_grid(
            parameters["grid_z"], height=int(grid_y.size), width=int(grid_x.size)
        )
        params = {
            "r_squared": None,
            "grid_label": parameters.get("grid"),
            "n_points": len(parameters.get("sample_points") or []),
            "power": parameters.get("power"),
            "n_break_lines": parameters.get("n_break_lines", 0),
        }
        variance_grid = None
        if parameters.get("grid_var") is not None:
            variance_grid = _to_float32_grid(
                parameters["grid_var"],
                height=int(grid_y.size),
                width=int(grid_x.size),
            )
            params["variance_min"] = parameters.get("variance_min")
            params["variance_max"] = parameters.get("variance_max")
        if parameters.get("azimuth_deg") is not None:
            params["azimuth_deg"] = parameters.get("azimuth_deg")
            params["semi_major"] = parameters.get("semi_major")
            params["semi_minor"] = parameters.get("semi_minor")
        return cls(
            grid_z=grid_z,
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name=factor_name,
            algorithm_id=algorithm_id,
            algorithm_parameters=params,
            crs=crs,
            unit=unit,
            generator_version=None,
            source_refs=[],
            run_ref=None,
            created_at=None,
            variance_grid=variance_grid,
        )

    # ----- serialisation -------------------------------------------------------
    def to_descriptor(self) -> dict[str, Any]:
        """JSON-serialisable *metadata* describing this result.

        Deliberately contains **no grid arrays** — the canonical buffer is a managed
        artifact (catalog INTERMEDIATE/DERIVED version). Persisting huge grids inline in
        ``.paleo.json`` is what this contract replaces.
        """
        return {
            "factor_name": self.factor_name,
            "algorithm_id": self.algorithm_id,
            "algorithm_parameters": self.algorithm_parameters,
            "crs": self.crs,
            "crs_is_known": self.crs_is_known,
            "unit": self.unit,
            "width": self.width,
            "height": self.height,
            "extent": list(self.extent),
            "generator_version": self.generator_version,
            "source_refs": list(self.source_refs),
            "run_ref": self.run_ref,
            "created_at": self.created_at,
            "has_variance_grid": self.variance_grid is not None,
            "has_boundary": self.boundary is not None,
            "statistics": self.statistics.to_dict(),
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        """Backward-compatible dict for any legacy consumer.

        Non-finite cells are emitted as ``None`` (the engine's encoding, which is the
        JSON-safe one) so downstream code and old tests keep working.
        """
        none_encoded = [
            [None if not math.isfinite(float(v)) else float(v) for v in row]
            for row in self.grid_z.tolist()
        ]
        out: dict[str, Any] = {
            "grid_x": [float(v) for v in self.grid_x.tolist()],
            "grid_y": [float(v) for v in self.grid_y.tolist()],
            "grid_z": none_encoded,
            "backend": self.algorithm_id,
            "min": self.statistics.min,
            "max": self.statistics.max,
            "mean": self.statistics.mean,
            "r_squared": self.algorithm_parameters.get("r_squared"),
        }
        if self.variance_grid is not None:
            out["grid_var"] = [
                [None if not math.isfinite(float(v)) else float(v) for v in row]
                for row in self.variance_grid.tolist()
            ]
            out["variance_min"] = self.algorithm_parameters.get("variance_min")
            out["variance_max"] = self.algorithm_parameters.get("variance_max")
        if self.boundary is not None:
            out["boundary"] = [[float(x), float(y)] for x, y in self.boundary]
        return out
