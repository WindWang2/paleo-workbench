"""Engine-side fixes from the 2026-08-20 audit, exercised from the workbench.

* #877 the geo-viz-engine IDW kernel compared a SUM OF WEIGHTS against the
  DISTANCE epsilon, so cells with a small-but-positive weight sum were emitted
  as nodata. #844 fixed the workbench batch path only; the engine kernel kept
  the defect.
* #880 ``FeatureEditor`` validated topology ring by ring, which cannot express
  inter-ring relationships, so an outer vertex dragged inside a hole (and a
  vertex dropped onto another vertex) committed an OGC-invalid polygon with no
  ``TopologyError``.
"""

from __future__ import annotations

import numpy as np
import pytest

shapely_geometry = pytest.importorskip("shapely.geometry")
shapely_validation = pytest.importorskip("shapely.validation")
shape = shapely_geometry.shape
explain_validity = shapely_validation.explain_validity

from geoviz_plots.interpolation.idw import interpolate_idw  # noqa: E402
from geoviz_plots.map_edit.feature_editor import (  # noqa: E402
    FeatureEditor,
    TopologyError,
)


# --------------------------------------------------------------------------- #
# #877 — IDW weight-sum threshold


# UTM-magnitude coordinates are the point: at power>=4 a ~1 km nearest-well
# distance gives per-well weights around 1e-12, so the weight SUM drops below
# the 1e-12 distance floor the kernel used to compare against.
_XS = np.array([500000.0, 502000.0, 504000.0, 500500.0, 503000.0, 501500.0])
_YS = np.array([3000000.0, 3001000.0, 3000500.0, 3002000.0, 3002500.0, 3000000.0])


@pytest.mark.parametrize("power", [2.0, 3.0, 3.5, 4.0, 6.0])
def test_idw_constant_field_has_no_nodata_at_high_power(power: float) -> None:
    """A constant field surrounded by wells must interpolate everywhere.

    IDW is ``sum(w*z)/sum(w)`` and is defined for ANY positive weight sum, so a
    cell may only be nodata when it has no contributing wells at all.
    """
    z = np.full(_XS.size, 10.0)
    gx = np.linspace(_XS.min(), _XS.max(), 4)
    gy = np.linspace(_YS.min(), _YS.max(), 4)

    out = interpolate_idw(_XS, _YS, z, gx, gy, power=power)

    assert not np.isnan(out).any(), (
        f"power={power} produced {int(np.isnan(out).sum())} nodata cells on a "
        "constant field with six surrounding wells (#877)"
    )
    np.testing.assert_allclose(out, 10.0, rtol=1e-9)


def test_idw_engine_and_workbench_batch_path_agree_at_high_power() -> None:
    """The two IDW implementations must not disagree for the same inputs.

    #844 fixed only the workbench batch path, so the two kernels returned
    different results (nodata vs values) for identical wells and grid.
    """
    from paleo_workbench.workflow.interpolation_plan import (
        apply_idw_plan,
        build_idw_plan,
    )

    z = np.full(_XS.size, 10.0)
    samples = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(_XS, _YS, z)
    ]

    plan = build_idw_plan(samples, grid_n=4, power=4.0)
    batch = apply_idw_plan(plan, z)

    # Run the engine kernel on the plan's own axes so the grids are identical.
    engine = interpolate_idw(
        _XS, _YS, z,
        np.asarray(batch["grid_x"]), np.asarray(batch["grid_y"]),
        power=4.0,
    )

    batch_z = np.asarray(batch["grid_z"], dtype=float)
    assert not np.isnan(engine).any(), "engine kernel emitted nodata (#877)"
    assert not np.isnan(batch_z).any(), "workbench batch path emitted nodata"
    np.testing.assert_allclose(engine, batch_z, rtol=1e-9)


# --------------------------------------------------------------------------- #
# #880 — whole-polygon topology validation

_OUTER = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
_HOLE = [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]


def _editor(coordinates: list[list[list[float]]]) -> FeatureEditor:
    editor = FeatureEditor()
    editor.load_layer(
        [{"id": "p1", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": coordinates}}]
    )
    return editor


def _geometry(editor: FeatureEditor) -> dict:
    features = editor.features
    feature = features["p1"] if isinstance(features, dict) else features[0]
    return feature["geometry"]


@pytest.mark.parametrize(
    "coordinates, select, destination, label",
    [
        ([list(_OUTER), list(_HOLE)], (0.0, 0.0), (4.0, 4.0), "outer vertex into hole"),
        ([list(_OUTER)], (0.0, 0.0), (10.0, 10.0), "bow-tie via coincident vertex"),
        ([list(_OUTER)], (0.0, 0.0), (15.0, 5.0), "crossing edges"),
        ([list(_OUTER)], (10.0, 0.0), (0.0, 10.0), "crossing edges, other vertex"),
    ],
)
def test_invalid_drag_raises_and_rolls_back(
    coordinates, select, destination, label
) -> None:
    """Every drag that would invalidate the polygon must raise and roll back."""
    editor = _editor(coordinates)
    before = shape(_geometry(editor))
    assert before.is_valid, "fixture must start valid"

    editor.select_at(*select)
    with pytest.raises(TopologyError):
        editor.move_selected_vertex(*destination, snap=False)

    after = shape(_geometry(editor))
    assert after.is_valid, (
        f"{label}: geometry left invalid after rollback -> "
        f"{explain_validity(after)}"
    )
    assert after.equals(before), f"{label}: rollback did not restore the geometry"


def test_valid_drag_is_still_accepted() -> None:
    """The stricter validation must not reject legitimate edits."""
    editor = _editor([list(_OUTER), list(_HOLE)])
    editor.select_at(0.0, 0.0)
    assert editor.move_selected_vertex(-2.0, -2.0, snap=False) is True

    moved = shape(_geometry(editor))
    assert moved.is_valid, explain_validity(moved)
    # The hole must survive the edit.
    assert len(_geometry(editor)["coordinates"]) == 2
    assert moved.area > shape({"type": "Polygon", "coordinates": [_OUTER, _HOLE]}).area
