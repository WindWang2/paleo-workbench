"""P1-C — unified geological scene extensions.

VRAM budget wiring, real geometry highlight, and versioned horizon
interpretations as 3D stratal inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")


class TestVramBudgetWiring:
    def test_budget_is_derived_and_bounded(self):
        from paleo_workbench.runtime.resource_budget import (
            ResourceBudget,
            apply_vram_budget,
        )

        small = ResourceBudget.for_total_ram_gb(8.0)
        large = ResourceBudget.for_total_ram_gb(32.0)
        assert small.vram_budget_mb == 512
        assert large.vram_budget_mb == 1024
        assert apply_vram_budget(large) is True
        from geoviz_seismic.vram_cache import VRAM

        assert VRAM.budget_bytes() == 1024 * 1024 * 1024

    def test_main_applies_budget(self):
        """main() wires the budget at boot (source contract)."""
        import inspect

        from paleo_workbench import main as main_module

        source = inspect.getsource(main_module.main)
        assert "apply_vram_budget(active_budget())" in source


class TestStratalFromInterpretations:
    def test_ms_grid_path_matches_dat_semantics(self, tmp_path):
        """The interpretation-grid path and the .dat path must agree on the
        alignment math (same preview sample-index mapping)."""
        import segyio

        segyio = pytest.importorskip("segyio")
        from paleo_workbench.viz.stratal_adapter import (
            build_stratal_grids,
            build_stratal_grids_from_ms_grids,
        )

        class FakeSurvey:
            iline_start = 1
            iline_step = 1
            n_inlines = 8
            xline_start = 1
            xline_step = 1
            n_crosslines = 8
            dt_ms = 4.0
            t0_ms = 0.0

        class FakeRegistration:
            strides = (1, 1, 1)

        class FakeScene:
            survey = FakeSurvey()
            registration = FakeRegistration()

        n_il, n_xl, n_s = 8, 8, 32
        rng = np.random.default_rng(11)
        volume = rng.standard_normal((n_il, n_xl, n_s)).astype(np.float32)
        ms_grid = np.full((n_il, n_xl), 40.0)

        # Write the same horizon as a .dat file (il, xl, twt rows).
        dat = tmp_path / "h.dat"
        lines = []
        for i in range(n_il):
            for j in range(n_xl):
                lines.append(f"{i + 1} {j + 1} 40.0")
        dat.write_text("\n".join(lines), encoding="utf-8")

        via_dat = build_stratal_grids(FakeScene(), volume, dat, dat)
        via_grid = build_stratal_grids_from_ms_grids(FakeScene(), volume, ms_grid, ms_grid)
        assert via_dat is not None and via_grid is not None
        np.testing.assert_allclose(via_dat[0], via_grid[0])
        np.testing.assert_allclose(via_dat[1], via_grid[1])


class TestHighlightGeometry:
    def test_probe_highlight_sets_marker_at_mid_trajectory(self):
        from PySide6.QtCore import QObject

        from paleo_workbench.ui.pages.geological_modeling_3d_page import (
            GeologicalModeling3DPage,
        )

        markers: list[tuple] = []

        class FakeTraj:
            name = "W-1"
            points = np.array(
                [[0.0, 0.0, 0.0], [5.0, 5.0, 5.0], [10.0, 10.0, 10.0]]
            )

        class FakeScene:
            @staticmethod
            def well_trajectories(*, visible_only=False):
                return {"wid": FakeTraj()}

        class FakeHost:
            scene = FakeScene()

        class FakeWidget:
            @staticmethod
            def set_probe_marker(xyz):
                markers.append(tuple(xyz))

        # __new__ on QWidget subclasses is unsafe; test the helper logic
        # through an unbound call on a lightweight stand-in.
        probe = GeologicalModeling3DPage._probe_highlight_well
        holder = type("_Holder", (), {})()
        holder._joint_host = FakeHost()
        holder._joint_widget = FakeWidget()
        assert probe(holder, "W-1") is True
        assert markers == [(5.0, 5.0, 5.0)]
        assert probe(holder, "W-MISSING") is False
        assert markers == [(5.0, 5.0, 5.0)]  # unchanged for unknown wells
