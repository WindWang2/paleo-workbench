"""P1-B — horizon picking → interpretation lifecycle closure.

The engine's SeismicView already picks points in survey coordinates; the
workbench side must turn them into a versioned interpretation: sparse
undoable writes into the draft Z grid, seed/reload round-trips, and a UI
controller bridging panel picks to the interpretation lifecycle.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.viz.interpretation_draft import HorizonInterpretationDraft
from paleo_workbench.viz.picking_controller import (
    HorizonPickingController,
    SurveyGridGeometry,
)


@pytest.fixture()
def draft() -> HorizonInterpretationDraft:
    rng = np.random.default_rng(42)
    z = rng.uniform(1000.0, 1100.0, size=(20, 30)).astype(np.float32)
    return HorizonInterpretationDraft(
        interpretation_id="interp_test",
        horizon_key="H1",
        name="H1",
        baseline_z=z,
        vertical_domain="time",
        crs=None,
    )


class TestSurveyGridGeometry:
    def test_maps_survey_numbers_to_grid_indices(self):
        grid = SurveyGridGeometry(
            il_start=100, il_step=2, xl_start=200, xl_step=1, n_il=20, n_xl=30
        )
        row, col = grid.il_xl_to_rowcol(104, 203)
        assert (row, col) == (2, 3)
        il, xl = grid.rowcol_to_il_xl(0, 0)
        assert (il, xl) == (100, 200)

    def test_out_of_range_is_none(self):
        grid = SurveyGridGeometry(
            il_start=100, il_step=2, xl_start=200, xl_step=1, n_il=20, n_xl=30
        )
        assert grid.il_xl_to_rowcol(300, 200) is None
        assert grid.il_xl_to_rowcol(99, 200) is None

    def test_from_engine_meta(self):
        meta = {
            "iline_start": 100.0, "iline_step": 2.0,
            "xline_start": 200.0, "xline_step": 1.0,
            "shape": (20, 30, 400),
        }
        grid = SurveyGridGeometry.from_engine_meta(meta)
        assert grid.n_il == 20 and grid.n_xl == 30
        assert grid.il_xl_to_rowcol(100, 200) == (0, 0)


class TestDraftPicks:
    def test_set_picks_writes_z_and_undo_restores(self, draft):
        original = draft.working_z().copy()
        rows = np.array([0, 5, 10])
        cols = np.array([0, 7, 12])
        values = np.array([1020.0, 1030.0, 1040.0], dtype=np.float32)
        draft.set_picks(rows, cols, values)
        z = draft.working_z()
        assert z[0, 0] == pytest.approx(1020.0)
        assert z[5, 7] == pytest.approx(1030.0)
        assert z[10, 12] == pytest.approx(1040.0)
        assert draft.refresh_status() == "dirty"
        assert draft.can_undo()
        draft.undo()
        np.testing.assert_allclose(draft.working_z(), original)
        assert draft.refresh_status() == "clean"

    def test_pick_indices_outside_grid_are_rejected(self, draft):
        with pytest.raises(IndexError):
            draft.set_picks(
                np.array([99]), np.array([0]), np.array([1.0], dtype=np.float32)
            )

    def test_interpolate_pick_line_fills_between_picks(self, draft):
        # Two picks on the same inline: Bresenham-style line fill along the
        # crossline axis must write every crossed node (no gaps in the pick).
        rows = np.array([5, 5])
        cols = np.array([2, 10])
        values = np.array([1000.0, 1016.0], dtype=np.float32)
        rows_f, cols_f, values_f = HorizonPickingController.interpolate_pick_line(
            rows, cols, values
        )
        assert len(rows_f) == 9
        np.testing.assert_allclose(values_f, np.linspace(1000.0, 1016.0, 9))


class TestPickingController:
    def _panel(self):
        from PySide6.QtCore import QObject, Signal

        class FakePanel(QObject):
            picks_changed = Signal(list)

            def __init__(self):
                super().__init__()
                self.points = []

            def picked_points(self):
                return list(self.points)

            def refresh_pick_overlay(self, points):
                self.points = list(points)

            def volume_shape(self):
                return (20, 30, 400)

        return FakePanel()

    def test_picks_flow_into_draft(self, draft):
        panel = self._panel()
        controller = HorizonPickingController(panel, draft)
        controller.set_grid(SurveyGridGeometry(
            il_start=100, il_step=2, xl_start=200, xl_step=1, n_il=20, n_xl=30
        ))
        panel.points = [(100.0, 200.0, 1050.0), (104.0, 203.0, 1060.0)]
        controller.sync_picks_into_draft()
        z = draft.working_z()
        assert z[0, 0] == pytest.approx(1050.0)
        assert z[2, 3] == pytest.approx(1060.0)
        assert draft.refresh_status() == "dirty"

    def test_reload_pushes_version_z_back_to_panel(self, draft):
        panel = self._panel()
        controller = HorizonPickingController(panel, draft)
        controller.set_grid(SurveyGridGeometry(
            il_start=100, il_step=2, xl_start=200, xl_step=1, n_il=20, n_xl=30
        ))
        # Simulate a loaded version: every node carries a pick in row 0.
        z = draft.working_z()
        controller.push_draft_to_panel(max_points_per_line=3)
        # push_draft_to_panel samples the grid back into survey coordinates
        assert panel.points
        il, xl, twt = panel.points[0]
        assert il == 100 and xl == 200
        assert twt == pytest.approx(float(z[0, 0]), abs=1e-3)

    def test_missing_grid_refuses(self, draft):
        panel = self._panel()
        controller = HorizonPickingController(panel, draft)
        panel.points = [(100.0, 200.0, 1050.0)]
        assert controller.sync_picks_into_draft() == 0
