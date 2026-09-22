"""Headless tests for the V2 geological domain model (G1)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.domain import (
    DomainError,
    FaultSurface,
    HorizonSurface,
    MeasurementRecord,
    ModelAssembly,
    Provenance,
    StratigraphicVolume,
    TunnelSection,
    WellTrajectory,
)
from paleo_workbench.viz.geomodel.builders import (
    build_horizon_from_grid,
    build_simplified_vertical_well,
    build_well_trajectory,
)


def make_well(**kwargs) -> WellTrajectory:
    st = np.array(
        [
            [0.0, 100.0, 200.0, 0.0],
            [100.0, 100.0, 200.0, 100.0],
            [200.0, 105.0, 202.0, 200.0],
        ]
    )
    return build_well_trajectory("W-1", st, crs="EPSG:32650", **kwargs)


class TestWellTrajectory:
    def test_identity_and_meta_roundtrip(self):
        well = make_well(
            provenance=Provenance(source_kind="catalog", source_version_ids=("v1",))
        )
        assert well.object_id == "well:w-1"
        assert well.kind() == "well"
        meta = well.meta()
        again = WellTrajectory.from_meta(meta)
        for f in ("object_id", "name", "crs", "unit", "representation", "version"):
            assert getattr(again, f) == getattr(well, f)
        assert again.provenance.source_version_ids == ("v1",)

    def test_meta_is_json_safe(self):
        import json

        well = make_well()
        json.dumps(well.meta())  # must not raise

    def test_md_monotonic_enforced(self):
        st = np.array(
            [[0.0, 0, 0, 0], [100.0, 0, 0, 100], [100.0, 0, 0, 100], [90.0, 0, 0, 90]]
        )
        with pytest.raises(DomainError, match="strictly increasing"):
            build_well_trajectory("bad", st)

    def test_simplified_vertical_representation(self):
        well = build_simplified_vertical_well(
            "W-2", (10.0, 20.0, 100.0), 500.0, crs="EPSG:32650"
        )
        assert well.representation == "simplified_vertical"
        assert well.stations.shape == (2, 4)
        assert well.stations[1, 3] == pytest.approx(600.0)
        # meta carries the representation so UI/export never fake a measured path
        assert well.meta()["representation"] == "simplified_vertical"

    def test_object_id_kind_prefix_enforced(self):
        with pytest.raises(DomainError, match="well:"):
            WellTrajectory(object_id="fault:nope", name="x")

    def test_nan_stations_rejected(self):
        st = np.array([[0.0, 0, 0, np.nan], [10.0, 0, 0, 10]])
        with pytest.raises(DomainError):
            build_well_trajectory("bad", st)

    def test_immutable_and_version_bump(self):
        well = make_well()
        with pytest.raises(dataclasses.FrozenInstanceError):
            well.name = "changed"  # type: ignore[misc]
        bumped = dataclasses.replace(well, version=well.version + 1)
        assert bumped.version == 2 and well.version == 1


class TestHorizonSurface:
    def test_build_with_nan_holes(self):
        g = np.arange(25, dtype=float).reshape(5, 5)
        g[2, 2] = np.nan
        h = build_horizon_from_grid("H1", g, crs="EPSG:32650", unit="m")
        assert h.object_id == "horizon:h1"
        meta = h.meta()
        assert meta["stats_extra"]["nan_fraction"] == pytest.approx(1 / 25)
        assert HorizonSurface.from_meta(meta).object_id == h.object_id

    def test_inf_rejected_nan_allowed(self):
        g = np.zeros((3, 3))
        g[1, 1] = np.inf
        with pytest.raises(DomainError, match="inf"):
            build_horizon_from_grid("bad", g)

    def test_confidence_shape_mismatch(self):
        g = np.zeros((3, 3))
        with pytest.raises(DomainError, match="confidence"):
            build_horizon_from_grid("bad", g, confidence=np.zeros((2, 2)))


class TestFaultSurface:
    def test_curtain_requires_z_extent(self):
        with pytest.raises(DomainError, match="z_extent"):
            FaultSurface(
                object_id="fault:f", name="f", representation="curtain_2p5d"
            )

    def test_representation_honest(self):
        v = np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10]])
        f = np.array([[0, 1, 2]])
        fault = FaultSurface(
            object_id="fault:f",
            name="f",
            verts=v,
            faces=f,
            representation="curtain_2p5d",
            z_extent=(0.0, 10.0),
        )
        assert fault.meta()["representation"] == "curtain_2p5d"

    def test_face_index_range(self):
        v = np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10]])
        with pytest.raises(DomainError, match="out of range"):
            FaultSurface(
                object_id="fault:f",
                name="f",
                verts=v,
                faces=np.array([[0, 1, 3]]),
            )


class TestVolumeTunnelMeasurement:
    def test_volume_meta_roundtrip_keeps_quality(self):
        vol = StratigraphicVolume(
            object_id="volume:sand",
            name="Sand",
            top_id="horizon:top",
            base_id="horizon:base",
            quality={"closed": True, "column_count": 12},
        )
        meta = vol.meta()
        assert meta["quality"]["closed"] is True
        assert StratigraphicVolume.from_meta(meta).top_id == "horizon:top"

    def test_facies_length_must_match_verts(self):
        with pytest.raises(DomainError, match="facies"):
            StratigraphicVolume(
                object_id="volume:v",
                name="v",
                verts=np.zeros((3, 3)),
                facies=np.array([0, 1]),
            )

    def test_tunnel(self):
        t = TunnelSection(
            object_id="tunnel:t1",
            name="T1",
            path=np.array([[0, 0, 0], [1, 1, 1]]),
        )
        assert TunnelSection.from_meta(t.meta()).radius == 3.0
        with pytest.raises(DomainError, match="radius"):
            TunnelSection(object_id="tunnel:t", name="t", radius=-1)

    def test_measurement_points_persist(self):
        m = MeasurementRecord(
            object_id="measure:m1",
            name="dist",
            measurement_kind="distance",
            points=np.array([[0, 0, 0], [3, 4, 0]]),
            result=5.0,
        )
        m2 = MeasurementRecord.from_meta(m.meta())
        assert m2.result == 5.0
        assert m2.points.shape == (2, 3)
        with pytest.raises(DomainError, match="measurement kind"):
            MeasurementRecord(object_id="measure:x", name="x", measurement_kind="area")


class TestModelAssembly:
    def test_add_get_remove_kind_filter(self):
        asm = ModelAssembly()
        well = make_well()
        hor = build_horizon_from_grid("H", np.ones((3, 3)))
        asm.add(well)
        asm.add(hor)
        assert len(asm) == 2
        assert asm.ids("well") == ["well:w-1"]
        assert asm.get("horizon:h") is hor
        assert asm.remove("well:w-1") is True
        assert asm.remove("well:w-1") is False
        assert len(asm) == 1

    def test_duplicate_rejected_replace_updates(self):
        asm = ModelAssembly()
        well = make_well()
        asm.add(well)
        with pytest.raises(DomainError, match="duplicate"):
            asm.add(make_well())
        renamed = dataclasses.replace(well, name="W-1 renamed", version=2)
        asm.replace(renamed)
        assert asm.get("well:w-1").name == "W-1 renamed"

    def test_meta_roundtrip_preserves_order_and_display(self):
        asm = ModelAssembly()
        well = make_well()
        hor = build_horizon_from_grid("H", np.ones((3, 3)))
        asm.add(well)
        asm.add(hor)
        asm.display["well:w-1"] = {"visible": False, "opacity": 0.5}
        snap = asm.to_meta()
        asm2 = ModelAssembly()
        restored = asm2.apply_meta(snap)
        assert restored == ["well:w-1", "horizon:h"]
        # arrays are not in meta: grid comes back empty (loader's job)
        assert asm2.get("horizon:h").z_grid.shape == (0, 0)
        assert asm2.display["well:w-1"]["visible"] is False
        assert asm2.ids() == ["well:w-1", "horizon:h"]

    def test_broken_meta_entries_reported_not_fatal(self):
        asm = ModelAssembly()
        bad = {
            "objects": [
                {"object_id": "well:ok", "name": "ok"},
                {"object_id": "weird:bad", "name": "bad"},
                {"object_id": "horizon:h", "confidence": "junk"},
            ]
        }
        restored = asm.apply_meta(bad)
        assert restored == ["well:ok"]
        assert len(asm) == 1

    def test_clear_by_kind(self):
        asm = ModelAssembly()
        asm.add(make_well())
        asm.add(build_horizon_from_grid("H", np.ones((3, 3))))
        assert asm.clear("well") == 1
        assert asm.ids() == ["horizon:h"]


class TestGeometryStats:
    def test_well_bounds(self):
        well = make_well()
        stats = well.meta()["stats"]
        assert stats["vertex_count"] == 3
        assert stats["bounds"][0] == pytest.approx(100.0)   # min x
        assert stats["bounds"][3] == pytest.approx(105.0)   # max x
        assert stats["bounds"][5] == pytest.approx(200.0)   # max z
