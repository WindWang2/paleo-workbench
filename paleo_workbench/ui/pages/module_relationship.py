"""模块关系图（首页流程导览画布）。

V3 Light 视觉收敛（DS V5-U3）：
- 卡片为扁平面板（hairline 边、RADIUS_CARD、无彩色头部条）——不再是
  web dashboard 的实色卡头构图；强调卡仅以主色描边 + 选中底色区分。
- 状态徽章复用 ui.components.PwbBadge；卡片样式经 ``ui.style.bind``
  动态渲染，主题切换即刷新（不再构造时快照 light 值）。
- 图例线样（实线/双线/虚线）由 QPainter 绘制，不再用文本字形。
- 画布改为最小宽度约束（滚动容器负责超宽），箭头锚点每 paint 读实时
  geometry，窗口尺寸变化不再截断。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.ui import style
from paleo_workbench.ui.components.badges import PwbBadge
from paleo_workbench.ui.theme import theme_manager
from paleo_workbench.ui.workstation.common import workstation_icon

# 工作流状态 → PwbBadge tone（词汇与 tokens.TASK_STATUS_COLORS 一致）
_STATUS_TONES = {
    "complete": "success",
    "running": "primary",
    "pending": "neutral",
    "warning": "warning",
    "failed": "error",
}


def _palette() -> dict:
    return tokens.palette_for(theme_manager.current_theme.value)


def _card_sheet(accented: bool) -> str:
    p = _palette()
    border = p["PRIMARY"] if accented else p["BORDER"]
    hover_border = p["ACCENT"] if accented else p["PRIMARY"]
    header_bg = p["BG_SELECTION"] if accented else p["BG_SEARCH"]
    title_color = p["PRIMARY"] if accented else p["TEXT_PRIMARY"]
    return f"""
        QFrame#ModuleCard, QFrame#DatabaseModuleCard {{
            background-color: {p["BG_SIDEBAR"]};
            border: 1px solid {border};
            border-radius: {tokens.RADIUS_CARD}px;
        }}
        QFrame#ModuleCard:hover, QFrame#DatabaseModuleCard:hover {{
            border-color: {hover_border};
            background-color: {p["BG_SIDEBAR"]};
        }}
        QFrame#ModuleCardHeader {{
            background-color: {header_bg};
            border: none;
            border-bottom: 1px solid {p["BORDER_LIGHT"]};
            border-top-left-radius: {tokens.RADIUS_CARD - 1}px;
            border-top-right-radius: {tokens.RADIUS_CARD - 1}px;
        }}
        QLabel#ModuleCardTitle {{
            color: {title_color};
            background-color: transparent;
            font-weight: 600;
            font-size: 12.5px;
        }}
        QLabel#ModuleCardItem {{
            color: {p["TEXT_PRIMARY"]};
            font-size: 11.5px;
            background: transparent;
        }}
        QLabel#ModuleCardMeta {{
            color: {p["TEXT_SECONDARY"]};
            font-size: 10.5px;
            background: transparent;
        }}
        QLabel#ModuleCardOutput {{
            color: {p["ACCENT"]};
            font-size: 10.5px;
            font-weight: 500;
            background: transparent;
        }}
    """


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header：浅底 + 600 标题 + 右侧状态徽章（无实色条）
        self.header = QFrame()
        self.header.setObjectName("ModuleCardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(tokens.SPACE_L, 8, tokens.SPACE_L, 8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModuleCardTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.status_badge = PwbBadge("", tone="neutral")
        header_layout.addWidget(self.status_badge)
        self.status_badge.hide()

        layout.addWidget(self.header)

        # Body
        self.body = QFrame()
        self.body.setObjectName("ModuleCardBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(tokens.SPACE_L, 8, tokens.SPACE_L, tokens.SPACE_L)
        body_layout.setSpacing(6)

        for item in items:
            lbl = QLabel(item)
            lbl.setObjectName("ModuleCardItem")
            lbl.setWordWrap(True)
            body_layout.addWidget(lbl)

        if inputs or outputs:
            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setStyleSheet(
                f"color: {tokens.BORDER}; background-color: {tokens.BORDER}; max-height: 1px;"
            )
            body_layout.addWidget(divider)

        if inputs:
            inp_lbl = QLabel("<b>输入:</b> " + ", ".join(inputs))
            inp_lbl.setObjectName("ModuleCardMeta")
            inp_lbl.setWordWrap(True)
            body_layout.addWidget(inp_lbl)

        if outputs:
            out_lbl = QLabel("<b>输出:</b> " + ", ".join(outputs))
            out_lbl.setObjectName("ModuleCardOutput")
            out_lbl.setWordWrap(True)
            body_layout.addWidget(out_lbl)

        layout.addWidget(self.body)

        self._accented = bool(is_accented)
        style.bind(self, lambda: _card_sheet(self._accented))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.page_index)
        super().mousePressEvent(event)

    def set_status(self, status: str) -> None:
        txt = tokens.STATUS_TEXT.get(status, "待开始")
        self.status_badge.setText(txt)
        self.status_badge.set_tone(_STATUS_TONES.get(status, "neutral"))
        self.status_badge.show()


class SubCard(QFrame):
    clicked = Signal(int)

    def __init__(self, title: str, icon: str, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.setObjectName("SubCard")
        style.bind(self, _sub_card_sheet)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_L, 8, tokens.SPACE_L, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        self._icon_name = icon  # 仓库 SVG 名（不再用 emoji 字形）
        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_lbl)

        text_lbl = QLabel(title)
        text_lbl.setObjectName("ModuleCardItem")
        text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_lbl)

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_icon()

    def event(self, event) -> bool:  # noqa: N802
        # app 级样式表切换会向全部 widget 投递 StyleChange——借此重染图标，
        # 不经 ui.style 注册表（bound-method 回调强持有 self，teardown 不安全）
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.StyleChange:
            if not hasattr(self, "_icon_name"):  # 构造早期的 StyleChange
                return super().event(event)
            try:
                self._refresh_icon()
            except RuntimeError:
                pass
        return super().event(event)

    def _refresh_icon(self) -> None:
        p = _palette()
        icon = workstation_icon(self._icon_name, str(p["TEXT_SECONDARY"]))
        self.icon_lbl.setPixmap(icon.pixmap(20, 20))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.page_index)
        super().mousePressEvent(event)


def _sub_card_sheet() -> str:
    p = _palette()
    return f"""
        QFrame#SubCard {{
            background-color: {p["BG_SIDEBAR"]};
            border: 1px solid {p["BORDER"]};
            border-radius: {tokens.RADIUS_CARD}px;
        }}
        QFrame#SubCard:hover {{
            border-color: {p["PRIMARY"]};
            background-color: {p["BG_MENU_HOVER"]};
        }}
    """


class DatabaseModuleCard(QFrame):
    clicked = Signal(int)  # sub page_index

    def __init__(self, title: str, sub_items: list[tuple[str, str, int]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DatabaseModuleCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setObjectName("ModuleCardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(tokens.SPACE_L, 8, tokens.SPACE_L, 8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModuleCardTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.status_badge = PwbBadge("", tone="neutral")
        header_layout.addWidget(self.status_badge)
        self.status_badge.hide()

        layout.addWidget(self.header)

        # Sub-items row
        self.body = QFrame()
        self.body.setObjectName("ModuleCardBody")
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(16, tokens.SPACE_L, 16, tokens.SPACE_L)
        body_layout.setSpacing(20)

        for label, icon, sub_page_index in sub_items:
            sub_card = SubCard(label, icon, sub_page_index, self)
            sub_card.clicked.connect(self.clicked.emit)
            body_layout.addWidget(sub_card)

        layout.addWidget(self.body)

        style.bind(self, lambda: _card_sheet(accented=False))

    def set_status(self, status: str) -> None:
        txt = tokens.STATUS_TEXT.get(status, "待开始")
        self.status_badge.setText(txt)
        self.status_badge.set_tone(_STATUS_TONES.get(status, "neutral"))
        self.status_badge.show()


class _LegendLine(QWidget):
    """QPainter 绘制的线样图例（solid / double / dashed / rect）。"""

    def __init__(self, style_kind: str, parent=None) -> None:
        super().__init__(parent)
        self._kind = style_kind
        self.setFixedSize(22, 12)

    def paintEvent(self, event) -> None:
        p = _palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(p["PRIMARY"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        if self._kind == "dashed":
            pen.setColor(QColor(p["ACCENT"]))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([2.0, 2.0])
        painter.setPen(pen)
        y = self.height() / 2
        if self._kind == "double":
            painter.drawLine(2, int(y - 2), self.width() - 4, int(y - 2))
            painter.drawLine(2, int(y + 2), self.width() - 4, int(y + 2))
        elif self._kind == "rect":
            painter.setPen(QPen(QColor(p["BORDER_STRONG"]), 1))
            painter.setBrush(QBrush(QColor(p["BG_SIDEBAR"])))
            painter.drawRect(4, 2, self.width() - 10, self.height() - 5)
        else:
            painter.drawLine(2, int(y), self.width() - 4, int(y))
        painter.end()


class LegendWidget(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LegendWidget")
        style.bind(self, _legend_sheet)
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

        for text, style_kind in items:
            lbl_layout = QHBoxLayout()
            lbl_layout.setSpacing(6)
            lbl_layout.addWidget(_LegendLine(style_kind))
            lbl = QLabel(text)
            lbl.setObjectName("ModuleCardMeta")
            lbl_layout.addWidget(lbl)
            layout.addLayout(lbl_layout)


def _legend_sheet() -> str:
    p = _palette()
    return f"""
        QFrame#LegendWidget {{
            background-color: {p["BG_RAIL_BOTTOM"]};
            border: 1px solid {p["BORDER"]};
            border-radius: {tokens.RADIUS_CARD}px;
        }}
        QLabel#ModuleCardMeta {{
            color: {p["TEXT_SECONDARY"]};
            font-size: 11px;
            font-weight: 500;
            background: transparent;
        }}
    """


class ModuleRelationshipCanvas(QWidget):
    navigation_requested = Signal(int)

    #: 比例最小宽度：低于此宽度的容器出现横向滚动，箭头比例不漂移
    MIN_CANVAS_WIDTH = 1080

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ModuleRelationshipCanvas")

        # 最小宽度（而非固定宽）：布局随容器伸展，paint 锚点每帧读实时
        # geometry，窗口尺寸变化不再截断/漂移。
        self.setMinimumWidth(self.MIN_CANVAS_WIDTH)
        self.setMinimumHeight(520)

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
        self.card_sequence.setMinimumWidth(500)
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
        self.card_well.setMinimumWidth(220)
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
        self.card_seismic.setMinimumWidth(220)
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
        self.card_facies.setMinimumWidth(220)
        self.grid.addWidget(self.card_facies, 1, 2, Qt.AlignmentFlag.AlignTop)

        self.card_mapping = ModuleCard(
            title="古地理图编制",
            items=[
                "· 古地理图编制",
                "· 图件输出",
                "· 成果发布",
            ],
            is_accented=True,
            page_index=8,
            parent=self,
        )
        self.card_mapping.setMinimumWidth(220)
        self.grid.addWidget(self.card_mapping, 1, 3, Qt.AlignmentFlag.AlignTop)

        # Row 2: 多源数据管理 (Centered under columns 0, 1, 2)
        sub_items = [
            ("数据标准化", "data.svg", 1),
            ("质检管理", "rb-qc.svg", 9),
            ("版本控制", "refresh-cw.svg", 1),
        ]
        self.card_data = DatabaseModuleCard(
            title="多源数据管理",
            sub_items=sub_items,
            parent=self,
        )
        self.card_data.setMinimumWidth(800)
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
        self.card_data.set_status(step_map.get("data_check", "pending"))

        # 2. Sequence Card -> factor_map (Step 2)
        self.card_sequence.set_status(step_map.get("factor_map", "pending"))

        # 3. Well & Seismic Cards -> prediction (Step 3 & 4)
        status_pred = step_map.get("prediction", "pending")
        self.card_well.set_status(status_pred)
        self.card_seismic.set_status(status_pred)

        # 4. Facies Card -> map_compile (Step 5)
        self.card_facies.set_status(step_map.get("map_compile", "pending"))

        # 5. Mapping Card -> qc (Step 6)
        self.card_mapping.set_status(step_map.get("qc", "pending"))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = _palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Parallel horizontal flow between Well and Seismic
        self._draw_parallel_horizontal_arrows(painter, self.card_well, self.card_seismic, p)

        # 2. Vertical Framework -> Seismic connection (Framework provides constraints)
        self._draw_vertical_framework_seismic_connection(painter, self.card_sequence, self.card_seismic, p)

        # 3. Vertical Framework <-> Facies connection (feedback loop)
        self._draw_vertical_framework_facies_connection(painter, self.card_sequence, self.card_facies, p)

        # 4. Horizontal Facies -> Mapping connection
        self._draw_horizontal_facies_mapping_connection(painter, self.card_facies, self.card_mapping, p)

        # 5. Database support dashed lines
        self._draw_database_support_arrows(painter, self.card_data, p)
        painter.end()

    def draw_directed_arrow(
        self,
        self_painter: QPainter,
        start: QPoint,
        end: QPoint,
        text: str = "",
        text_pos: str = "top",
        is_dashed: bool = False,
        color_hex: str | None = None,
    ) -> None:
        if color_hex is None:
            color_hex = _palette()["PRIMARY"]
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
            font = self.font()
            font.setPointSize(9)
            self_painter.setFont(font)
            self_painter.setPen(QColor(_palette()["TEXT_SECONDARY"]))

            mid_x = (start.x() + end.x()) / 2
            mid_y = (start.y() + end.y()) / 2

            lines = text.split("\n")
            metrics = QFontMetrics(font)
            line_height = metrics.height()

            for i, line in enumerate(lines):
                text_width = metrics.horizontalAdvance(line)

                if text_pos == "top":
                    offset_y = -(len(lines) - 1 - i) * line_height - 6
                    self_painter.drawText(
                        int(mid_x - text_width / 2),
                        int(mid_y + offset_y),
                        line
                    )
                elif text_pos == "bottom":
                    offset_y = i * line_height + 15
                    self_painter.drawText(
                        int(mid_x - text_width / 2),
                        int(mid_y + offset_y),
                        line
                    )
                elif text_pos == "left":
                    offset_y = int((i - len(lines) / 2.0 + 0.5) * line_height)
                    self_painter.drawText(
                        int(mid_x - text_width - 8),
                        int(mid_y + offset_y + line_height / 3),
                        line
                    )
                elif text_pos == "right":
                    offset_y = int((i - len(lines) / 2.0 + 0.5) * line_height)
                    self_painter.drawText(
                        int(mid_x + 8),
                        int(mid_y + offset_y + line_height / 3),
                        line
                    )

    def _draw_parallel_horizontal_arrows(self, painter: QPainter, card_well, card_seismic, p: dict) -> None:
        geom_well = card_well.geometry()
        geom_seismic = card_seismic.geometry()

        y_center = geom_well.top() + 85
        y_top = y_center - 10
        y_bottom = y_center + 10

        start_top = QPoint(geom_well.right() + 4, y_top)
        end_top = QPoint(geom_seismic.left() - 4, y_top)
        self.draw_directed_arrow(
            painter, start_top, end_top, text="提供井控信息\n约束与验证", text_pos="top"
        )

        start_bottom = QPoint(geom_seismic.left() - 4, y_bottom)
        end_bottom = QPoint(geom_well.right() + 4, y_bottom)
        self.draw_directed_arrow(
            painter, start_bottom, end_bottom, text="反馈地震相结果\n辅助单井解释", text_pos="bottom"
        )

    def _draw_vertical_framework_seismic_connection(self, painter: QPainter, card_seq, card_seismic, p: dict) -> None:
        geom_seq = card_seq.geometry()
        geom_seismic = card_seismic.geometry()

        x_center = geom_seismic.center().x()
        start = QPoint(x_center, geom_seq.bottom() + 4)
        end = QPoint(x_center, geom_seismic.top() - 4)

        self.draw_directed_arrow(
            painter, start, end, text="提供层序格架\n约束条件", text_pos="left"
        )

    def _draw_vertical_framework_facies_connection(self, painter: QPainter, card_seq, card_facies, p: dict) -> None:
        geom_seq = card_seq.geometry()
        geom_facies = card_facies.geometry()

        x_center = geom_facies.center().x()
        x_left = x_center - 12
        x_right = x_center + 12

        start_up = QPoint(x_left, geom_facies.top() - 4)
        end_up = QPoint(x_left, geom_seq.bottom() + 4)
        self.draw_directed_arrow(
            painter, start_up, end_up, text="地层层序检查\n调整与更新", text_pos="left"
        )

        start_down = QPoint(x_right, geom_seq.bottom() + 4)
        end_down = QPoint(x_right, geom_facies.top() - 4)
        self.draw_directed_arrow(painter, start_down, end_down)

    def _draw_horizontal_facies_mapping_connection(self, painter: QPainter, card_facies, card_mapping, p: dict) -> None:
        geom_facies = card_facies.geometry()
        geom_mapping = card_mapping.geometry()

        y_center = geom_facies.top() + 85
        start = QPoint(geom_facies.right() + 4, y_center)
        end = QPoint(geom_mapping.left() - 4, y_center)
        self.draw_directed_arrow(
            painter, start, end, text="提供解释成果\n与图版方案", text_pos="top"
        )

    def _draw_database_support_arrows(self, painter: QPainter, card_data, p: dict) -> None:
        geom_data = card_data.geometry()
        y_top = geom_data.top() - 4
        accent = p["ACCENT"]

        x_well = self.card_well.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_well, y_top),
            QPoint(x_well, self.card_well.geometry().bottom() + 4),
            is_dashed=True,
            color_hex=accent,
        )

        x_seismic = self.card_seismic.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_seismic, y_top),
            QPoint(x_seismic, self.card_seismic.geometry().bottom() + 4),
            is_dashed=True,
            color_hex=accent,
        )

        x_facies = self.card_facies.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_facies, y_top),
            QPoint(x_facies, self.card_facies.geometry().bottom() + 4),
            is_dashed=True,
            color_hex=accent,
        )

        x_seq = self.card_sequence.geometry().center().x()
        self.draw_directed_arrow(
            painter,
            QPoint(x_seq, y_top),
            QPoint(x_seq, self.card_sequence.geometry().bottom() + 4),
            is_dashed=True,
            color_hex=accent,
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
