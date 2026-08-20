"""Regression test for #888: engine default depth_step must not override the
real sampling axis.

A 0.1524 m (half-foot) LAS previously produced a recommended top 699.5 m off
because the engine passed a fixed 0.5 default as an explicit override; the
correlator only derives the real step when depth_step is None.
"""

from __future__ import annotations

import numpy as np

from paleo_workbench.viz.stratigraphic_correlation_engine import StratigraphicCorrelationEngine


def _wells(step: float = 0.1524, n: int = 10_000, start: float = 1000.0):
    depths = start + np.arange(n) * step
    curve = np.sin(np.linspace(0.0, 40.0 * np.pi, n))
    well = {
        "name": "W",
        "depths": {"GR": list(depths)},
        "curves": {"GR": list(curve)},
    }
    return [dict(well, name="A"), dict(well, name="B")]


def test_engine_default_uses_real_depth_axis() -> None:
    step = 0.1524
    wells = _wells(step=step)
    ref_top = 1005.84  # sits on an exact sample of the 0.1524 m axis

    engine = StratigraphicCorrelationEngine().with_wells(wells)
    rec = engine.recommend_top("A", "B", ref_top, curve_key="GR")

    assert abs(rec.suggested_depth - ref_top) < 2.0 * step, (
        f"engine default should use the real axis: got {rec.suggested_depth:.2f}, "
        f"expected ~{ref_top:.2f} (a 0.5 default would return ~306)"
    )


def test_engine_explicit_depth_step_still_overrides() -> None:
    wells = _wells()
    ref_top = 1005.84
    engine = (
        StratigraphicCorrelationEngine()
        .with_wells(wells)
        .with_dtw_config(depth_step=0.5)
    )
    rec = engine.recommend_top("A", "B", ref_top, curve_key="GR")
    # An explicit override must still take effect (resampling the reference
    # index grid onto 0.5 m) rather than being ignored.
    assert abs(rec.suggested_depth - ref_top) > 2.0 * 0.1524
