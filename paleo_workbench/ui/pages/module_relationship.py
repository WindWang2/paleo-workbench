from __future__ import annotations
import math
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, QGridLayout, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QCursor, QFontMetrics

from paleo_workbench.ui import tokens


class ModuleCard(QFrame):
    clicked = Signal(int)  # emits page_index

    def __init__(
        self,
        title: str,
        items: list[str],
        inputs: list[str] = None,
        outputs: list[str] = None,
        is_accented: bool = False,
        page_index: int = -1,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.setObjectName("ModuleCard")

        # Apply a soft drop shadow
        # shadow = QGraphicsDropShadowEffect(self)
        # shadow.setBlurRadius(12)
        # shadow.setColor(QColor(0, 0, 0, 15))
        # shadow.setOffset(0, 3)
        # self.setGraphicsEffect(shadow)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setObjectName("ModuleCardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 10)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModuleCardTitle")
        header_layout.addWidget(self.title_label)

        # Add status badge
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("ModuleCardStatus")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_badge.setStyleSheet("""
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            background-color: transparent;
            color: white;
        """)
        header_layout.addWidget(self.status_badge)
        self.status_badge.hide()

        layout.addWidget(self.header)

        # Body
        self.body = QFrame()
        self.body.setObjectName("ModuleCardBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(6)

        # Items
        for item in items:
            lbl = QLabel(item)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 11.5px; color: #28323f;")
            body_layout.addWidget(lbl)

        # Inputs & Outputs section
        if inputs or outputs:
            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setStyleSheet("color: #e2e6ec; background-color: #e2e6ec; max-height: 1px;")
            body_layout.addWidget(divider)

        if inputs:
            inp_lbl = QLabel(f"<b>输入:</b> " + ", ".join(inputs))
            inp_lbl.setWordWrap(True)
            inp_lbl.setStyleSheet("color: #7e8794; font-size: 10.5px;")
            body_layout.addWidget(inp_lbl)

        if outputs:
            out_lbl = QLabel(f"<b>输出:</b> " + ", ".join(outputs))
            out_lbl.setWordWrap(True)
            out_lbl.setStyleSheet("color: #1f6fe0; font-size: 10.5px; font-weight: 500;")
            body_layout.addWidget(out_lbl)

        layout.addWidget(self.body)

        # Styling
        if is_accented:
            # Golden card styling for Mapping
            self.header.setStyleSheet("""
                QFrame#ModuleCardHeader {
                    background-color: #ff9f1c;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                }
                QLabel#ModuleCardTitle {
                    color: white;
                    font-weight: bold;
                    font-size: 12.5px;
                }
            """)
            self.setStyleSheet("""
                QFrame#ModuleCard {
                    background-color: #fffaf0;
                    border: 1px solid #ffcc80;
                    border-radius: 8px;
                }
                QFrame#ModuleCard:hover {
                    border-color: #ff9f1c;
                    background-color: #fff5e6;
                }
            """)
        else:
            # Blue card styling
            self.header.setStyleSheet("""
                QFrame#ModuleCardHeader {
                    background-color: #1e56a0;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                }
                QLabel#ModuleCardTitle {
                    color: white;
                    font-weight: bold;
                    font-size: 12.5px;
                }
            """)
            self.setStyleSheet("""
                QFrame#ModuleCard {
                    background-color: #f7faff;
                    border: 1px solid #c8d6e5;
                    border-radius: 8px;
                }
                QFrame#ModuleCard:hover {
                    border-color: #1e56a0;
                    background-color: #edf4fe;
                }
            """)

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.page_index)
        super().mousePressEvent(event)

    def set_status(self, status: str) -> None:
        status_text = {
            "complete": "完成",
            "running": "进行中",
            "pending": "待开始",
            "warning": "警告",
            "failed": "失败",
        }
        status_colors = {
            "complete": "#22c55e",  # green
            "running": "#3b82f6",   # blue
            "pending": "#7e8794",   # gray
            "warning": "#eab308",   # amber
            "failed": "#ef4444",    # red
        }
        txt = status_text.get(status, "待开始")
        color = status_colors.get(status, "#7e8794")
        self.status_badge.setText(txt)
        self.status_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            background-color: {color};
            color: white;
        """)
        self.status_badge.show()


class SubCard(QFrame):
    clicked = Signal(int)

    def __init__(self, title: str, icon: str, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.setObjectName("SubCard")
        self.setStyleSheet("""
            QFrame#SubCard {
                background-color: white;
                border: 1px solid #dce0e6;
                border-radius: 6px;
            }
            QFrame#SubCard:hover {
                border-color: #1f6fe0;
                background-color: #f7faff;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 18px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_lbl = QLabel(title)
        text_lbl.setStyleSheet("font-weight: 500; font-size: 11px; color: #28323f;")
        text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(icon_lbl)
        layout.addWidget(text_lbl)

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.page_index)
        super().mousePressEvent(event)


class DatabaseModuleCard(QFrame):
    clicked = Signal(int)  # sub page_index

    def __init__(self, title: str, sub_items: list[tuple[str, str, int]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DatabaseModuleCard")

        # shadow = QGraphicsDropShadowEffect(self)
        # shadow.setBlurRadius(12)
        # shadow.setColor(QColor(0, 0, 0, 15))
        # shadow.setOffset(0, 3)
        # self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setObjectName("ModuleCardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 10)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModuleCardTitle")
        header_layout.addWidget(self.title_label)

        # Add status badge
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("ModuleCardStatus")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_badge.setStyleSheet("""
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            background-color: transparent;
            color: white;
        """)
        header_layout.addWidget(self.status_badge)
        self.status_badge.hide()

        layout.addWidget(self.header)

        # Sub-items row
        self.body = QFrame()
        self.body.setObjectName("ModuleCardBody")
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(16, 12, 16, 12)
        body_layout.setSpacing(20)

        for label, icon, sub_page_index in sub_items:
            sub_card = SubCard(label, icon, sub_page_index, self)
            sub_card.clicked.connect(self.clicked.emit)
            body_layout.addWidget(sub_card)

        layout.addWidget(self.body)

        self.header.setStyleSheet("""
            QFrame#ModuleCardHeader {
                background-color: #1e56a0;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QLabel#ModuleCardTitle {
                color: white;
                font-weight: bold;
                font-size: 12.5px;
            }
        """)
        self.setStyleSheet("""
            QFrame#DatabaseModuleCard {
                background-color: #f7faff;
                border: 1px solid #c8d6e5;
                border-radius: 8px;
            }
        """)

    def set_status(self, status: str) -> None:
        status_text = {
            "complete": "完成",
            "running": "进行中",
            "pending": "待开始",
            "warning": "警告",
            "failed": "失败",
        }
        status_colors = {
            "complete": "#22c55e",  # green
            "running": "#3b82f6",   # blue
            "pending": "#7e8794",   # gray
            "warning": "#eab308",   # amber
            "failed": "#ef4444",    # red
        }
        txt = status_text.get(status, "待开始")
        color = status_colors.get(status, "#7e8794")
        self.status_badge.setText(txt)
        self.status_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            background-color: {color};
            color: white;
        """)
        self.status_badge.show()


class LegendWidget(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LegendWidget")
        self.setStyleSheet("""
            QFrame#LegendWidget {
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        items = [
            ("主要数据流/成果流", "solid"),
            ("双向交互/反馈", "double"),
            ("数据供给/支撑", "dashed"),
            ("模块内部输入输出", "rect"),
        ]

        for text, style in items:
            lbl_layout = QHBoxLayout()
            lbl_layout.setSpacing(6)

            indicator = QLabel()
            if style == "solid":
                indicator.setText("──➤")
                indicator.setStyleSheet("color: #1e56a0; font-weight: bold; font-size: 11px;")
            elif style == "double":
                indicator.setText("◀──▶")
                indicator.setStyleSheet("color: #1e56a0; font-weight: bold; font-size: 11px;")
            elif style == "dashed":
                indicator.setText("· · ➤")
                indicator.setStyleSheet("color: #1e56a0; font-weight: bold; font-size: 11px;")
            elif style == "rect":
                indicator.setText(" ")
                indicator.setFixedSize(14, 10)
                indicator.setStyleSheet("background-color: #f7faff; border: 1px solid #c8d6e5; border-radius: 2px;")

            lbl = QLabel(text)
            lbl.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 500;")

            lbl_layout.addWidget(indicator)
            lbl_layout.addWidget(lbl)
            layout.addLayout(lbl_layout)


class ModuleRelationshipCanvas(QWidget):
    navigation_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ModuleRelationshipCanvas")

        # Fixed width ensures diagram coordinates and arrow anchor points never drift when parent resizes
        self.setFixedWidth(1180)
        self.setMinimumHeight(580)

        # Grid layout
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(15, 10, 15, 10)
        
        # Spans gaps of 90px horizontally and 65px vertically to keep clean proportional spacing
        self.grid.setHorizontalSpacing(90)
        self.grid.setVerticalSpacing(65)

        # Row 0: 地层格架构建 (Centered at top)
        self.card_sequence = ModuleCard(
            title="地层格架构建",
            items=[
                "· 单井层序划分",
                "· 井震标定",
                "· 井震地层层序划分及岩性共拉分特征",
                "· 资料地质编图",
            ],
            outputs=["地层格架方案控制单井/地震分析 and 编图的最小单元"],
            page_index=4,
            parent=self,
        )
        self.card_sequence.setFixedWidth(500)
        self.grid.addWidget(self.card_sequence, 0, 1, 1, 2, Qt.AlignmentFlag.AlignCenter)

        # Row 1: Middle Row (AlignTop to keep a perfectly horizontal baseline)
        self.card_well = ModuleCard(
            title="单井相智能分析",
            items=[
                "1. 单井的岩性结果标记地震属性",
                "2. 单井的结果校验地层结果",
            ],
            inputs=["地层格架", "地震属性", "测井曲线", "岩心/岩性数据", "其它辅助资料"],
            outputs=["单井相结果", "相带/相序划分"],
            page_index=2,
            parent=self,
        )
        self.card_well.setFixedWidth(220)
        self.grid.addWidget(self.card_well, 1, 0, Qt.AlignmentFlag.AlignTop)

        self.card_seismic = ModuleCard(
            title="地震相智能分析",
            items=[
                "1. 地震属性辅助无井区地砂岩性判别",
                "2. 判断相变边界",
            ],
            inputs=["地层格架", "地震体", "地震属性", "井点/相标定"],
            outputs=["地震相结果", "相变边界"],
            page_index=3,
            parent=self,
        )
        self.card_seismic.setFixedWidth(220)
        self.grid.addWidget(self.card_seismic, 1, 1, Qt.AlignmentFlag.AlignTop)

        self.card_facies = ModuleCard(
            title="岩相与沉积相分析",
            items=[
                "1. 输出解释版本管理",
                "2. 输出编制图版成果",
            ],
            inputs=["地震相结果", "单井相结果", "地层格架"],
            outputs=["相类型", "沉积相", "解释成果"],
            page_index=5,
            parent=self,
        )
        self.card_facies.setFixedWidth(220)
        self.grid.addWidget(self.card_facies, 1, 2, Qt.AlignmentFlag.AlignTop)

        self.card_mapping = ModuleCard(
            title="古地理图编制",
            items=[
                "☑ 古地理图编制",
                "☑ 图件输出",
                "☑ 成果发布",
            ],
            is_accented=True,
            page_index=8,
            parent=self,
        )
        self.card_mapping.setFixedWidth(220)
        self.grid.addWidget(self.card_mapping, 1, 3, Qt.AlignmentFlag.AlignTop)

        # Row 2: 多源数据管理 (Centered under columns 0, 1, 2)
        sub_items = [
            ("数据标准化", "📁", 1),
            ("质检管理", "🔍", 9),
            ("版本控制", "🔄", 1),
        ]
        self.card_data = DatabaseModuleCard(
            title="多源数据管理",
            sub_items=sub_items,
            parent=self,
        )
        self.card_data.setFixedWidth(800)
        self.grid.addWidget(self.card_data, 2, 0, 1, 3, Qt.AlignmentFlag.AlignCenter)

        # Connect signals
        self.card_sequence.clicked.connect(self.navigation_requested.emit)
        self.card_well.clicked.connect(self.navigation_requested.emit)
        self.card_seismic.clicked.connect(self.navigation_requested.emit)
        self.card_facies.clicked.connect(self.navigation_requested.emit)
        self.card_mapping.clicked.connect(self.navigation_requested.emit)
        self.card_data.clicked.connect(self.navigation_requested.emit)

    def update_states(self, steps: list) -> None:
        step_map = {}
        for step in steps:
            step_map[step.step_type] = step.status

        # 1. DatabaseModuleCard -> data_check (Step 1)
        status_data = step_map.get("data_check", "pending")
        self.card_data.set_status(status_data)

        # 2. Sequence Card -> factor_map (Step 2)
        status_seq = step_map.get("factor_map", "pending")
        self.card_sequence.set_status(status_seq)

        # 3. Well & Seismic Cards -> prediction (Step 3 & 4)
        status_pred = step_map.get("prediction", "pending")
        self.card_well.set_status(status_pred)
        self.card_seismic.set_status(status_pred)

        # 4. Facies Card -> map_compile (Step 5)
        status_facies = step_map.get("map_compile", "pending")
        self.card_facies.set_status(status_facies)

        # 5. Mapping Card -> qc (Step 6)
        status_mapping = step_map.get("qc", "pending")
        self.card_mapping.set_status(status_mapping)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Parallel horizontal flow between Well and Seismic
        self._draw_parallel_horizontal_arrows(painter, self.card_well, self.card_seismic)

        # 2. Vertical Framework -> Seismic connection (Framework provides constraints)
        self._draw_vertical_framework_seismic_connection(painter, self.card_sequence, self.card_seismic)

        # 3. Vertical Framework <-> Facies connection (feedback loop)
        self._draw_vertical_framework_facies_connection(painter, self.card_sequence, self.card_facies)

        # 4. Horizontal Facies -> Mapping connection
        self._draw_horizontal_facies_mapping_connection(painter, self.card_facies, self.card_mapping)

        # 5. Database support dashed lines
        self._draw_database_support_arrows(painter, self.card_data)
        painter.end()


class ModuleRelationshipWidget(QWidget):
    navigation_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ModuleRelationshipWidget")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = ModuleRelationshipCanvas(self)
        self.canvas.navigation_requested.connect(self.navigation_requested.emit)
        layout.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)

    def update_states(self, steps: list) -> None:
        self.canvas.update_states(steps)

    @property
    def card_sequence(self):
        return self.canvas.card_sequence

    @property
    def card_well(self):
        return self.canvas.card_well

    @property
    def card_seismic(self):
        return self.canvas.card_seismic

    @property
    def card_facies(self):
        return self.canvas.card_facies

    @property
    def card_mapping(self):
        return self.canvas.card_mapping

    @property
    def card_data(self):
        return self.canvas.card_data

    def draw_directed_arrow(
        self,
        self_painter: QPainter,
        start: QPoint,
        end: QPoint,
        text: str = "",
        text_pos: str = "top",
        is_dashed: bool = False,
        color_hex: str = "#1e56a0",
    ) -> None:
        color = QColor(color_hex)
        pen = QPen(color, 1.5)
        if is_dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        self_painter.setPen(pen)
        self_painter.setBrush(QBrush(color))
        self_painter.drawLine(start, end)

        # Draw arrowhead
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        angle = math.atan2(dy, dx)

        arrow_size = 7
        p1 = QPoint(
            int(end.x() - arrow_size * math.cos(angle - math.pi / 6)),
            int(end.y() - arrow_size * math.sin(angle - math.pi / 6)),
        )
        p2 = QPoint(
            int(end.x() - arrow_size * math.cos(angle + math.pi / 6)),
            int(end.y() - arrow_size * math.sin(angle + math.pi / 6)),
        )
        self_painter.drawPolygon([end, p1, p2])

        # Draw label
        if text:
            # Safe metrics resolving by explicitly instantiating QFontMetrics with widget font
            font = self.font()
            font.setPointSize(9)
            self_painter.setFont(font)
            self_painter.setPen(QColor("#64748b"))

            mid_x = (start.x() + end.x()) / 2
            mid_y = (start.y() + end.y()) / 2
            
            lines = text.split("\n")
            metrics = QFontMetrics(font)
            line_height = metrics.height()

            for i, line in enumerate(lines):
                text_width = metrics.horizontalAdvance(line)
                
                if text_pos == "top":
                    # Stack lines upwards: last line ends at mid_y - 6
                    offset_y = -(len(lines) - 1 - i) * line_height - 6
                    self_painter.drawText(
                        int(mid_x - text_width / 2),
                        int(mid_y + offset_y),
                        line
                    )
                elif text_pos == "bottom":
                    # Stack lines downwards: first line starts at mid_y + 15
                    offset_y = i * line_height + 15
                    self_painter.drawText(
                        int(mid_x - text_width / 2),
                        int(mid_y + offset_y),
                        line
                    )
                elif text_pos == "left":
                    # Center vertically relative to line midpoint
                    offset_y = int((i - len(lines) / 2.0 + 0.5) * line_height)
                    self_painter.drawText(
                        int(mid_x - text_width - 8),
                        int(mid_y + offset_y + line_height / 3),
                        line
                    )
                elif text_pos == "right":
                    # Center vertically relative to line midpoint
                    offset_y = int((i - len(lines) / 2.0 + 0.5) * line_height)
                    self_painter.drawText(
                        int(mid_x + 8),
                        int(mid_y + offset_y + line_height / 3),
                        line
                    )

    def _draw_parallel_horizontal_arrows(self, painter: QPainter, card_well, card_seismic) -> None:
        geom_well = card_well.geometry()
        geom_seismic = card_seismic.geometry()

        # Since Row 1 cards are AlignTop, their top Y values are identical.
        # Use geom_well.top() + 85 to cross precisely in the visual middle of both cards.
        y_center = geom_well.top() + 85
        y_top = y_center - 10
        y_bottom = y_center + 10

        # Top arrow: Well -> Seismic (提供井控信息约束与验证)
        # Shift start and end points slightly away from borders to make it look clean
        start_top = QPoint(geom_well.right() + 4, y_top)
        end_top = QPoint(geom_seismic.left() - 4, y_top)
        self.draw_directed_arrow(
            painter, start_top, end_top, text="提供井控信息\n约束与验证", text_pos="top"
        )

        # Bottom arrow: Seismic -> Well (反馈地震相结果辅助单井解释)
        start_bottom = QPoint(geom_seismic.left() - 4, y_bottom)
        end_bottom = QPoint(geom_well.right() + 4, y_bottom)
        self.draw_directed_arrow(
            painter, start_bottom, end_bottom, text="反馈地震相结果\n辅助单井解释", text_pos="bottom"
        )

    def _draw_vertical_framework_seismic_connection(self, painter: QPainter, card_seq, card_seismic) -> None:
        geom_seq = card_seq.geometry()
        geom_seismic = card_seismic.geometry()

        # Vertical line between Framework (top) -> Seismic (bottom) (提供层序格架约束条件)
        x_center = geom_seismic.center().x()
        start = QPoint(x_center, geom_seq.bottom() + 4)
        end = QPoint(x_center, geom_seismic.top() - 4)
        
        self.draw_directed_arrow(
            painter, start, end, text="提供层序格架\n约束条件", text_pos="left"
        )

    def _draw_vertical_framework_facies_connection(self, painter: QPainter, card_seq, card_facies) -> None:
        geom_seq = card_seq.geometry()
        geom_facies = card_facies.geometry()

        # Draw a double vertical path representing feedback and updates
        x_center = geom_facies.center().x()
        x_left = x_center - 12
        x_right = x_center + 12

        # Left path (pointing up): Facies -> Framework (地层层序检查调整与更新)
        start_up = QPoint(x_left, geom_facies.top() - 4)
        end_up = QPoint(x_left, geom_seq.bottom() + 4)
        self.draw_directed_arrow(
            painter, start_up, end_up, text="地层层序检查\n调整与更新", text_pos="left"
        )

        # Right path (pointing down): Framework -> Facies
        start_down = QPoint(x_right, geom_seq.bottom() + 4)
        end_down = QPoint(x_right, geom_facies.top() - 4)
        self.draw_directed_arrow(painter, start_down, end_down)

    def _draw_horizontal_facies_mapping_connection(self, painter: QPainter, card_facies, card_mapping) -> None:
        geom_facies = card_facies.geometry()
        geom_mapping = card_mapping.geometry()

        # Perfectly horizontal line aligned with y_center of Row 1
        y_center = geom_facies.top() + 85
        start = QPoint(geom_facies.right() + 4, y_center)
        end = QPoint(geom_mapping.left() - 4, y_center)
        self.draw_directed_arrow(
            painter, start, end, text="提供解释成果\n与图版方案", text_pos="top"
        )

    def _draw_database_support_arrows(self, painter: QPainter, card_data) -> None:
        geom_data = card_data.geometry()
        y_top = geom_data.top() - 4

        # Draw dashed support lines pointing up to the bottoms of cards
        # 1. To Well
        x_well = self.card_well.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_well, y_top),
            QPoint(x_well, self.card_well.geometry().bottom() + 4),
            is_dashed=True,
            color_hex="#3b82f6",
        )

        # 2. To Seismic
        x_seismic = self.card_seismic.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_seismic, y_top),
            QPoint(x_seismic, self.card_seismic.geometry().bottom() + 4),
            is_dashed=True,
            color_hex="#3b82f6",
        )

        # 3. To Facies
        x_facies = self.card_facies.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_facies, y_top),
            QPoint(x_facies, self.card_facies.geometry().bottom() + 4),
            is_dashed=True,
            color_hex="#3b82f6",
        )

        # 4. To Framework (Sequence)
        # This line goes straight up through the space between seismic and facies cards
        x_seq = self.card_sequence.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_seq, y_top),
            QPoint(x_seq, self.card_sequence.geometry().bottom() + 4),
            is_dashed=True,
            color_hex="#3b82f6",
        )


class ModuleRelationshipWidget(QWidget):
    navigation_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ModuleRelationshipWidget")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = ModuleRelationshipCanvas(self)
        self.canvas.navigation_requested.connect(self.navigation_requested.emit)
        layout.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)

    def update_states(self, steps: list) -> None:
        self.canvas.update_states(steps)

    @property
    def card_sequence(self):
        return self.canvas.card_sequence

    @property
    def card_well(self):
        return self.canvas.card_well

    @property
    def card_seismic(self):
        return self.canvas.card_seismic

    @property
    def card_facies(self):
        return self.canvas.card_facies

    @property
    def card_mapping(self):
        return self.canvas.card_mapping

    @property
    def card_data(self):
        return self.canvas.card_data
