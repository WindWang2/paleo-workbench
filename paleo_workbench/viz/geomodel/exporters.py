from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def export_to_flac3d(filename: str, nx: int = 10, ny: int = 10, nz: int = 10, dx: float = 10.0, dy: float = 10.0, dz: float = 10.0) -> bool:
    """Export a synthetic geological model structured grid to FLAC3D corner-point f3grid format."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("* FLAC3D grid exported by PaleoWorkbench\n")
            f.write(f"* Grid dimensions: {nx} x {ny} x {nz}\n")
            
            # Nodes: index starts at 1
            node_id = 1
            node_map = {}
            for k in range(nz + 1):
                for j in range(ny + 1):
                    for i in range(nx + 1):
                        x = i * dx
                        y = j * dy
                        z = k * dz
                        # Simulate geological layer fluctuation
                        z += 5.0 * (i / nx) * (j / ny)
                        f.write(f"GRID {node_id} {x:.4f} {y:.4f} {z:.4f}\n")
                        node_map[(i, j, k)] = node_id
                        node_id += 1
            
            # Zones (Hexahedra C3D8 style)
            zone_id = 1
            for k in range(nz):
                for j in range(ny):
                    for i in range(nx):
                        n1 = node_map[(i, j, k)]
                        n2 = node_map[(i+1, j, k)]
                        n3 = node_map[(i, j+1, k)]
                        n4 = node_map[(i+1, j+1, k)]
                        n5 = node_map[(i, j, k+1)]
                        n6 = node_map[(i+1, j, k+1)]
                        n7 = node_map[(i, j+1, k+1)]
                        n8 = node_map[(i+1, j+1, k+1)]
                        f.write(f"ZON hex {zone_id} {n1} {n2} {n3} {n4} {n5} {n6} {n7} {n8}\n")
                        zone_id += 1
        logger.info(f"FLAC3D grid successfully exported to {filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to export to FLAC3D: {e}")
        raise e


def export_to_abaqus(filename: str, nx: int = 10, ny: int = 10, nz: int = 10, dx: float = 10.0, dy: float = 10.0, dz: float = 10.0) -> bool:
    """Export a synthetic geological model structured grid to Abaqus INP mesh format."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("*HEADING\n")
            f.write("** Abaqus mesh exported by PaleoWorkbench\n")
            f.write("*PART, NAME=GEOMODEL\n")
            f.write("*NODE\n")
            
            node_id = 1
            node_map = {}
            for k in range(nz + 1):
                for j in range(ny + 1):
                    for i in range(nx + 1):
                        x = i * dx
                        y = j * dy
                        z = k * dz
                        # Simulate geological layer fluctuation
                        z += 5.0 * (i / nx) * (j / ny)
                        f.write(f"{node_id}, {x:.4f}, {y:.4f}, {z:.4f}\n")
                        node_map[(i, j, k)] = node_id
                        node_id += 1
                        
            f.write("*ELEMENT, TYPE=C3D8, ELSET=EALL\n")
            zone_id = 1
            for k in range(nz):
                for j in range(ny):
                    for i in range(nx):
                        n1 = node_map[(i, j, k)]
                        n2 = node_map[(i+1, j, k)]
                        n3 = node_map[(i+1, j+1, k)]
                        n4 = node_map[(i, j+1, k)]
                        n5 = node_map[(i, j, k+1)]
                        n6 = node_map[(i+1, j, k+1)]
                        n7 = node_map[(i+1, j+1, k+1)]
                        n8 = node_map[(i, j+1, k+1)]
                        f.write(f"{zone_id}, {n1}, {n2}, {n3}, {n4}, {n5}, {n6}, {n7}, {n8}\n")
                        zone_id += 1
            f.write("*END PART\n")
        logger.info(f"Abaqus mesh successfully exported to {filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to export to Abaqus: {e}")
        raise e
