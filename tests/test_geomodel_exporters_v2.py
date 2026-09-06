"""V2 exporter tests (G14): real-volume FLAC3D/Abaqus, OBJ/STL/VTP,
round-trip parser validation, blocker gating, provenance sidecars."""

from __future__ import annotations

import json

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import (
    build_fault_from_mesh,
    build_horizon_from_grid,
    build_volume_shell,
)
from paleo_workbench.viz.geomodel.domain import Provenance, StratigraphicVolume
from paleo_workbench.viz.geomodel.exporters import (
    ExportError,
    export_mesh_obj,
    export_mesh_stl,
    export_mesh_vtp,
    export_volume_abaqus,
    export_volume_flac3d,
    read_abaqus_inp,
    read_flac3d_grid,
    read_obj,
    read_stl,
    read_vtp,
    validate_export,
)
from paleo_workbench.viz.geomodel.qc import QCBlockerError

CRS = "EPSG:32650"
PROV = Provenance(source_kind="catalog", source_version_ids=("hv1", "hv2"))


@pytest.fixture()
def volume():
    tg = np.full((5, 5), 100.0) + 0.5 * np.arange(25).reshape(5, 5)
    bg = tg + 50.0
    top = build_horizon_from_grid(
        "Top", tg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS, provenance=PROV
    )
    base = build_horizon_from_grid(
        "Base", bg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS, provenance=PROV
    )
    vol, qc = build_volume_shell(
        top,
        base,
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
        object_id="volume:sand",
        name="Sand",
    )
    return vol, top, base


class TestFLAC3D:
    def test_write_and_parse_back(self, volume, tmp_path):
        vol, top, base = volume
        out = export_volume_flac3d(vol, tmp_path / "sand.f3grid", top=top, base=base)
        parsed = read_flac3d_grid(out)
        assert parsed["zone_count"] > 0
        assert parsed["node_count"] > 0
        # world bounds must reflect the volume's real geometry (100..200 m)
        zmin = parsed["nodes"][:, 2].min()
        zmax = parsed["nodes"][:, 2].max()
        assert 90.0 < zmin < 110.0
        assert 140.0 < zmax < 210.0
        validate_export(out, vol)

    def test_shell_only_export_matches_grid(self, volume, tmp_path):
        vol, _, _ = volume
        out = export_volume_flac3d(vol, tmp_path / "s.f3grid")
        parsed = read_flac3d_grid(out)
        assert parsed["zone_count"] == 16 * 4  # 16 columns x 4 layers

    def test_sidecar_records_provenance(self, volume, tmp_path):
        vol, _, _ = volume
        out = export_volume_flac3d(vol, tmp_path / "s.f3grid")
        sidecar = json.loads(
            (tmp_path / "s.provenance.json").read_text(encoding="utf-8")
        )
        assert sidecar["object_id"] == vol.object_id
        assert sidecar["crs"] == CRS
        assert sidecar["provenance"]["source_version_ids"] == ["hv1", "hv2"]
        assert "qc" in sidecar

    def test_blocker_refuses(self, volume, tmp_path):
        vol, _, _ = volume
        bad = StratigraphicVolume(
            object_id="volume:bad",
            name="bad",
            crs="unknown",
            top_id=vol.top_id,
            base_id=vol.base_id,
        )
        with pytest.raises(QCBlockerError):
            export_volume_flac3d(bad, tmp_path / "bad.f3grid", top=None, base=None)
        assert not (tmp_path / "bad.f3grid").exists()


class TestAbaqus:
    def test_write_and_parse_back(self, volume, tmp_path):
        vol, top, base = volume
        out = export_volume_abaqus(vol, tmp_path / "sand.inp", top=top, base=base)
        parsed = read_abaqus_inp(out)
        assert parsed["element_count"] == 64
        # hex volume sanity: every element has positive closed volume
        nodes = parsed["nodes"]
        elems = np.array([e[1] for e in parsed["elements"]]) - 1
        p = nodes[elems]
        centre = p.mean(axis=1)
        vol6 = np.zeros(len(p))
        for a, b, c in ((0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
                        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
                        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)):
            vol6 += np.einsum(
                "ij,ij->i",
                np.cross(p[:, b] - p[:, a], p[:, c] - p[:, a]),
                centre - p[:, a],
            )
        assert np.all(np.abs(vol6 / 6.0) > 0.0)
        validate_export(out, vol)


class TestMeshFormats:
    def test_obj_roundtrip(self, volume, tmp_path):
        vol, _, _ = volume
        out = export_mesh_obj(vol, tmp_path / "sand.obj")
        parsed = validate_export(out, vol)
        assert parsed["face_count"] == len(np.asarray(vol.faces))

    def test_stl_roundtrip(self, volume, tmp_path):
        vol, _, _ = volume
        out = export_mesh_stl(vol, tmp_path / "sand.stl")
        parsed = validate_export(out, vol)
        assert parsed["triangle_count"] == len(np.asarray(vol.faces))

    def test_vtp_roundtrip_with_attributes(self, volume, tmp_path):
        vol, _, _ = volume
        facies = np.zeros(len(vol.verts))
        out = export_mesh_vtp(
            vol, tmp_path / "sand.vtp", point_data={"facies": facies}
        )
        parsed = validate_export(out, vol)
        assert parsed["point_data"]["facies"].shape == (len(vol.verts),)

    def test_fault_export(self, tmp_path):
        fault = build_fault_from_mesh(
            "F",
            np.array([[0, 0, 0], [10, 0, 5], [0, 10, 3]], dtype=float),
            np.array([[0, 1, 2]]),
            crs=CRS,
            provenance=PROV,
        )
        out = export_mesh_obj(fault, tmp_path / "f.obj")
        parsed = validate_export(out, fault)
        assert parsed["vertex_count"] == 3

    def test_missing_crs_blocks_obj(self, tmp_path):
        fault = build_fault_from_mesh(
            "F",
            np.array([[0, 0, 0], [10, 0, 5], [0, 10, 3]], dtype=float),
            np.array([[0, 1, 2]]),
        )
        with pytest.raises(QCBlockerError):
            export_mesh_obj(fault, tmp_path / "f.obj")


class TestParserRobustness:
    def test_truncated_stl_rejected(self, tmp_path):
        p = tmp_path / "x.stl"
        p.write_bytes(b"\0" * 40)
        with pytest.raises(ExportError, match="truncated"):
            read_stl(p)

    def test_stl_size_mismatch_rejected(self, tmp_path):
        import struct as _s

        p = tmp_path / "x.stl"
        p.write_bytes(b"\0" * 84 + _s.pack("<I", 3) + b"\0" * 10)
        with pytest.raises(ExportError, match="size mismatch"):
            read_stl(p)

    def test_non_vtk_xml_rejected(self, tmp_path):
        p = tmp_path / "x.vtp"
        p.write_text("<html></html>", encoding="utf-8")
        with pytest.raises(ExportError):
            read_vtp(p)

    def test_flac3d_dangling_reference_rejected(self, tmp_path):
        p = tmp_path / "x.f3grid"
        p.write_text("G 1 0 0 0\nZ B8 1 1 2 3 4 5 6 7 8\n", encoding="utf-8")
        with pytest.raises(ExportError, match="missing gridpoint"):
            read_flac3d_grid(p)

    def test_abaqus_wrong_element_type_rejected(self, tmp_path):
        p = tmp_path / "x.inp"
        p.write_text(
            "*NODE\n1, 0, 0, 0\n*ELEMENT, TYPE=S4\n1, 1, 1, 1, 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ExportError):
            read_abaqus_inp(p)


class TestLegacySignatures:
    def test_legacy_exports_still_work(self, tmp_path):
        from paleo_workbench.viz.geomodel.exporters import (
            export_to_abaqus as legacy_abaqus,
        )
        from paleo_workbench.viz.geomodel.exporters import (
            export_to_flac3d as legacy_flac3d,
        )

        f3 = tmp_path / "legacy.f3grid"
        inp = tmp_path / "legacy.inp"
        assert legacy_flac3d(str(f3), nx=3, ny=3, nz=2) is True
        assert legacy_abaqus(str(inp), nx=3, ny=3, nz=2) is True
        assert read_flac3d_grid(f3)["zone_count"] == 18
        assert read_abaqus_inp(inp)["element_count"] == 18
        # legacy header honestly marks the synthetic nature
        assert "LEGACY" in f3.read_text(encoding="utf-8")


class TestParserGarbage:
    """P2-6: every reader fails with ExportError on garbage, never the
    underlying parser exception type."""

    def test_vtp_garbage_raises_ExportError(self, tmp_path):
        p = tmp_path / "g.vtp"
        p.write_bytes(b"\x00\x01\x02garbage\xff")
        with pytest.raises(ExportError, match="malformed VTK XML"):
            read_vtp(p)

    def test_vtp_empty_raises(self, tmp_path):
        p = tmp_path / "e.vtp"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ExportError):
            read_vtp(p)

    def test_obj_garbage_raises(self, tmp_path):
        p = tmp_path / "g.obj"
        p.write_text("# only a comment\n", encoding="utf-8")
        with pytest.raises(ExportError, match="no vertices"):
            read_obj(p)
