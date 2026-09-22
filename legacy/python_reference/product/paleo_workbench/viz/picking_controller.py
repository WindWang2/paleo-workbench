"""Horizon picking controller: engine picks ⇄ versioned interpretation draft.

The engine ``SeismicView`` picks points in survey coordinates (IL, XL, TWT)
and displays them on its own panels. This controller bridges those picks to
the workbench interpretation lifecycle:

* ``sync_picks_into_draft`` — survey picks → sparse undoable writes into the
  draft Z grid (through :meth:`HorizonInterpretationDraft.set_picks`, with
  line interpolation so consecutive picks on a section leave no node gaps);
* ``push_draft_to_panel`` — a reopened version's Z grid samples back into
  survey-coordinate picks so the panels show the loaded interpretation.

Geometry comes from :class:`SurveyGridGeometry`, built from the engine's
volume metadata (iline/xline starts+steps, shape). Without geometry the
controller refuses (returns 0 / does nothing) — it never guesses a mapping.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np

from paleo_workbench.viz.interpretation_draft import HorizonInterpretationDraft

logger = logging.getLogger(__name__)


class SurveyGridGeometry:
    """Inline/crossline numbering ↔ grid index mapping for one volume."""

    def __init__(
        self,
        *,
        il_start: float,
        il_step: float,
        xl_start: float,
        xl_step: float,
        n_il: int,
        n_xl: int,
    ) -> None:
        if il_step == 0.0 or xl_step == 0.0:
            raise ValueError("survey line steps must be non-zero")
        self.il_start = float(il_start)
        self.il_step = float(il_step)
        self.xl_start = float(xl_start)
        self.xl_step = float(xl_step)
        self.n_il = int(n_il)
        self.n_xl = int(n_xl)

    @classmethod
    def from_engine_meta(cls, meta: Any) -> "SurveyGridGeometry | None":
        """Build from the engine's volume meta (pydantic model or mapping)."""
        if meta is None:
            return None
        def field(name: str, default: Any) -> Any:
            if isinstance(meta, dict):
                return meta.get(name, default)
            return getattr(meta, name, default)

        try:
            n_il = int(field("n_inlines", 0) or 0)
            n_xl = int(field("n_crosslines", 0) or 0)
            if not n_il or not n_xl:
                shape = field("shape", None)
                if shape:
                    n_il, n_xl = int(shape[0]), int(shape[1])
            if not n_il or not n_xl:
                return None
            return cls(
                il_start=float(field("iline_start", 0.0)),
                il_step=float(field("iline_step", 1.0) or 1.0),
                xl_start=float(field("xline_start", 0.0)),
                xl_step=float(field("xline_step", 1.0) or 1.0),
                n_il=n_il,
                n_xl=n_xl,
            )
        except (TypeError, ValueError, IndexError):
            return None

    def il_xl_to_rowcol(self, il: float, xl: float) -> tuple[int, int] | None:
        row_f = (float(il) - self.il_start) / self.il_step
        col_f = (float(xl) - self.xl_start) / self.xl_step
        row = int(round(row_f))
        col = int(round(col_f))
        # A pick between grid nodes (fractional line spacing mismatch) is not
        # this grid's node: reject half-way picks instead of snapping them.
        near_node = 0.25
        if abs(row_f - row) > near_node or abs(col_f - col) > near_node:
            return None
        if 0 <= row < self.n_il and 0 <= col < self.n_xl:
            return (row, col)
        return None

    def rowcol_to_il_xl(self, row: int, col: int) -> tuple[float, float]:
        return (
            self.il_start + self.il_step * int(row),
            self.xl_start + self.xl_step * int(col),
        )


class HorizonPickingController:
    """Bridges one seismic panel's picks with one interpretation draft."""

    def __init__(self, panel: Any, draft: HorizonInterpretationDraft) -> None:
        self._panel = panel
        self.draft = draft
        self._grid: SurveyGridGeometry | None = None

    def set_grid(self, grid: SurveyGridGeometry) -> None:
        self._grid = grid

    def grid(self) -> SurveyGridGeometry | None:
        return self._grid

    # ------------------------------------------------------------------
    # panel → draft
    # ------------------------------------------------------------------

    def sync_picks_into_draft(self, picks: Sequence[tuple] | None = None) -> int:
        """Write the panel's survey-coordinate picks into the draft grid.

        Returns the number of grid nodes written (0 when the picks are empty,
        the geometry is missing, or no pick lands inside the grid). The whole
        sync is ONE undoable patch.
        """
        grid = self._grid
        if grid is None:
            logger.debug("picking sync refused: no survey grid geometry")
            return 0
        points = list(picks) if picks is not None else self._picked_points()
        if not points:
            return 0
        rows: list[int] = []
        cols: list[int] = []
        values: list[float] = []
        for point in points:
            try:
                il, xl, twt = float(point[0]), float(point[1]), float(point[2])
            except (TypeError, ValueError, IndexError):
                continue
            cell = grid.il_xl_to_rowcol(il, xl)
            if cell is None:
                continue
            rows.append(cell[0])
            cols.append(cell[1])
            values.append(twt)
        if not rows:
            return 0
        rows_arr = np.asarray(rows, dtype=np.int64)
        cols_arr = np.asarray(cols, dtype=np.int64)
        values_arr = np.asarray(values, dtype=np.float32)
        rows_arr, cols_arr, values_arr = self.interpolate_pick_line(
            rows_arr, cols_arr, values_arr
        )
        # Deduplicate nodes (last pick wins), keeping order stability.
        key = rows_arr * grid.n_xl + cols_arr
        _, unique_indices = np.unique(key[::-1], return_index=True)
        keep = len(key) - 1 - unique_indices
        self.draft.set_picks(rows_arr[keep], cols_arr[keep], values_arr[keep])
        return int(len(keep))

    # ------------------------------------------------------------------
    # draft → panel (reopen path)
    # ------------------------------------------------------------------

    def push_draft_to_panel(self, max_points_per_line: int = 200) -> int:
        """Sample the draft grid back into survey picks for panel display.

        Samples along a coarse row stride so a full-grid horizon does not
        flood the engine's pick overlay; the interpretation itself stays the
        draft grid (picks are only a display projection).
        """
        grid = self._grid
        refresh = getattr(self._panel, "refresh_pick_overlay", None)
        if grid is None or not callable(refresh):
            return 0
        z = self.draft.working_z()
        n_il, n_xl = z.shape
        row_stride = max(1, n_il // max(1, min(max_points_per_line, n_il)))
        col_stride = max(1, n_xl // max(1, min(max_points_per_line, n_xl)))
        points: list[tuple[float, float, float]] = []
        for row in range(0, n_il, row_stride):
            for col in range(0, n_xl, col_stride):
                value = float(z[row, col])
                if not np.isfinite(value):
                    continue
                il, xl = grid.rowcol_to_il_xl(row, col)
                points.append((il, xl, value))
        refresh(points)
        return len(points)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _picked_points(self) -> list[tuple]:
        getter = getattr(self._panel, "picked_points", None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:
                logger.debug("picked_points() failed", exc_info=True)
        return []

    @staticmethod
    def interpolate_pick_line(
        rows: np.ndarray, cols: np.ndarray, values: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Fill consecutive pick pairs with integer-node lines (Bresenham-lite).

        Picks arrive in pick order; each consecutive pair on the same
        inline row OR crossline column is densified so the written nodes form
        a continuous line. Pairs offset in BOTH axes stay as-is (the pick
        line is diagonal across the grid — honoring only orthogonal sections
        keeps the interpolation faithful to what the interpreter picked).
        """
        if len(rows) < 2:
            return rows, cols, values
        out_rows: list[int] = []
        out_cols: list[int] = []
        out_values: list[float] = []
        for i in range(len(rows) - 1):
            r0, c0, v0 = int(rows[i]), int(cols[i]), float(values[i])
            r1, c1, v1 = int(rows[i + 1]), int(cols[i + 1]), float(values[i + 1])
            out_rows.append(r0)
            out_cols.append(c0)
            out_values.append(v0)
            steps = 0
            if r0 == r1 and c0 != c1:
                steps = abs(c1 - c0)
            elif c0 == c1 and r0 != r1:
                steps = abs(r1 - r0)
            if steps > 0:
                for s in range(1, steps):
                    frac = s / steps
                    out_rows.append(int(round(r0 + (r1 - r0) * frac)))
                    out_cols.append(int(round(c0 + (c1 - c0) * frac)))
                    out_values.append(v0 + (v1 - v0) * frac)
        out_rows.append(int(rows[-1]))
        out_cols.append(int(cols[-1]))
        out_values.append(float(values[-1]))
        return (
            np.asarray(out_rows, dtype=np.int64),
            np.asarray(out_cols, dtype=np.int64),
            np.asarray(out_values, dtype=np.float32),
        )
