"""Scene adapter tests (G2): stub-widget sync, determinism, incremental
updates, picking back-transform, teardown safety."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import (
    build_fault_curtain_from_trace,
    build_horizon_from_grid,
    build_simplified_vertical_well,
    build_volume_shell,
    build_well_trajectory,
)
from paleo_workbench.viz.geomodel.domain import ModelAssembly, MeasurementRecord
from paleo_workbench.viz.geomodel.measurements import distance
from paleo_workbench.viz.geomodel.scene_adapter import (
    DomainPick,
    GeologicalSceneAdapter,
    ObjectStyle,
)


class RecordingWidget:
    """Stub WellSeismicJointWidget: records engine calls, no GL."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.objects: dict[str, dict] = {}
        self._scene = None

    def set_scene_ref(self, scene):
        self._scene = scene

    def scene(self):
        return self._scene

    def add_scene_object(self, name, **kwargs):
        self.calls.append(("add", name))
        self.objects[name] = kwargs

    def remove_scene_object(self, name):
        self.calls.append(("remove", name))
        self.objects.pop(name, None)

    def set_scene_object_visibility(self, name, visible):
        self.calls.append(("vis", name, visible))

    def set_scene_object_opacity(self, name, opacity):
        self.calls.append(("op", name, opacity))

    def set_scene_object_color(self, name, color):
        self.calls.append(("color", name, color))

    def set_scene_object_clip_planes(self, name, planes):
        self.calls.append(("clip", name, planes))

    def pick_scene_object(self, px, py, kinds=None):
        for name, kw in self.objects.items():
            if kw.get("pickable"):
                return _FakeHit(name=name, kind=kw.get("kind", "generic"))
        return None

    def world_xyz_to_index(self, world):
        return np.asarray(world, dtype=np.float64)

    def index_xyz_to_world(self, idx):
        return np.asarray(idx, dtype=np.float64)


class _FakeHit:
    def __init__(self, name, kind):
        self.name = name
        self.kind = kind
        self.point = (5.0, 5.0, 5.0)
        self.distance = 1.0


class _FakeScene:
    """Identity mapping with domain-z passthrough."""

    def world_to_render_xyz_array(self, pts):
        return np.asarray(pts, dtype=np.float64)

    def render_to_world_xyz_array(self, pts):
        return np.asarray(pts, dtype=np.float64)


@pytest.fixture()
def rig():
    widget = RecordingWidget()
    widget.set_scene_ref(_FakeScene())
    holder = {"widget": widget}
    adapter = GeologicalSceneAdapter(lambda: holder["widget"])
    return holder, adapter


def make_assembly(n_wells=2):
    asm = ModelAssembly()
    for k in range(n_wells):
        st = np.array(
            [[0.0, k * 10.0, 0.0, 0.0], [100.0, k * 10.0, 5.0, -100.0]],
            dtype=float,
        )
        asm.add(build_well_trajectory(f"W{k}", st, crs="EPSG:32650"))
    tg = np.full((4, 4), -100.0)
    asm.add(
        build_horizon_from_grid(
            "Top", tg, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650"
        )
    )
    return asm


class TestSync:
    def test_first_sync_adds_all(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        report = adapter.sync(asm)
        assert len(report.added) == 3
        assert report.unchanged == 0
        # each well contributes trajectory + head + label; horizon is a mesh
        assert len(widget_objects(holder)) >= 3 + 1

    def test_second_sync_is_noop(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        before = len(widget_objects(holder))
        report2 = adapter.sync(asm)
        assert report2.added == [] and report2.updated == []
        assert report2.unchanged == 3
        assert len(widget_objects(holder)) == before  # no rebuild churn

    def test_single_object_change_is_incremental(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        n_before = len(holder["widget"].calls)
        # move one well: bump version (token change)
        well = asm.get("well:w0")
        import dataclasses

        asm.replace(dataclasses.replace(well, version=well.version + 1))
        report = adapter.sync(asm)
        assert report.updated == ["well:w0"]
        assert report.unchanged == 2
        assert len(holder["widget"].calls) > n_before

    def test_removal_drops_derived_objects(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        asm.remove("well:w0")
        report = adapter.sync(asm)
        assert report.removed == ["well:w0"]
        assert not any(n.startswith("well:w0") for n in widget_objects(holder))

    def test_no_widget_is_safe_noop(self):
        adapter = GeologicalSceneAdapter(lambda: None)
        report = adapter.sync(make_assembly())
        assert report.added == []

    def test_deterministic_across_adapters(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        adapter2 = GeologicalSceneAdapter(lambda: holder["widget"])
        adapter2.sync(asm)
        # identical token state → identical derived name sets
        assert set(adapter._derived) == set(adapter2._derived)


class TestViewState:
    def test_visibility_and_opacity(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        adapter.set_visibility("well:w0", False)
        adapter.set_opacity("well:w1", 0.5)
        widget = holder["widget"]
        assert any(c[0] == "vis" and c[1] == "well:w0" and c[2] is False for c in widget.calls)
        assert any(c[0] == "op" and c[1].startswith("well:w1") for c in widget.calls)
        # persisted view state survives rebuild
        import dataclasses

        well = asm.get("well:w0")
        asm.replace(dataclasses.replace(well, version=well.version + 5))
        adapter.sync(asm)
        assert any(
            c[0] == "add" and c[1] == "well:w0" for c in widget.calls
        )

    def test_clip_planes_applied_to_all(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        planes = [(0.0, 0.0, -1.0, 10.0)]
        adapter.set_clip_planes(planes)
        widget = holder["widget"]
        clips = [c for c in widget.calls if c[0] == "clip"]
        assert clips
        assert all(c[2] == planes for c in clips)

    def test_selection_highlight_updates_color(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        adapter.set_selected("well:w1")
        widget = holder["widget"]
        sel = [c for c in widget.calls if c[0] == "color" and c[1].startswith("well:w1")]
        assert sel
        assert sel[-1][2] == ObjectStyle().selected_color


class TestPicking:
    def test_pick_maps_back_to_domain(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        pick = adapter.pick(100, 100)
        assert isinstance(pick, DomainPick)
        assert pick.object_id in asm
        assert pick.domain_xyz == pytest.approx((5.0, 5.0, 5.0))

    def test_pick_without_widget_is_none(self):
        adapter = GeologicalSceneAdapter(lambda: None)
        assert adapter.pick(1, 1) is None


class TestTeardownSafety:
    def test_widget_disappearing_between_syncs(self, rig):
        holder, adapter = rig
        asm = make_assembly()
        adapter.sync(asm)
        holder["widget"] = None  # viewport destroyed
        adapter.set_visibility("well:w0", False)
        adapter.set_opacity("well:w1", 0.2)
        adapter.set_selected("well:w0")
        adapter.set_clip_planes([(0, 0, -1, 1)])
        assert adapter.sync(asm).added == []  # no crash, no stale calls
        holder["widget"] = RecordingWidget()  # fresh viewport, no scene bound
        report = adapter.sync(asm)
        # A new widget is a new render context (scene identity changed), so
        # every payload rebuilds — the stale-transform correctness rule
        # (review P1-4) intentionally dominates cache reuse here.
        assert len(report.updated) == 3
        assert report.added == []

    def test_reset_clears_everything(self, rig):
        holder, adapter = rig
        adapter.sync(make_assembly())
        adapter.reset()
        assert not widget_objects(holder)
        assert adapter._synced_tokens == {}


def widget_objects(holder):
    return list(holder["widget"].objects)


class TestPayloads:
    def test_well_payloads_use_line_strip(self, rig):
        holder, adapter = rig
        asm = ModelAssembly()
        st = np.array([[0.0, 0, 0, 0], [50.0, 5, 5, -50], [100.0, 10, 10, -100]])
        asm.add(build_well_trajectory("WA", st, crs="EPSG:32650"))
        adapter.sync(asm)
        traj = holder["widget"].objects["well:wa"]
        assert traj["mode"] == "lines"
        assert traj["line_mode"] == "line_strip"
        assert traj["kind"] == "well"
        assert traj["pickable"] is True
        # domain z=0..-100 flows through the identity mapping unchanged
        assert traj["verts"][0, 2] == pytest.approx(0.0)
        assert traj["verts"][-1, 2] == pytest.approx(-100.0)

    def test_horizon_nan_holes_are_not_triangulated(self, rig):
        holder, adapter = rig
        asm = ModelAssembly()
        g = np.full((5, 5), -100.0)
        g[2, 2] = np.nan  # single hole: quads touching it are dropped
        asm.add(
            build_horizon_from_grid("H", g, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650")
        )
        adapter.sync(asm)
        mesh = holder["widget"].objects["horizon:h"]
        # 16 valid quads minus the 4 touching the hole -> 12 quads = 24 tris
        assert len(mesh["faces"]) == 24
        # and no triangle references the NaN node
        assert len(np.unique(mesh["faces"])) == 24

    def test_fault_and_volume_meshes(self, rig):
        holder, adapter = rig
        asm = ModelAssembly()
        asm.add(
            build_fault_curtain_from_trace(
                "F", [(0, 0), (50, 0)], 0.0, 100.0, crs="EPSG:32650"
            )
        )
        tg = np.full((4, 4), 100.0)
        bg = np.full((4, 4), 150.0)
        top = build_horizon_from_grid("T", tg, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650")
        base = build_horizon_from_grid("B", bg, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650")
        vol, _ = build_volume_shell(
            top, base, [(0, 0), (30, 0), (30, 30), (0, 30)], object_id="volume:v"
        )
        asm.add(vol)
        adapter.sync(asm)
        assert "fault:f" in widget_objects(holder)
        assert "volume:v" in widget_objects(holder)
        assert holder["widget"].objects["volume:v"]["faces"].shape[1] == 3

    def test_facies_face_colors(self, rig):
        holder, adapter = rig
        tg = np.full((4, 4), 100.0)
        bg = np.full((4, 4), 150.0)
        top = build_horizon_from_grid("T", tg, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650")
        base = build_horizon_from_grid("B", bg, origin=(0, 0), spacing=(10, 10), crs="EPSG:32650")
        vol, _ = build_volume_shell(
            top, base, [(0, 0), (30, 0), (30, 30), (0, 30)], object_id="volume:v"
        )
        import dataclasses

        vol = dataclasses.replace(
            vol, facies=np.zeros(len(vol.verts), dtype=int)
        )
        asm = ModelAssembly()
        asm.add(vol)
        adapter.sync(asm)
        fc = holder["widget"].objects["volume:v"]["face_colors"]
        assert fc is not None
        assert fc.shape == (len(vol.faces), 4)

    def test_measurement_payloads(self, rig):
        holder, adapter = rig
        asm = ModelAssembly()
        m = distance((0, 0, 0), (3, 4, 0), crs="EPSG:32650")
        asm.add(m)
        adapter.sync(asm)
        assert m.object_id in widget_objects(holder)
        assert f"{m.object_id}#label" in widget_objects(holder)
