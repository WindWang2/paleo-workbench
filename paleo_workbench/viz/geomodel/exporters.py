"""FLAC3D and Abaqus structured grid exporters.

Extracts the shared grid generation into _generate_structured_grid()
to eliminate the Duplicated Code smell between the two exporters.
"""
from __future__ import annotations

import logging
import numpy as np

from .models import GridSpec

logger = logging.getLogger(__name__)


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
    """Export a structured grid to FLAC3D corner-point f3grid format."""
    spec = GridSpec(nx, ny, nz, dx, dy, dz)
    try:
        nodes, elements = _generate_structured_grid(spec)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("* FLAC3D grid exported by PaleoWorkbench\n")
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
    """Export a structured grid to Abaqus INP mesh format."""
    spec = GridSpec(nx, ny, nz, dx, dy, dz)
    try:
        nodes, elements = _generate_structured_grid(spec)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("*HEADING\n")
            f.write("** Abaqus mesh exported by PaleoWorkbench\n")
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
