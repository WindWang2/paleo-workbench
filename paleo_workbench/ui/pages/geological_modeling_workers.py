"""Background QThread workers for the 3D geological modeling workbench.

Extracted from geological_modeling_3d_page.py to avoid the Divergent Change smell —
each worker changes for its own reason (data generation, export format, advisor logic).
"""
from __future__ import annotations

import logging
import time
import numpy as np

from PySide6.QtCore import QObject, Signal

from geoviz import (
    generate_cylinder_geometry,
    generate_fault_geometry,
    generate_tube_geometry,
)
from paleo_workbench.viz.geomodel.models import GridSpec

logger = logging.getLogger(__name__)


class GeologicalModelingWorker(QObject):
    """Asynchronous worker for CPU-heavy 3D geological modeling geometry generation.

    The volume / borehole / tunnel / fault geometry is SYNTHETIC DEMO data
    (formula volume + hardcoded records), so the result is explicitly marked
    ``demo=True`` / ``source="synthetic/demo"`` and the page shows a Demo
    badge. A future real-data worker must pass ``demo=False`` and provide a
    real input provenance (P3 structural split).
    """
    completed = Signal(dict)
    failed = Signal(str)
    progress = Signal(int)
    terminal = Signal()

    def __init__(self, density: str, algorithm: str, parent=None, *, demo: bool = True):
        super().__init__(parent)
        self.density = density
        self.algorithm = algorithm
        self.demo = demo

    def run(self) -> None:
        try:
            self.progress.emit(10)
            time.sleep(0.2)
            self.progress.emit(30)

            # Determine volume grid resolution
            if "低" in self.density:
                dim = 40
            elif "中" in self.density:
                dim = 80
            else:
                dim = 120

            # Vectorized volume generation (eliminates pure-Python triple loop)
            ii, jj, kk = np.meshgrid(
                np.arange(dim), np.arange(dim), np.arange(dim), indexing="ij"
            )
            val = kk + 8.0 * np.sin(ii / 8.0) * np.cos(jj / 8.0)
            vol_data = ((val / dim) * 255).astype(np.uint8) % 256

            self.progress.emit(60)
            time.sleep(0.1)

            # 1. Borehole raw data & geometry
            bh_raw = [
                {
                    "name": "钻孔 HZ21-1", "x": -40.0, "y": -40.0, "total_depth": 150.0,
                    "layers": [
                        {"top": 0.0, "bottom": 30.0, "lithology": "砂岩", "color": (0.8, 0.6, 0.4, 0.8)},
                        {"top": 30.0, "bottom": 75.0, "lithology": "泥岩", "color": (0.5, 0.5, 0.5, 0.8)},
                        {"top": 75.0, "bottom": 120.0, "lithology": "石灰岩", "color": (0.4, 0.7, 0.9, 0.8)},
                        {"top": 120.0, "bottom": 150.0, "lithology": "花岗岩", "color": (0.9, 0.4, 0.4, 0.8)},
                    ]
                },
                {
                    "name": "钻孔 HZ19-6", "x": 40.0, "y": -40.0, "total_depth": 180.0,
                    "layers": [
                        {"top": 0.0, "bottom": 40.0, "lithology": "砂岩", "color": (0.8, 0.6, 0.4, 0.8)},
                        {"top": 40.0, "bottom": 90.0, "lithology": "泥岩", "color": (0.5, 0.5, 0.5, 0.8)},
                        {"top": 90.0, "bottom": 140.0, "lithology": "石灰岩", "color": (0.4, 0.7, 0.9, 0.8)},
                        # Intentional depth overlap check warning
                        {"top": 135.0, "bottom": 180.0, "lithology": "花岗岩", "color": (0.9, 0.4, 0.4, 0.8)},
                    ]
                },
                {
                    "name": "钻孔 XJ24-3", "x": -40.0, "y": 40.0, "total_depth": 200.0,
                    "layers": [
                        {"top": 0.0, "bottom": 50.0, "lithology": "砂岩", "color": (0.8, 0.6, 0.4, 0.8)},
                        {"top": 50.0, "bottom": 110.0, "lithology": "泥岩", "color": (0.5, 0.5, 0.5, 0.8)},
                        {"top": 110.0, "bottom": 160.0, "lithology": "石灰岩", "color": (0.4, 0.7, 0.9, 0.8)},
                        {"top": 160.0, "bottom": 200.0, "lithology": "花岗岩", "color": (0.9, 0.4, 0.4, 0.8)},
                    ]
                },
                {
                    "name": "钻孔 HZ25-2", "x": 40.0, "y": 40.0, "total_depth": 160.0,
                    "layers": [
                        {"top": 0.0, "bottom": 35.0, "lithology": "砂岩", "color": (0.8, 0.6, 0.4, 0.8)},
                        {"top": 35.0, "bottom": 80.0, "lithology": "泥岩", "color": (0.5, 0.5, 0.5, 0.8)},
                        {"top": 80.0, "bottom": 130.0, "lithology": "石灰岩", "color": (0.4, 0.7, 0.9, 0.8)},
                        # Exceeds total depth check warning
                        {"top": 130.0, "bottom": 168.0, "lithology": "花岗岩", "color": (0.9, 0.4, 0.4, 0.8)},
                    ]
                }
            ]

            bh_geom = []
            for bh in bh_raw:
                bx, by = bh["x"], bh["y"]
                for lyr in bh["layers"]:
                    t = lyr["top"]
                    b = lyr["bottom"]
                    p1 = (bx, by, -t)
                    p2 = (bx, by, -b)
                    v, f, c = generate_cylinder_geometry(p1, p2, radius=2.5, color=lyr["color"])
                    bh_geom.append({"name": bh["name"], "v": v, "f": f, "c": c})

            self.progress.emit(80)

            # 2. Tunnels raw data & geometry
            tunnel_raw = [
                {
                    "name": "巷道 A",
                    "path": [[-50.0, -20.0, -30.0], [0.0, 0.0, -40.0], [50.0, 20.0, -50.0]],
                    "color": (0.2, 0.8, 0.2, 0.9)
                },
                {
                    "name": "巷道 B",
                    "path": [[-30.0, 50.0, -20.0], [20.0, 10.0, -35.0], [60.0, -30.0, -55.0]],
                    "color": (0.8, 0.8, 0.2, 0.9)
                }
            ]

            t_geom = []
            for tn in tunnel_raw:
                v, f, c = generate_tube_geometry(tn["path"], radius=3.5, color=tn["color"])
                t_geom.append({"name": tn["name"], "v": v, "f": f, "c": c})

            # 3. Faults raw data & geometry
            faults_raw = [
                {"name": "断层 F1 Surface", "normal": (1.0, 0.5, 0.2), "d": -20.0, "color": (0.9, 0.2, 0.2, 0.65)},
                {"name": "断层 F2 Surface", "normal": (0.98, 0.52, 0.18), "d": -25.0, "color": (0.9, 0.2, 0.5, 0.65)}
            ]

            f_geom = []
            v1, f1, c1 = generate_fault_geometry(xlim=(-60, 60), ylim=(-60, 60), color=faults_raw[0]["color"])
            v1[:, 2] += 20.0
            f_geom.append({"name": faults_raw[0]["name"], "v": v1, "f": f1, "c": c1})
            v2, f2, c2 = generate_fault_geometry(xlim=(-60, 60), ylim=(-60, 60), color=faults_raw[1]["color"])
            v2[:, 2] += 12.0
            f_geom.append({"name": faults_raw[1]["name"], "v": v2, "f": f2, "c": c2})

            self.progress.emit(95)
            time.sleep(0.1)
            self.progress.emit(100)

            self.completed.emit({
                "volume_data": vol_data,
                "boreholes": bh_geom,
                "tunnels": t_geom,
                "faults": f_geom,
                "bh_raw": bh_raw,
                "faults_raw": faults_raw,
                "demo": self.demo,
                "source": "synthetic/demo" if self.demo else "real_data",
                "algorithm": self.algorithm,
            })
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.terminal.emit()


class ExportWorker(QObject):
    """Asynchronous worker for grid exporting to avoid UI freezing."""
    completed = Signal(str)
    failed = Signal(str)
    terminal = Signal()

    def __init__(self, filename: str, mode: str, grid_spec: GridSpec, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.mode = mode
        self.grid_spec = grid_spec

    def run(self) -> None:
        from paleo_workbench.viz.geomodel.exporters import export_to_flac3d, export_to_abaqus
        try:
            time.sleep(0.6)  # Simulated export latency
            spec = self.grid_spec
            if self.mode == "flac3d":
                export_to_flac3d(self.filename, spec.nx, spec.ny, spec.nz, spec.dx, spec.dy, spec.dz)
            else:
                export_to_abaqus(self.filename, spec.nx, spec.ny, spec.nz, spec.dx, spec.dy, spec.dz)
            self.completed.emit(self.filename)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.terminal.emit()


class AdvisorWorker(QObject):
    """Asynchronous worker for rule-based data consistency analysis."""
    completed = Signal(dict, dict)
    failed = Signal(str)
    terminal = Signal()

    def __init__(self, bh_data: list, faults_data: list, parent=None):
        super().__init__(parent)
        self.bh_data = bh_data
        self.faults_data = faults_data

    def run(self) -> None:
        from paleo_workbench.viz.geomodel.advisor import check_boreholes, check_coplanar_faults
        try:
            time.sleep(0.5)  # Simulated analysis latency (UI affordance)
            bh_report = check_boreholes(self.bh_data)
            fault_report = check_coplanar_faults(self.faults_data)
            self.completed.emit(bh_report, fault_report)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.terminal.emit()
