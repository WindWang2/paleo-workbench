"""V6 §3 — unit-dependent consumers must not treat unknown as meters.

Covers: correlation tops overlay placement, engine adapter unit envelope,
well-tie array building, and the well-log canvas cursor gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

pytest.importorskip("PySide6")


# ---------------------------------------------------------------------------
# Correlation tops overlay placement
# ---------------------------------------------------------------------------


@dataclass
class _FakeLogData:
    well_name: str = "W-1"
    depth_unit: str | None = None
    markers: list = field(default_factory=list)


@pytest.fixture()
def md_top_rows(monkeypatch):
    rows = [
        {"id": "t1", "marker": "M1", "depth": 1000.0, "depth_domain": "MD"},
        {"id": "t2", "marker": "M2", "depth": 1100.0, "depth_domain": "MD"},
    ]
    import paleo_workbench.workflow.correlation_overlay as overlay

    monkeypatch.setattr(
        overlay, "formation_tops_overlay_for_well", lambda *a, **k: list(rows)
    )
    return rows


class TestTopsOverlayUnitGate:
    def test_meter_axis_places_meters_directly(self, md_top_rows):
        from paleo_workbench.workflow.correlation_overlay import (
            apply_correlation_tops_to_well_log_data,
        )

        data = _FakeLogData(depth_unit="m")
        wrapped = apply_correlation_tops_to_well_log_data(data, None)
        markers = list(getattr(wrapped, "markers", []))
        assert [m.depth for m in markers] == [1000.0, 1100.0]

    def test_foot_axis_converts_meters_to_feet(self, md_top_rows):
        from paleo_workbench.workflow.correlation_overlay import (
            apply_correlation_tops_to_well_log_data,
        )
        from paleo_workbench.workflow.curve_operations import conversion_factor

        data = _FakeLogData(depth_unit="ft")
        wrapped = apply_correlation_tops_to_well_log_data(data, None)
        markers = list(getattr(wrapped, "markers", []))
        factor = conversion_factor("m", "ft")
        np.testing.assert_allclose(
            sorted(m.depth for m in markers), sorted([1000.0 * factor, 1100.0 * factor])
        )

    def test_unknown_axis_unit_refuses_placement(self, md_top_rows):
        """V6 P0-3: an undeclared unit must not place meter tops raw — the
        ×3.28 misplacement is exactly what refusal prevents."""
        from paleo_workbench.workflow.correlation_overlay import (
            apply_correlation_tops_to_well_log_data,
        )

        data = _FakeLogData(depth_unit=None)
        wrapped = apply_correlation_tops_to_well_log_data(data, None)
        markers = list(getattr(wrapped, "markers", []))
        assert markers == [], "unknown unit must skip top placement"

    def test_bare_document_without_unit_attr_refuses(self, md_top_rows):
        from paleo_workbench.workflow.correlation_overlay import (
            apply_correlation_tops_to_well_log_data,
        )

        @dataclass
        class Bare:
            well_name: str = "W-1"
            markers: list = field(default_factory=list)

        wrapped = apply_correlation_tops_to_well_log_data(Bare(), None)
        assert list(getattr(wrapped, "markers", [])) == []


# ---------------------------------------------------------------------------
# Engine adapter unit envelope
# ---------------------------------------------------------------------------


class TestEngineAdapterUnitEnvelope:
    def _sample_well(self):
        from geoviz_well_log.models import CurveData, WellLogData

        depth = np.arange(1000.0, 1010.0, 0.5).tolist()
        return WellLogData(
            well_name="W-1",
            top_depth=1000.0,
            bottom_depth=1009.5,
            curves=[
                CurveData(
                    name="GR",
                    unit="gAPI",
                    depth=depth,
                    values=(60.0 + np.arange(len(depth))).tolist(),
                    display_range=(0.0, 150.0),
                )
            ],
        )

    def test_unknown_unit_is_flagged_not_silently_meters(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter
        from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

        plan = adapter.adapt_well_log_data(
            WellLogDataWithDepthUnit(self._sample_well(), None, depth_unit_declared=False)
        )
        # The engine bridge contract still requires a non-empty unit token
        # for rendering; the honesty lives in the plan/snapshot metadata.
        assert plan.primary.depth_unit in ("m", "ft")  # bridge-compatible label
        assert plan.primary.depth_unit_declared is False
        assert any("depth-unit" in d for d in plan.diagnostics)

    def test_declared_ft_passes_through(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter
        from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

        plan = adapter.adapt_well_log_data(
            WellLogDataWithDepthUnit(self._sample_well(), "ft", depth_unit_declared=True)
        )
        assert plan.primary.depth_unit == "ft"
        assert plan.primary.depth_unit_declared is True
        assert not any("depth-unit" in d for d in plan.diagnostics)

    def test_parity_snapshot_carries_declared_flag(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter
        from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

        snap = adapter.parity_snapshot(
            WellLogDataWithDepthUnit(self._sample_well(), None, depth_unit_declared=False)
        )
        assert snap["curves"][0]["depth_unit_declared"] is False


# ---------------------------------------------------------------------------
# Well-tie synthetic arrays: unit-dependent integration
# ---------------------------------------------------------------------------


class TestWellTieUnitGate:
    def _log(self, unit: str | None):
        from geoviz_well_log.models import CurveData, WellLogData

        depth = np.arange(1000.0, 1100.0, 0.5).tolist()
        sonic = np.full(len(depth), 250.0).tolist()
        data = WellLogData(
            well_name="W-tie",
            top_depth=1000.0,
            bottom_depth=1099.5,
            curves=[
                CurveData(
                    name="DT",
                    unit="us/m",
                    depth=depth,
                    values=sonic,
                    display_range=(100.0, 400.0),
                ),
            ],
        )
        if unit is not None:
            from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

            return WellLogDataWithDepthUnit(data, unit, depth_unit_declared=True)
        return data

    def test_unknown_unit_refuses_synthetic_tie(self):
        """Sonic integration over depth is unit-defined; unknown → None."""
        from paleo_workbench.viz.hosts.well_tie_host import build_tie_arrays

        assert build_tie_arrays(self._log(None)) is None

    def test_bare_log_without_wrapper_is_unknown(self):
        from paleo_workbench.viz.hosts.well_tie_host import build_tie_arrays

        # A bare WellLogData has no unit envelope at all → unknown → refuse
        assert build_tie_arrays(self._log(None)) is None

    def test_meter_log_still_builds(self):
        from paleo_workbench.viz.hosts.well_tie_host import build_tie_arrays

        arrays = build_tie_arrays(self._log("m"))
        assert arrays is not None and arrays[0].size >= 2


# ---------------------------------------------------------------------------
# Canvas cursor gate
# ---------------------------------------------------------------------------


class TestCursorUnitGate:
    def test_unknown_unit_is_not_meters(self):
        from paleo_workbench.workflow.well_science import classify_depth_unit

        # The pure classification the cursor gate consumes: unknown never
        # coerces to "m" (canvas publishes MD in metres — unknown must be
        # unavailable, mirroring the existing ft refusal).
        assert classify_depth_unit(None).unit is None
        assert classify_depth_unit("").unit is None
