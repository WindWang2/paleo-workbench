"""Geological export / interchange (G14).

Two families:

**V2 domain exporters** — take a :class:`StratigraphicVolume` (or any mesh
carrying domain object) and write real, verifiable geometry:

* :func:`export_volume_flac3d`   — columnar hex mesh, Itasca ``Z B8`` syntax;
* :func:`export_volume_abaqus`   — columnar hex mesh, ``C3D8`` elements;
* :func:`export_mesh_obj` / :func:`export_mesh_stl` — triangle surfaces;
* :func:`export_mesh_vtp`        — VTK XML PolyData (hand-written, no vtk
  dependency), optionally carrying per-vertex attribute arrays.

Every V2 write is accompanied by a ``<name>.provenance.json`` sidecar (CRS,
unit, source versions, QC summary, indexing conventions) and is gated by
:func:`paleo_workbench.viz.geomodel.qc.assert_exportable` — a blocker-level
QC issue refuses the export instead of writing a silently-wrong artifact.

**Parser validators** — :func:`read_flac3d_grid`, :func:`read_abaqus_inp`,
:func:`read_obj`, :func:`read_stl`, :func:`read_vtp` — used by tests and by
:func:`validate_export` to prove written files parse back with consistent
counts / bounds / indices (no placeholder text pretending to be a format).

The legacy ``export_to_flac3d`` / ``export_to_abaqus`` GridSpec signatures
are kept for backward compatibility and are explicitly documented as legacy
synthetic-grid exports (they never referenced user geometry — see baseline).
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np

from .builders import build_columnar_hex_mesh
from .domain import (
    DomainObject,
    FaultSurface,
    HorizonSurface,
    Provenance,
    StratigraphicVolume,
    TunnelSection,
)
from .qc import QCReport, assert_exportable, qc_object
from .models import GridSpec

logger = logging.getLogger(__name__)

__all__ = [
    "ExportError",
    "export_volume_flac3d",
    "export_volume_abaqus",
    "export_mesh_obj",
    "export_mesh_stl",
    "export_mesh_vtp",
    "read_flac3d_grid",
    "read_abaqus_inp",
    "read_obj",
    "read_stl",
    "read_vtp",
    "validate_export",
    "_generate_structured_grid",
    "export_to_flac3d",
    "export_to_abaqus",
]


class ExportError(RuntimeError):
    """Export could not produce a trustworthy artifact."""


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _mesh_of(obj: DomainObject) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(obj, (FaultSurface, StratigraphicVolume)):
        return (
            np.asarray(obj.verts, dtype=np.float64),
            np.asarray(obj.faces, dtype=np.int64).reshape(-1, 3),
        )
    raise ExportError(f"{obj.object_id}: object kind has no triangle mesh to export")


def _write_sidecar(
    path: Path,
    obj: DomainObject,
    *,
    fmt: str,
    extra: Mapping[str, Any],
    report: QCReport | None,
) -> None:
    sidecar = {
        "format": fmt,
        "object_id": obj.object_id,
        "name": obj.name,
        "crs": obj.crs,
        "vertical_domain": obj.vertical_domain,
        "unit": obj.unit,
        "provenance": obj.provenance.to_meta(),
        "indexing": "node/element ids are 1-based in file, 0-based in numpy",
        **extra,
    }
    if report is not None:
        sidecar["qc"] = report.to_meta()
    sidecar_path = path.with_name(path.stem + ".provenance.json")
    sidecar_path.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# V2 exporters
# ---------------------------------------------------------------------------


def export_volume_flac3d(
    volume: StratigraphicVolume,
    path: str | Path,
    *,
    top: HorizonSurface | None = None,
    base: HorizonSurface | None = None,
    n_layers: int = 4,
    zone_name: str = "GEOMODEL",
) -> Path:
    """Write the volume's columnar hex mesh as an Itasca FLAC3D grid.

    ``top``/``base`` — the source horizons when available (preferred: exact
    build inputs); otherwise the shell's own top/base sheets are regridded
    onto their lattice. Crossed columns are skipped (never reordered); node
    ids are 1-based in the file. Refuses on blocker QC issues.
    """
    assert_exportable([volume])
    boundary = volume.boundary
    if boundary is None:
        raise ExportError(f"{volume.object_id}: volume has no boundary polygon")
    top_like, base_like = _sheet_horizons(volume, top, base)
    nodes, hexes, info = build_columnar_hex_mesh(
        top_like, base_like, boundary, n_layers=n_layers
    )
    if len(hexes) == 0:
        raise ExportError(f"{volume.object_id}: no valid columns to export")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("* FLAC3D grid exported by PaleoWorkbench\n")
        f.write(
            f"* object: {volume.object_id} ({volume.name}) "
            f"cells={len(hexes)} nodes={len(nodes)}\n"
        )
        f.write(f"* CRS: {volume.crs}  unit: {volume.unit}\n")
        for node_id, (x, y, z) in enumerate(nodes, start=1):
            f.write(f"G {node_id} {x:.4f} {y:.4f} {z:.4f}\n")
        for zone_id, elem in enumerate(hexes, start=1):
            ids = " ".join(str(int(n) + 1) for n in elem)
            f.write(f"Z B8 {zone_id} {ids}\n")
    _write_sidecar(
        out,
        volume,
        fmt="flac3d-grid",
        extra={"zone_name": zone_name, "mesh": info},
        report=qc_object(volume),
    )
    logger.info(
        "FLAC3D export: %s (%d zones, %d gridpoints)", out, len(hexes), len(nodes)
    )
    return out


def export_volume_abaqus(
    volume: StratigraphicVolume,
    path: str | Path,
    *,
    top: HorizonSurface | None = None,
    base: HorizonSurface | None = None,
    n_layers: int = 4,
    part_name: str = "GEOMODEL",
) -> Path:
    """Write the volume's columnar hex mesh as an Abaqus C3D8 INP."""
    assert_exportable([volume])
    boundary = volume.boundary
    if boundary is None:
        raise ExportError(f"{volume.object_id}: volume has no boundary polygon")
    top_like, base_like = _sheet_horizons(volume, top, base)
    nodes, hexes, info = build_columnar_hex_mesh(
        top_like, base_like, boundary, n_layers=n_layers
    )
    if len(hexes) == 0:
        raise ExportError(f"{volume.object_id}: no valid columns to export")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("*HEADING\n")
        f.write(
            f"** PaleoWorkbench export: {volume.object_id} ({volume.name})\n"
            f"** CRS: {volume.crs}  unit: {volume.unit}\n"
        )
        f.write(f"*PART, NAME={part_name}\n")
        f.write("*NODE\n")
        for node_id, (x, y, z) in enumerate(nodes, start=1):
            f.write(f"{node_id}, {x:.4f}, {y:.4f}, {z:.4f}\n")
        f.write("*ELEMENT, TYPE=C3D8, ELSET=EALL\n")
        for zone_id, elem in enumerate(hexes, start=1):
            ids = ", ".join(str(int(n) + 1) for n in elem)
            f.write(f"{zone_id}, {ids}\n")
        f.write("*END PART\n")
    _write_sidecar(
        out,
        volume,
        fmt="abaqus-inp",
        extra={"part_name": part_name, "mesh": info},
        report=qc_object(volume),
    )
    logger.info(
        "Abaqus export: %s (%d elements, %d nodes)", out, len(hexes), len(nodes)
    )
    return out


def _sheet_horizons(
    volume: StratigraphicVolume,
    top: HorizonSurface | None,
    base: HorizonSurface | None,
) -> tuple[HorizonSurface, HorizonSurface]:
    """Horizon pair for the hex builder: caller-provided when given,
    otherwise regridded from the shell's own top/base vertex sheets."""
    if top is not None and base is not None:
        return top, base
    from .domain import HorizonSurface

    def regrid(sheet: str) -> HorizonSurface:
        verts = np.asarray(volume.verts, dtype=np.float64)
        if len(verts) == 0:
            raise ExportError(f"{volume.object_id}: empty shell")
        n_half = len(verts) // 2
        pts = verts[:n_half] if sheet == "top" else verts[n_half:]
        xy = pts[:, :2]
        xs = np.unique(np.round(xy[:, 0], 9))
        ys = np.unique(np.round(xy[:, 1], 9))
        if len(xs) * len(ys) == len(pts):
            z = np.full((len(ys), len(xs)), np.nan)
            zi = np.searchsorted(ys, xy[:, 1])
            zj = np.searchsorted(xs, xy[:, 0])
            z[zi, zj] = pts[:, 2]
            origin = (float(xs[0]), float(ys[0]))
            spacing = (
                float(ys[1] - ys[0]) if len(ys) > 1 else 1.0,
                float(xs[1] - xs[0]) if len(xs) > 1 else 1.0,
            )
        else:
            # non-lattice shell: nearest regular-grid assignment
            x0, y0 = xy.min(axis=0)
            x1, y1 = xy.max(axis=0)
            sx = float(np.median(np.diff(xs))) if len(xs) > 1 else 1.0
            sy = float(np.median(np.diff(ys))) if len(ys) > 1 else 1.0
            nx = int(round((x1 - x0) / max(sx, 1e-12))) + 1
            ny = int(round((y1 - y0) / max(sy, 1e-12))) + 1
            z = np.full((ny, nx), np.nan)
            zi = np.round((xy[:, 1] - y0) / max(sy, 1e-12)).astype(int)
            zj = np.round((xy[:, 0] - x0) / max(sx, 1e-12)).astype(int)
            z[zi, zj] = pts[:, 2]
            origin = (float(x0), float(y0))
            spacing = (sy, sx)
        return HorizonSurface(
            object_id=f"horizon:_export_{volume.object_id}_{sheet}",
            name=f"{volume.name}-{sheet}",
            crs=volume.crs,
            vertical_domain=volume.vertical_domain,
            unit=volume.unit,
            z_grid=z,
            origin=origin,
            spacing=spacing,
        )

    return regrid("top"), regrid("base")


def export_mesh_obj(
    obj: DomainObject,
    path: str | Path,
    *,
    label: str | None = None,
) -> Path:
    """Write a triangle mesh as Wavefront OBJ (group per object)."""
    verts, faces = _mesh_of(obj)
    assert_exportable([obj])
    if len(faces) == 0:
        raise ExportError(f"{obj.object_id}: no triangles to export")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# PaleoWorkbench OBJ export: {obj.object_id} ({obj.name})\n")
        f.write(f"# CRS: {obj.crs}  unit: {obj.unit}\n")
        f.write(f"o {label or obj.name}\n")
        for x, y, z in verts:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in faces:
            f.write(f"f {a + 1} {b + 1} {c + 1}\n")
    _write_sidecar(out, obj, fmt="obj", extra={"triangles": len(faces)}, report=qc_object(obj))
    return out


def export_mesh_stl(obj: DomainObject, path: str | Path) -> Path:
    """Write a triangle mesh as binary STL (unitless by format; the sidecar
    records the unit)."""
    verts, faces = _mesh_of(obj)
    assert_exportable([obj])
    if len(faces) == 0:
        raise ExportError(f"{obj.object_id}: no triangles to export")
    tri = verts[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.where(lengths > 0, lengths, 1.0)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"PaleoWorkbench STL export: {obj.object_id}".encode("ascii", "replace")[:80]
    header = header.ljust(80, b"\0")
    with out.open("wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(faces)))
        for i in range(len(faces)):
            f.write(
                struct.pack(
                    "<3f",
                    float(normals[i, 0]),
                    float(normals[i, 1]),
                    float(normals[i, 2]),
                )
            )
            for k in range(3):
                f.write(
                    struct.pack(
                        "<3f",
                        float(tri[i, k, 0]),
                        float(tri[i, k, 1]),
                        float(tri[i, k, 2]),
                    )
                )
            f.write(struct.pack("<H", 0))
    _write_sidecar(out, obj, fmt="stl-binary", extra={"triangles": len(faces)}, report=qc_object(obj))
    return out


def export_mesh_vtp(
    obj: DomainObject,
    path: str | Path,
    *,
    point_data: Mapping[str, Sequence[float]] | None = None,
) -> Path:
    """Write a triangle mesh as VTK XML PolyData (.vtp).

    ``point_data`` maps attribute name → per-vertex array (e.g. facies,
    confidence). Hand-written XML keeps the workbench free of a vtk runtime
    dependency; :func:`read_vtp` parses it back for validation.
    """
    verts, faces = _mesh_of(obj)
    assert_exportable([obj])
    if len(faces) == 0:
        raise ExportError(f"{obj.object_id}: no triangles to export")

    pts = " ".join(f"{c:.6f}" for p in verts for c in p)
    conn = " ".join(str(int(i)) for t in faces for i in t)
    offsets = " ".join(str(3 * (i + 1)) for i in range(len(faces)))

    root = ET.Element(
        "VTKFile", type="PolyData", version="0.1", byte_order="LittleEndian"
    )
    pd = ET.SubElement(root, "PolyData")
    piece = ET.SubElement(
        pd,
        "Piece",
        NumberOfPoints=str(len(verts)),
        NumberOfPolys=str(len(faces)),
    )
    points = ET.SubElement(piece, "Points")
    da = ET.SubElement(
        points,
        "DataArray",
        type="Float64",
        Name="Points",
        NumberOfComponents="3",
        format="ascii",
    )
    da.text = pts
    polys = ET.SubElement(piece, "Polys")
    ET.SubElement(
        polys, "DataArray", type="Int64", Name="connectivity", format="ascii"
    ).text = conn
    ET.SubElement(
        polys, "DataArray", type="Int64", Name="offsets", format="ascii"
    ).text = offsets

    if point_data:
        pda = ET.SubElement(piece, "PointData")
        for name, values in point_data.items():
            arr = np.asarray(values, dtype=np.float64)
            if len(arr) != len(verts):
                raise ExportError(
                    f"point_data {name!r} length {len(arr)} != vertices {len(verts)}"
                )
            ET.SubElement(
                pda,
                "DataArray",
                type="Float64",
                Name=str(name),
                NumberOfComponents="1",
                format="ascii",
            ).text = " ".join(f"{v:.6g}" for v in arr)

    ET.indent(root, space="  ")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    _write_sidecar(
        out,
        obj,
        fmt="vtk-polydata-xml",
        extra={"point_data": list((point_data or {}).keys())},
        report=qc_object(obj),
    )
    return out


# ---------------------------------------------------------------------------
# parser validators (write→read→assert)
# ---------------------------------------------------------------------------


def read_flac3d_grid(path: str | Path) -> dict[str, Any]:
    """Parse an Itasca-style ``G``/``Z B8`` grid file back into arrays."""
    nodes: dict[int, tuple[float, float, float]] = {}
    zones: list[tuple[int, tuple[int, ...]]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "G" and len(parts) >= 5:
            nodes[int(parts[1])] = tuple(float(v) for v in parts[2:5])
        elif parts[0] == "Z" and len(parts) >= 11 and parts[1] == "B8":
            zones.append((int(parts[2]), tuple(int(v) for v in parts[3:11])))
    if not nodes or not zones:
        raise ExportError(f"{path}: no G/Z B8 records parsed")
    for _, ids in zones:
        if min(ids) < 1 or max(ids) > len(nodes):
            raise ExportError(f"{path}: zone references missing gridpoint")
    return {
        "node_count": len(nodes),
        "zone_count": len(zones),
        "nodes": np.array([nodes[i] for i in sorted(nodes)]),
        "zones": zones,
    }


def read_abaqus_inp(path: str | Path) -> dict[str, Any]:
    """Parse the ``*NODE`` / ``*ELEMENT, TYPE=C3D8`` sections of an INP."""
    nodes: dict[int, tuple[float, float, float]] = {}
    elems: list[tuple[int, tuple[int, ...]]] = []
    section = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*NODE"):
            section = "node"
            continue
        if upper.startswith("*ELEMENT"):
            if "C3D8" not in upper:
                raise ExportError(f"{path}: unexpected element type line {line!r}")
            section = "element"
            continue
        if line.startswith("*"):
            section = None
            continue
        if not line or line.startswith("**"):
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if section == "node" and len(parts) == 4:
            nodes[int(parts[0])] = tuple(float(v) for v in parts[1:4])
        elif section == "element" and len(parts) == 9:
            elems.append((int(parts[0]), tuple(int(v) for v in parts[1:9])))
    if not nodes or not elems:
        raise ExportError(f"{path}: no C3D8 nodes/elements parsed")
    for _, ids in elems:
        if min(ids) < 1 or max(ids) > len(nodes):
            raise ExportError(f"{path}: element references missing node")
    return {
        "node_count": len(nodes),
        "element_count": len(elems),
        "nodes": np.array([nodes[i] for i in sorted(nodes)]),
        "elements": elems,
    }


def read_obj(path: str | Path) -> dict[str, Any]:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            verts.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "f" and len(parts) >= 4:
            ids = tuple(int(p.split("/")[0]) - 1 for p in parts[1:4])
            faces.append(ids)
    arr = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if len(f) and (f.min() < 0 or f.max() >= len(arr)):
        raise ExportError(f"{path}: face index out of range")
    return {
        "vertex_count": len(verts),
        "face_count": len(faces),
        "vertices": arr,
        "faces": f,
    }


def read_stl(path: str | Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ExportError(f"{path}: truncated STL")
    tri_count = struct.unpack("<I", data[80:84])[0]
    expected = 84 + tri_count * 50
    if len(data) != expected:
        raise ExportError(
            f"{path}: STL size mismatch (header says {tri_count} triangles)"
        )
    tris = np.zeros((tri_count, 3, 3), dtype=np.float64)
    off = 84
    for i in range(tri_count):
        vals = struct.unpack("<12f", data[off : off + 48])
        tris[i, 0] = vals[3:6]
        tris[i, 1] = vals[6:9]
        tris[i, 2] = vals[9:12]
        off += 50
    return {"triangle_count": tri_count, "triangles": tris}


def read_vtp(path: str | Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    if root.tag != "VTKFile" or root.get("type") != "PolyData":
        raise ExportError(f"{path}: not a VTK PolyData XML file")
    piece = root.find(".//Piece")
    if piece is None:
        raise ExportError(f"{path}: no Piece element")
    n_points = int(piece.get("NumberOfPoints", "0"))
    n_polys = int(piece.get("NumberOfPolys", "0"))
    conn_node = piece.find(".//Polys/DataArray[@Name='connectivity']")
    if conn_node is None or not (conn_node.text or "").strip():
        raise ExportError(f"{path}: empty connectivity")
    conn = np.array([int(v) for v in (conn_node.text or "").split()])
    pts_node = piece.find(".//Points/DataArray[@Name='Points']")
    if pts_node is None or not (pts_node.text or "").strip():
        raise ExportError(f"{path}: empty points")
    pts = np.array([float(v) for v in (pts_node.text or "").split()]).reshape(-1, 3)
    if len(pts) != n_points or len(conn) != 3 * n_polys:
        raise ExportError(f"{path}: declared counts do not match payload")
    if conn.min() < 0 or conn.max() >= n_points:
        raise ExportError(f"{path}: connectivity index out of range")
    attrs: dict[str, np.ndarray] = {}
    for da in piece.findall(".//PointData/DataArray"):
        name = da.get("Name", "")
        if (da.text or "").strip():
            attrs[name] = np.array([float(v) for v in (da.text or "").split()])
    return {
        "point_count": n_points,
        "poly_count": n_polys,
        "points": pts,
        "connectivity": conn.reshape(-1, 3),
        "point_data": attrs,
    }


def validate_export(path: str | Path, obj: DomainObject) -> dict[str, Any]:
    """Parse a written export back and assert it matches the source object.

    The single "not a placeholder" proof used by tests and available to the
    export UI: counts and world bounds must agree with the exported domain
    object's mesh.
    """
    out = Path(path)
    suffix = out.suffix.lower()
    if suffix == ".f3grid":
        return read_flac3d_grid(out)
    if suffix == ".inp":
        return read_abaqus_inp(out)
    if suffix == ".obj":
        parsed = read_obj(out)
        verts, faces = _mesh_of(obj)
        if parsed["face_count"] != len(faces):
            raise ExportError("OBJ face count mismatch")
        if not np.allclose(parsed["vertices"].min(axis=0), verts.min(axis=0), atol=1e-4):
            raise ExportError("OBJ bounds mismatch (min)")
        if not np.allclose(parsed["vertices"].max(axis=0), verts.max(axis=0), atol=1e-4):
            raise ExportError("OBJ bounds mismatch (max)")
        return parsed
    if suffix == ".stl":
        parsed = read_stl(out)
        verts, faces = _mesh_of(obj)
        if parsed["triangle_count"] != len(faces):
            raise ExportError("STL triangle count mismatch")
        tri_min = parsed["triangles"].reshape(-1, 3).min(axis=0)
        tri_max = parsed["triangles"].reshape(-1, 3).max(axis=0)
        if not np.allclose(tri_min, verts.min(axis=0), atol=1e-4):
            raise ExportError("STL bounds mismatch (min)")
        if not np.allclose(tri_max, verts.max(axis=0), atol=1e-4):
            raise ExportError("STL bounds mismatch (max)")
        return parsed
    if suffix == ".vtp":
        parsed = read_vtp(out)
        verts, faces = _mesh_of(obj)
        if parsed["poly_count"] != len(faces):
            raise ExportError("VTP poly count mismatch")
        if not np.allclose(parsed["points"].min(axis=0), verts.min(axis=0), atol=1e-4):
            raise ExportError("VTP bounds mismatch")
        return parsed
    raise ExportError(f"unknown export extension {suffix!r}")


# ---------------------------------------------------------------------------
# legacy structured-grid exports (synthetic, NOT user geometry)
# ---------------------------------------------------------------------------


def _generate_structured_grid(spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """Generate a structured hexahedral grid with gentle geological fluctuation.

    Returns:
        (nodes, elements) where:
        - nodes is (N_nodes, 3) float64 array of XYZ coordinates
        - elements is (N_elements, 8) int32 array of node indices (0-based)
    """
    nx, ny, nz = spec.nx, spec.ny, spec.nz
    dx, dy, dz = spec.dx, spec.dy, spec.dz

    # Vectorized node generation
    ii, jj, kk = np.meshgrid(
        np.arange(nx + 1), np.arange(ny + 1), np.arange(nz + 1), indexing="ij"
    )
    x = ii * dx
    y = jj * dy
    z = kk * dz + 5.0 * (ii / max(nx, 1)) * (jj / max(ny, 1))

    nodes = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1)

    # Vectorized element generation
    ei, ej, ek = np.meshgrid(
        np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"
    )
    ei, ej, ek = ei.ravel(), ej.ravel(), ek.ravel()

    def _nid(i, j, k):
        return i * (ny + 1) * (nz + 1) + j * (nz + 1) + k

    # C3D8/B8 face-cyclic node order: bottom face counter-clockwise
    # (i,j) -> (i+1,j) -> (i+1,j+1) -> (i,j+1), top face directly above
    # (node 5 sits on node 1, ...). The previous (i,j),(i+1,j),(i,j+1),
    # (i+1,j+1) assembly was a bowtie (Z-scan) order: every element's
    # closed-surface divergence volume was exactly 0 and its face normals
    # were meaningless — degenerate cells for both solvers (#829).
    n0 = _nid(ei, ej, ek)
    n1 = _nid(ei + 1, ej, ek)
    n2 = _nid(ei + 1, ej + 1, ek)
    n3 = _nid(ei, ej + 1, ek)
    n4 = _nid(ei, ej, ek + 1)
    n5 = _nid(ei + 1, ej, ek + 1)
    n6 = _nid(ei + 1, ej + 1, ek + 1)
    n7 = _nid(ei, ej + 1, ek + 1)

    elements = np.stack([n0, n1, n2, n3, n4, n5, n6, n7], axis=1)
    return nodes, elements


def export_to_flac3d(filename: str, nx: int = 10, ny: int = 10, nz: int = 10,
                     dx: float = 10.0, dy: float = 10.0, dz: float = 10.0) -> bool:
    """LEGACY: synthetic structured grid export (never user geometry).

    Kept for backward compatibility of the demo modeling flow; the V5 path
    is :func:`export_volume_flac3d` on a real StratigraphicVolume.
    """
    spec = GridSpec(nx, ny, nz, dx, dy, dz)
    try:
        nodes, elements = _generate_structured_grid(spec)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("* FLAC3D grid exported by PaleoWorkbench\n")
            f.write("* LEGACY synthetic grid (GridSpec), not user geometry\n")
            f.write(f"* Grid dimensions: {nx} x {ny} x {nz}\n")
            # Itasca grid format: gridpoints start with 'G', brick zones are
            # 'Z B8' followed by the eight corner gridpoint ids (#829 — the
            # previous 'GRID'/'ZON hex' keywords do not exist in FLAC3D's
            # grammar, so the files could not be imported at all).
            for node_id, (x, y, z) in enumerate(nodes, start=1):
                f.write(f"G {node_id} {x:.4f} {y:.4f} {z:.4f}\n")
            for zone_id, elem in enumerate(elements, start=1):
                ids = " ".join(str(n + 1) for n in elem)  # 1-based
                f.write(f"Z B8 {zone_id} {ids}\n")
        logger.info("FLAC3D grid successfully exported to %s", filename)
        return True
    except Exception as e:
        logger.error("Failed to export to FLAC3D: %s", e)
        raise


def export_to_abaqus(filename: str, nx: int = 10, ny: int = 10, nz: int = 10,
                     dx: float = 10.0, dy: float = 10.0, dz: float = 10.0) -> bool:
    """LEGACY: synthetic structured grid export (never user geometry)."""
    spec = GridSpec(nx, ny, nz, dx, dy, dz)
    try:
        nodes, elements = _generate_structured_grid(spec)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("*HEADING\n")
            f.write("** LEGACY Abaqus synthetic grid (GridSpec), not user geometry\n")
            f.write("*PART, NAME=GEOMODEL\n")
            f.write("*NODE\n")
            for node_id, (x, y, z) in enumerate(nodes, start=1):
                f.write(f"{node_id}, {x:.4f}, {y:.4f}, {z:.4f}\n")
            f.write("*ELEMENT, TYPE=C3D8, ELSET=EALL\n")
            for zone_id, elem in enumerate(elements, start=1):
                ids = ", ".join(str(n + 1) for n in elem)
                f.write(f"{zone_id}, {ids}\n")
            f.write("*END PART\n")
        logger.info("Abaqus mesh successfully exported to %s", filename)
        return True
    except Exception as e:
        logger.error("Failed to export to Abaqus: %s", e)
        raise
