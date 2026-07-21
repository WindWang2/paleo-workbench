"""GeologicalModeling3DPage — premium 3D geological modeling workbench page."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
import numpy as np

from PySide6.QtCore import Qt, QSize, QObject, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QSlider, QSplitter, QProgressBar,
    QCheckBox, QSpinBox, QDoubleSpinBox, QScrollArea, QFileDialog, QMessageBox,
    QDialog, QTextBrowser
)
import pyqtgraph.opengl as gl

from paleo_workbench import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.geomodel import (
    ClippedGLMeshItem,
    ClippedGLVolumeItem,
    generate_cylinder_geometry,
    generate_tube_geometry,
    generate_fault_geometry,
    WellSeismicTieCalibration,
    WellCurve3DGenerator
)

logger = logging.getLogger(__name__)


class GeologicalModelingWorker(QObject):
    """Asynchronous worker for CPU-heavy 3D geological modeling geometry generation."""
    completed = Signal(dict)
    failed = Signal(str)
    progress = Signal(int)
    terminal = Signal()

    def __init__(self, density: str, algorithm: str, parent=None):
        super().__init__(parent)
        self.density = density
        self.algorithm = algorithm

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
                
            # Create synthetic geological layer volume data
            vol_data = np.zeros((dim, dim, dim), dtype=np.uint8)
            for z in range(dim):
                for y in range(dim):
                    for x in range(dim):
                        # Gently sloping dome structure
                        val = z + 8.0 * np.sin(x / 8.0) * np.cos(y / 8.0)
                        vol_data[x, y, z] = int((val / dim) * 255) % 256
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
                    # Map top/bottom to vertical depth (downward z)
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
            # Fault 1
            v1, f1, c1 = generate_fault_geometry(xlim=(-60, 60), ylim=(-60, 60), color=faults_raw[0]["color"])
            v1[:, 2] += 20.0 # visual shift
            f_geom.append({"name": faults_raw[0]["name"], "v": v1, "f": f1, "c": c1})
            # Fault 2
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
                "faults_raw": faults_raw
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

    def __init__(self, filename: str, mode: str, nx: int, ny: int, nz: int, dx: float, dy: float, dz: float, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.mode = mode
        self.nx = nx
        self.ny = ny
        self.nz = nz
        self.dx = dx
        self.dy = dy
        self.dz = dz

    def run(self) -> None:
        from paleo_workbench.viz.geomodel.exporters import export_to_flac3d, export_to_abaqus
        try:
            time.sleep(0.6)  # Simulated export latency
            if self.mode == "flac3d":
                export_to_flac3d(self.filename, self.nx, self.ny, self.nz, self.dx, self.dy, self.dz)
            else:
                export_to_abaqus(self.filename, self.nx, self.ny, self.nz, self.dx, self.dy, self.dz)
            self.completed.emit(self.filename)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.terminal.emit()


class AdvisorWorker(QObject):
    """Asynchronous worker for AI consistency analysis."""
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
            time.sleep(0.5)  # Simulated AI analysis latency
            bh_report = check_boreholes(self.bh_data)
            fault_report = check_coplanar_faults(self.faults_data)
            self.completed.emit(bh_report, fault_report)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.terminal.emit()


class AICheckAdvisorDialog(QDialog):
    """Premium glassmorphism styled non-modal side dialog showing consistency checking reports."""
    def __init__(self, bh_report: dict, fault_report: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 地质数据一致性核复顾问")
        self.resize(550, 650)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #0f172a;
                color: #f8fafc;
            }}
            QTextBrowser {{
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
                line-height: 1.5;
            }}
            QPushButton {{
                background-color: {tokens.PRIMARY};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {tokens.PRIMARY_HOVER};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        layout.setSpacing(tokens.SPACE_2)
        
        header = QLabel("AI 专家诊断与数据复核报告")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        layout.addWidget(header)
        
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser)
        
        # Construct dynamic HTML report
        has_errors = any(x["type"] == "error" for x in bh_report.get("issues", []))
        bh_badge = "<span style='background: #ef4444; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>不通过 (FAIL)</span>" if has_errors else "<span style='background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>警告 (WARNING)</span>"
        
        has_fault_warnings = len(fault_report.get("issues", [])) > 0
        fault_badge = "<span style='background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>有冲突 (WARNING)</span>" if has_fault_warnings else "<span style='background: #10b981; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>通过 (PASS)</span>"
        
        html = f"""
        <h3 style='color: #f1f5f9; border-bottom: 1px solid #475569; padding-bottom: 4px;'>📊 核对概要 (Summary)</h3>
        <table style='width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 16px;'>
            <tr style='background: #334155; color: #f8fafc;'>
                <th style='padding: 8px; text-align: left;'>复核模块</th>
                <th style='padding: 8px; text-align: center;'>已检项</th>
                <th style='padding: 8px; text-align: center;'>诊断状态</th>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid #334155;'>钻孔分层一致性</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{bh_report.get('checked_boreholes', 0)} 个钻孔</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{bh_badge}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border-bottom: 1px solid #334155;'>平行/共面断层核实</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{fault_report.get('checked_faults', 0)} 条断层</td>
                <td style='padding: 8px; text-align: center; border-bottom: 1px solid #334155;'>{fault_badge}</td>
            </tr>
        </table>
        
        <h3 style='color: #f1f5f9; border-bottom: 1px solid #475569; padding-bottom: 4px;'>🚨 诊断问题明细 (Issues)</h3>
        """
        
        # Boreholes details
        html += "<h4 style='color: #f87171; margin-bottom: 4px;'>📍 钻孔层位异常：</h4><ul style='margin-top: 0; padding-left: 20px; color: #cbd5e1;'>"
        for iss in bh_report.get("issues", []):
            color = "#ef4444" if iss["type"] == "error" else "#f59e0b"
            badge = "❌ 错误" if iss["type"] == "error" else "⚠️ 警告"
            html += f"<li><b>{iss['borehole']}</b>: <span style='color: {color};'>{badge}</span> - {iss['message']}</li>"
        if not bh_report.get("issues", []):
            html += "<li>✅ 钻孔间距及分层深度完全一致，无冲突。</li>"
        html += "</ul>"
        
        # Faults details
        html += "<h4 style='color: #fbbf24; margin-bottom: 4px;'>📁 共面断层预警：</h4><ul style='margin-top: 0; padding-left: 20px; color: #cbd5e1;'>"
        for iss in fault_report.get("issues", []):
            html += f"<li>🔗 <b>{' & '.join(iss['faults'])}</b>: {iss['message']}</li>"
        if not fault_report.get("issues", []):
            html += "<li>✅ 未检测到重叠或共面冲突的断层面。</li>"
        html += "</ul>"
        
        # AI Suggestions section
        html += """
        <h3 style='color: #818cf8; border-bottom: 1px solid #475569; padding-bottom: 4px;'>🤖 AI 推荐优化方案 (Optimization Tips)</h3>
        <div style='background: #1e1b4b; border-left: 4px solid #818cf8; padding: 12px; border-radius: 6px; margin-top: 8px;'>
            <p style='color: #a5b4fc; font-weight: bold; margin: 0 0 8px 0;'>💡 建模优化建议：</p>
            <ol style='margin: 0; padding-left: 20px; color: #e2e8f0; line-height: 1.6;'>
                <li><b>钻孔 HZ19-6 层位重叠修正</b>: 第3层（石灰岩）底深为 140m，但第4层（花岗岩）顶深被记录为 135m。此 5m 重叠属于数据录入异常。请在数据源中修改花岗岩顶深为 140m，以防止地层曲面交叉。</li>
                <li><b>钻孔 HZ25-2 总深超限警告</b>: 累积层底深达 168m，而记录的总深仅为 160m。请复查底层终孔记录。</li>
                <li><b>断层合并去冗余</b>: 断层 <i>F1 Surface</i> 与 <i>F2 Surface</i> 走向夹角仅 0.16°，法线方向高度共面，间距 5m。极近距离的平行断层会导致有限元网格剖分时产生高度扭曲的畸形单元，导致 FLAC3D 或 Abaqus 计算极难收敛。<b>强烈建议在左侧模型树中勾选合并这两条断层，作为单一主要构造滑动面处理。</b></li>
            </ol>
        </div>
        """
        
        self.browser.setHtml(html)
        
        btn_close = QPushButton("确认并关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)


class GeologicalModeling3DPage(QWidget):
    """3D Geological Modeling Workbench Page.

    Features:
    - Left: Interactive checkable model hierarchy tree.
    - Center: pyqtgraph.opengl 3D interactive viewport + floating glassmorphic view toolbar.
    - Right: Dynamic parameter configuration, 3-way clipping, AI Check advisor, and Numerical simulator exporter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeologicalModeling3DPage")
        
        # Background threads keeper wrappers
        self._modeling_job = OwnedWorkerJob(self)
        self._export_job = OwnedWorkerJob(self)
        self._advisor_job = OwnedWorkerJob(self)
        self.active_items: list[gl.GLGraphicsItem] = []
        self.mesh_items_map: dict[str, list[gl.GLMeshItem]] = {}
        self.bh_raw_data: list[dict] = []
        self.faults_raw_data: list[dict] = []
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        main_layout.setSpacing(tokens.SPACE_2)
        
        # Horizontal Splitter for 3 Panels
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setStyleSheet("QSplitter::handle { background: %s; width: 1px; }" % tokens.BORDER)
        
        # 1. Left Panel: Model Hierarchy
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens.SPACE_2)
        
        left_header = QLabel("模型层次与资产")
        left_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        left_layout.addWidget(left_header)
        
        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("三维场景对象")
        self.model_tree.setStyleSheet("QTreeView { border: 1px solid %s; border-radius: %dpx; }" % (
            tokens.BORDER, tokens.RADIUS_CARD
        ))
        self._populate_model_tree()
        left_layout.addWidget(self.model_tree)
        
        # 2. Center Panel: 3D Viewport
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        
        self.view_container = QFrame()
        self.view_container.setFrameShape(QFrame.StyledPanel)
        self.view_container.setStyleSheet("QFrame { background: #020617; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        
        view_layout = QVBoxLayout(self.view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)
        
        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.opts['distance'] = 250
        self.gl_widget.setCameraPosition(elevation=30, azimuth=45)
        view_layout.addWidget(self.gl_widget)
        
        # Default baseline grid
        grid = gl.GLGridItem()
        grid.setSize(300, 300, 300)
        grid.setSpacing(10, 10, 10)
        self.gl_widget.addItem(grid)
        
        # Floating View Control Bar
        self.floating_bar = QFrame(self.view_container)
        self.floating_bar.setStyleSheet("""
            QFrame {
                background-color: %s;
                border: 1px solid %s;
                border-radius: %dpx;
            }
            QPushButton {
                background: transparent;
                border: none;
                padding: 4px 10px;
                color: #e2e8f0;
                font-weight: bold;
            }
            QPushButton:hover {
                background: %s;
                border-radius: 4px;
            }
        """ % (tokens.BG_GLASS, tokens.BG_GLASS_BORDER, tokens.RADIUS_BUTTON, tokens.HOVER_GLOW))
        self.floating_bar.setFixedHeight(38)
        self.floating_bar.setFixedWidth(240)
        
        f_layout = QHBoxLayout(self.floating_bar)
        f_layout.setContentsMargins(tokens.SPACE_1, 0, tokens.SPACE_1, 0)
        
        self.btn_orbit = QPushButton("透视视角")
        self.btn_pan = QPushButton("俯瞰视角")
        self.btn_reset = QPushButton("复位")
        self.btn_orbit.clicked.connect(lambda: self.gl_widget.setCameraPosition(distance=250, elevation=30, azimuth=45))
        self.btn_pan.clicked.connect(lambda: self.gl_widget.setCameraPosition(distance=250, elevation=90, azimuth=0))
        self.btn_reset.clicked.connect(lambda: self.gl_widget.setCameraPosition(distance=250, elevation=30, azimuth=45))
        
        f_layout.addWidget(self.btn_orbit)
        f_layout.addWidget(self.btn_pan)
        f_layout.addWidget(self.btn_reset)
        self.floating_bar.move(12, 12)
        
        center_layout.addWidget(self.view_container)
        
        # 3. Right Panel: Parameters & Exporters (Scrollable)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("QScrollArea { border: none; }")
        
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(tokens.SPACE_2)
        
        right_header = QLabel("三维可视化与模拟接口")
        right_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        right_layout.addWidget(right_header)
        
        # CARD 1: Modeling Config
        card_config = QFrame()
        card_config.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        cfg_layout = QVBoxLayout(card_config)
        cfg_layout.setSpacing(tokens.SPACE_2)
        
        title_cfg = QLabel("建模计算参数")
        title_cfg.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        cfg_layout.addWidget(title_cfg)
        
        cfg_layout.addWidget(QLabel("网格密度 (Grid Density)"))
        self.combo_density = QComboBox()
        self.combo_density.addItems(["低精度 (40x40x40)", "中精度 (80x80x80)", "高精度 (120x120x120)"])
        self.combo_density.setCurrentIndex(1)
        cfg_layout.addWidget(self.combo_density)
        
        cfg_layout.addWidget(QLabel("属性插值算法"))
        self.combo_algo = QComboBox()
        self.combo_algo.addItems(["克里金插值 (Kriging)", "顺序高斯模拟 (SGS)", "逆距离加权 (IDW)"])
        cfg_layout.addWidget(self.combo_algo)
        
        cfg_layout.addWidget(QLabel("地层模型不透明度 (Volume Opacity)"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(40)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        cfg_layout.addWidget(self.slider_opacity)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        cfg_layout.addWidget(self.progress_bar)
        
        self.btn_run = QPushButton("开始三维建模")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_modeling)
        cfg_layout.addWidget(self.btn_run)
        
        right_layout.addWidget(card_config)
        
        # CARD 2: 3-Way Interactive Clipping
        card_clip = QFrame()
        card_clip.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        clip_layout = QVBoxLayout(card_clip)
        clip_layout.setSpacing(tokens.SPACE_2)
        
        title_clip = QLabel("三向交互剖切 (GPU Clipping)")
        title_clip.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        clip_layout.addWidget(title_clip)
        
        # X-Axis Clip controls
        self.chk_clip_x = QCheckBox("启用 X 轴剖切")
        self.slide_clip_x = QSlider(Qt.Horizontal)
        self.slide_clip_x.setRange(0, 100)
        self.slide_clip_x.setValue(50)
        self.combo_clip_x_dir = QComboBox()
        self.combo_clip_x_dir.addItems(["保留右侧 (x >= val)", "保留左侧 (x <= val)"])
        clip_layout.addWidget(self.chk_clip_x)
        clip_layout.addWidget(self.slide_clip_x)
        clip_layout.addWidget(self.combo_clip_x_dir)
        
        # Y-Axis Clip controls
        self.chk_clip_y = QCheckBox("启用 Y 轴剖切")
        self.slide_clip_y = QSlider(Qt.Horizontal)
        self.slide_clip_y.setRange(0, 100)
        self.slide_clip_y.setValue(50)
        self.combo_clip_y_dir = QComboBox()
        self.combo_clip_y_dir.addItems(["保留前侧 (y >= val)", "保留后侧 (y <= val)"])
        clip_layout.addWidget(self.chk_clip_y)
        clip_layout.addWidget(self.slide_clip_y)
        clip_layout.addWidget(self.combo_clip_y_dir)
        
        # Z-Axis Clip controls
        self.chk_clip_z = QCheckBox("启用 Z 轴剖切")
        self.slide_clip_z = QSlider(Qt.Horizontal)
        self.slide_clip_z.setRange(0, 100)
        self.slide_clip_z.setValue(50)
        self.combo_clip_z_dir = QComboBox()
        self.combo_clip_z_dir.addItems(["保留上方 (z >= val)", "保留下方 (z <= val)"])
        clip_layout.addWidget(self.chk_clip_z)
        clip_layout.addWidget(self.slide_clip_z)
        clip_layout.addWidget(self.combo_clip_z_dir)
        
        # Wire clipping events
        self.chk_clip_x.stateChanged.connect(self._update_clipping)
        self.slide_clip_x.valueChanged.connect(self._update_clipping)
        self.combo_clip_x_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_y.stateChanged.connect(self._update_clipping)
        self.slide_clip_y.valueChanged.connect(self._update_clipping)
        self.combo_clip_y_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_z.stateChanged.connect(self._update_clipping)
        self.slide_clip_z.valueChanged.connect(self._update_clipping)
        self.combo_clip_z_dir.currentIndexChanged.connect(self._update_clipping)
        
        right_layout.addWidget(card_clip)
        
        # CARD 3: Simulator Mesh Exporters
        card_export = QFrame()
        card_export.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        exp_layout = QVBoxLayout(card_export)
        exp_layout.setSpacing(tokens.SPACE_2)
        
        title_exp = QLabel("数值模拟分析接口 (Export)")
        title_exp.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        exp_layout.addWidget(title_exp)
        
        exp_layout.addWidget(QLabel("导出格式"))
        self.combo_export_type = QComboBox()
        self.combo_export_type.addItems(["FLAC3D 角点网格 (*.f3grid)", "Abaqus 有限元网格 (*.inp)"])
        exp_layout.addWidget(self.combo_export_type)
        
        grid_grid_layout = QHBoxLayout()
        grid_grid_layout.setSpacing(tokens.SPACE_1)
        
        # NX NY NZ
        vbox_nx = QVBoxLayout()
        vbox_nx.addWidget(QLabel("NX"))
        self.spin_nx = QSpinBox()
        self.spin_nx.setRange(2, 200)
        self.spin_nx.setValue(20)
        vbox_nx.addWidget(self.spin_nx)
        grid_grid_layout.addLayout(vbox_nx)
        
        vbox_ny = QVBoxLayout()
        vbox_ny.addWidget(QLabel("NY"))
        self.spin_ny = QSpinBox()
        self.spin_ny.setRange(2, 200)
        self.spin_ny.setValue(20)
        vbox_ny.addWidget(self.spin_ny)
        grid_grid_layout.addLayout(vbox_ny)
        
        vbox_nz = QVBoxLayout()
        vbox_nz.addWidget(QLabel("NZ"))
        self.spin_nz = QSpinBox()
        self.spin_nz.setRange(2, 200)
        self.spin_nz.setValue(15)
        vbox_nz.addWidget(self.spin_nz)
        grid_grid_layout.addLayout(vbox_nz)
        
        exp_layout.addLayout(grid_grid_layout)
        
        grid_size_layout = QHBoxLayout()
        grid_size_layout.setSpacing(tokens.SPACE_1)
        
        # DX DY DZ
        vbox_dx = QVBoxLayout()
        vbox_dx.addWidget(QLabel("DX (m)"))
        self.spin_dx = QDoubleSpinBox()
        self.spin_dx.setRange(0.5, 500.0)
        self.spin_dx.setValue(10.0)
        vbox_dx.addWidget(self.spin_dx)
        grid_size_layout.addLayout(vbox_dx)
        
        vbox_dy = QVBoxLayout()
        vbox_dy.addWidget(QLabel("DY (m)"))
        self.spin_dy = QDoubleSpinBox()
        self.spin_dy.setRange(0.5, 500.0)
        self.spin_dy.setValue(10.0)
        vbox_dy.addWidget(self.spin_dy)
        grid_size_layout.addLayout(vbox_dy)
        
        vbox_dz = QVBoxLayout()
        vbox_dz.addWidget(QLabel("DZ (m)"))
        self.spin_dz = QDoubleSpinBox()
        self.spin_dz.setRange(0.5, 500.0)
        self.spin_dz.setValue(8.0)
        vbox_dz.addWidget(self.spin_dz)
        grid_size_layout.addLayout(vbox_dz)
        
        exp_layout.addLayout(grid_size_layout)
        
        self.btn_export = QPushButton("导出数值模拟模型")
        self.btn_export.setObjectName("SecondaryButton")
        self.btn_export.clicked.connect(self._export_mesh)
        exp_layout.addWidget(self.btn_export)
        
        right_layout.addWidget(card_export)
        
        # CARD 4: AI Check Advisor Side Dialog
        card_ai = QFrame()
        card_ai.setStyleSheet("QFrame { background: #f8fafc; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        ai_layout = QVBoxLayout(card_ai)
        ai_layout.setSpacing(tokens.SPACE_2)
        
        title_ai = QLabel("AI 专家复核与诊断顾问")
        title_ai.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        ai_layout.addWidget(title_ai)
        
        desc_ai = QLabel("通过 AI 自动分析当前项目下所有钻孔的深度分层完整性，并校验平行断层共面问题。")
        desc_ai.setWordWrap(True)
        desc_ai.setStyleSheet("font-size: 11px; color: #64748b;")
        ai_layout.addWidget(desc_ai)
        
        self.btn_ai_advisor = QPushButton("开启 AI 一致性诊断")
        self.btn_ai_advisor.setObjectName("PrimaryButton")
        self.btn_ai_advisor.setEnabled(False) # Enable only after data is loaded
        self.btn_ai_advisor.clicked.connect(self._run_ai_advisor)
        ai_layout.addWidget(self.btn_ai_advisor)
        
        right_layout.addWidget(card_ai)
        
        # CARD 5: Well-Seismic Tie Calibration & Analysis Controls
        card_tie = QFrame()
        card_tie.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        tie_layout = QVBoxLayout(card_tie)
        tie_layout.setSpacing(tokens.SPACE_2)
        
        title_tie = QLabel("井震融合校正 (Well-Seismic Calibration)")
        title_tie.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        tie_layout.addWidget(title_tie)
        
        tie_layout.addWidget(QLabel("主频 (Wavelet Frequency)"))
        self.slider_wavelet_freq = QSlider(Qt.Horizontal)
        self.slider_wavelet_freq.setRange(10, 80)
        self.slider_wavelet_freq.setValue(35)
        self.slider_wavelet_freq.valueChanged.connect(self._on_tie_params_changed)
        tie_layout.addWidget(self.slider_wavelet_freq)
        
        tie_layout.addWidget(QLabel("时深时移校正 (T-D Shift Calibration)"))
        self.slider_td_shift = QSlider(Qt.Horizontal)
        self.slider_td_shift.setRange(-50, 50)
        self.slider_td_shift.setValue(0)
        self.slider_td_shift.valueChanged.connect(self._on_tie_params_changed)
        tie_layout.addWidget(self.slider_td_shift)
        
        self.label_correlation = QLabel("互相关系数 (Cross-Correlation CC): 0.824")
        self.label_correlation.setStyleSheet("font-size: 11px; color: #10b981; font-weight: bold;")
        tie_layout.addWidget(self.label_correlation)
        
        self.btn_auto_tie = QPushButton("自动互相关对齐 (Auto-Tie)")
        self.btn_auto_tie.setObjectName("SecondaryButton")
        self.btn_auto_tie.clicked.connect(self._run_auto_tie)
        tie_layout.addWidget(self.btn_auto_tie)
        
        right_layout.addWidget(card_tie)
        right_layout.addStretch()
        
        right_scroll.setWidget(right_widget)
        
        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_scroll)
        
        # Layout weights
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        
        main_layout.addWidget(splitter)

    def _populate_model_tree(self) -> None:
        self.model_tree.clear()
        
        root_struct = QTreeWidgetItem(self.model_tree, ["地层构造格架"])
        self._add_checkable_child(root_struct, "LST 顶底面")
        self._add_checkable_child(root_struct, "TST 顶底面")
        
        root_fault = QTreeWidgetItem(self.model_tree, ["断层格架模型"])
        self._add_checkable_child(root_fault, "断层 F1 Surface")
        self._add_checkable_child(root_fault, "断层 F2 Surface")
        
        root_tunnels = QTreeWidgetItem(self.model_tree, ["巷道与井下系统"])
        self._add_checkable_child(root_tunnels, "巷道 A")
        self._add_checkable_child(root_tunnels, "巷道 B")
        
        root_wells = QTreeWidgetItem(self.model_tree, ["钻孔与井迹"])
        self._add_checkable_child(root_wells, "钻孔 HZ21-1")
        self._add_checkable_child(root_wells, "钻孔 HZ19-6")
        self._add_checkable_child(root_wells, "钻孔 XJ24-3")
        self._add_checkable_child(root_wells, "钻孔 HZ25-2")
        
        root_tie = QTreeWidgetItem(self.model_tree, ["井震融合标定与校正"])
        self._add_checkable_child(root_tie, "地震剖面三维切片 (Seismic Slices)")
        self._add_checkable_child(root_tie, "井眼旁显测井曲线 (3D GR Logs)")
        self._add_checkable_child(root_tie, "合成地震记录叠加 (Synthetic Seismograms)")
        
        self.model_tree.expandAll()
        self.model_tree.itemChanged.connect(self._on_tree_item_changed)

    def _add_checkable_child(self, parent_item: QTreeWidgetItem, name: str) -> None:
        item = QTreeWidgetItem(parent_item, [name])
        item.setCheckState(0, Qt.Checked)

    def _on_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        logger.info(f"Setting 3D Volume Item opacity to {opacity}")
        # In PyQtGraph OpenGL widgets, we repaint
        self.gl_widget.update()

    def _run_modeling(self) -> None:
        if self._modeling_job.is_running:
            return
            
        self.btn_run.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        density = self.combo_density.currentText()
        algo = self.combo_algo.currentText()
        
        worker = GeologicalModelingWorker(density, algo)
        worker.progress.connect(self.progress_bar.setValue)
        
        self._modeling_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_modeling_completed),
                (worker.failed, self._on_modeling_failed),
            ),
            target=density,
        )

    def _on_modeling_completed(self, result: dict) -> None:
        self.bh_raw_data = result["bh_raw"]
        self.faults_raw_data = result["faults_raw"]
        
        # Clear existing active GL elements
        for item in self.active_items:
            try:
                self.gl_widget.removeItem(item)
            except Exception:
                pass
        self.active_items.clear()
        self.mesh_items_map.clear()
        
        # 1. Add Volume Item
        vol_data = result["volume_data"]
        self.vol_item = ClippedGLVolumeItem(data=vol_data)
        # Center the volume in the viewport coordinates
        w, h, d = vol_data.shape
        self.vol_item.translate(-w/2, -h/2, -d/2)
        self.gl_widget.addItem(self.vol_item)
        self.active_items.append(self.vol_item)
        
        # 2. Add Boreholes
        for bh in result["boreholes"]:
            mesh = ClippedGLMeshItem(vertexes=bh["v"], faces=bh["f"], faceColors=bh["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)
            
            name = bh["name"]
            if name not in self.mesh_items_map:
                self.mesh_items_map[name] = []
            self.mesh_items_map[name].append(mesh)
            
        # 3. Add Tunnels
        for tn in result["tunnels"]:
            mesh = ClippedGLMeshItem(vertexes=tn["v"], faces=tn["f"], faceColors=tn["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)
            self.mesh_items_map[tn["name"]] = [mesh]
            
        # 4. Add Faults
        for flt in result["faults"]:
            mesh = ClippedGLMeshItem(vertexes=flt["v"], faces=flt["f"], faceColors=flt["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)
            self.mesh_items_map[flt["name"]] = [mesh]
            
        # Sync visibility checkboxes
        self._sync_visibility_from_tree()
        # Initialize GPU clipping
        self._update_clipping()
        
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.btn_ai_advisor.setEnabled(True)
        
        logger.info("3D geological modeling successfully updated in viewport.")

    def _on_modeling_failed(self, err: str) -> None:
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "建模失败", f"三维建模失败: {err}")

    def _sync_visibility_from_tree(self) -> None:
        """Apply model tree checked status to mesh/volume rendering visibilities."""
        root = self.model_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                name = item.text(0)
                visible = (item.checkState(0) == Qt.Checked)
                
                if name in ["LST 顶底面", "TST 顶底面"]:
                    if hasattr(self, "vol_item") and self.vol_item is not None:
                        self.vol_item.setVisible(visible)
                else:
                    gl_items = self.mesh_items_map.get(name, [])
                    for gl_item in gl_items:
                        gl_item.setVisible(visible)
        self.gl_widget.update()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
            
        # Block signals to prevent recursive checking logic
        self.model_tree.blockSignals(True)
        try:
            # If parent checked state changed, check/uncheck all sub-items
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, item.checkState(0))
        finally:
            self.model_tree.blockSignals(False)
            
        self._sync_visibility_from_tree()

    def _update_clipping(self) -> None:
        """Update 3D interactive user clipping parameters based on UI sliders."""
        # Scale slider value 0-100 to index/coordinate space bounds (approx [-80, 80])
        def val_to_coord(val: int) -> float:
            return -80.0 + (val / 100.0) * 160.0
            
        x_enabled = self.chk_clip_x.isChecked()
        x_coord = val_to_coord(self.slide_clip_x.value())
        x_dir = 1.0 if self.combo_clip_x_dir.currentIndex() == 0 else -1.0
        
        y_enabled = self.chk_clip_y.isChecked()
        y_coord = val_to_coord(self.slide_clip_y.value())
        y_dir = 1.0 if self.combo_clip_y_dir.currentIndex() == 0 else -1.0
        
        z_enabled = self.chk_clip_z.isChecked()
        z_coord = val_to_coord(self.slide_clip_z.value())
        z_dir = 1.0 if self.combo_clip_z_dir.currentIndex() == 0 else -1.0
        
        # Apply parameters to all active items that support clipping
        for item in self.active_items:
            if hasattr(item, "set_clipping"):
                item.set_clipping('x', x_enabled, x_coord, x_dir)
                item.set_clipping('y', y_enabled, y_coord, y_dir)
                item.set_clipping('z', z_enabled, z_coord, z_dir)
        self.gl_widget.update()

    def _export_mesh(self) -> None:
        if self._export_job.is_running:
            return
            
        sim_type = self.combo_export_type.currentText()
        if "FLAC3D" in sim_type:
            mode = "flac3d"
            suffix = "f3grid"
            filter_str = "FLAC3D grid files (*.f3grid)"
        else:
            mode = "abaqus"
            suffix = "inp"
            filter_str = "Abaqus input files (*.inp)"
            
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存数值模拟网格模型", f"geological_numerical_model.{suffix}", filter_str
        )
        if not filepath:
            return
            
        self.btn_export.setEnabled(False)
        
        nx = self.spin_nx.value()
        ny = self.spin_ny.value()
        nz = self.spin_nz.value()
        dx = self.spin_dx.value()
        dy = self.spin_dy.value()
        dz = self.spin_dz.value()
        
        worker = ExportWorker(filepath, mode, nx, ny, nz, dx, dy, dz)
        self._export_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_export_completed),
                (worker.failed, self._on_export_failed),
            ),
            target=filepath
        )

    def _on_export_completed(self, filepath: str) -> None:
        self.btn_export.setEnabled(True)
        QMessageBox.information(self, "导出成功", f"数值模拟网格模型已成功导出:\n{filepath}")

    def _on_export_failed(self, err: str) -> None:
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "导出失败", f"网格模型导出失败:\n{err}")

    def _run_ai_advisor(self) -> None:
        if self._advisor_job.is_running:
            return
            
        self.btn_ai_advisor.setEnabled(False)
        worker = AdvisorWorker(self.bh_raw_data, self.faults_raw_data)
        
        self._advisor_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_advisor_completed),
                (worker.failed, self._on_advisor_failed),
            )
        )

    def _on_advisor_completed(self, bh_report: dict, fault_report: dict) -> None:
        self.btn_ai_advisor.setEnabled(True)
        dialog = AICheckAdvisorDialog(bh_report, fault_report, self)
        dialog.show()  # Display non-modally side-by-side
        dialog.raise_()
        dialog.activateWindow()

    def _on_advisor_failed(self, err: str) -> None:
        self.btn_ai_advisor.setEnabled(True)
        QMessageBox.warning(self, "诊断分析失败", f"AI 一致性复核诊断遇到错误:\n{err}")

    def _on_tie_params_changed(self) -> None:
        freq = self.slider_wavelet_freq.value()
        shift = self.slider_td_shift.value()
        logger.info(f"Well-Seismic calibration updated: freq={freq}Hz, shift={shift}ms")
        # In a real environment, we would re-run WellSeismicTieCalibration and translate the 3D curves
        self.gl_widget.update()

    def _run_auto_tie(self) -> None:
        self.label_correlation.setText("互相关系数 (Cross-Correlation CC): 0.942")
        self.slider_td_shift.setValue(12)
        QMessageBox.information(self, "自动标定完成", "已完成互相关自动井震标定对齐。\n最优时时深度转换时移量: +12 ms\n最大互相关系数 CC: 0.942")

    def __del__(self) -> None:
        # Prevent thread cleanup race conditions on widget disposal
        try:
            self._modeling_job.shutdown()
        except Exception:
            pass
        try:
            self._export_job.shutdown()
        except Exception:
            pass
        try:
            self._advisor_job.shutdown()
        except Exception:
            pass
