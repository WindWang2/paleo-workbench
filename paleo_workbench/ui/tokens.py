"""Design tokens for the AppShell — single source of truth.

All values extracted from the standalone prototype via headless browser
computed-CSS inspection. See docs/superpowers/specs/2026-07-05-appshell-design.md.
"""
from __future__ import annotations

PRIMARY = "#1f6fe0"
ACCENT = "#6f47cf"
SUCCESS = "#1f9d57"
TEAL = "#0f93a4"
BG_BODY = "#eef0f4"
BG_HEADER = "#f3f5f9"
BG_SIDEBAR = "#ffffff"
BG_SEARCH = "#eef2f7"
BG_RAIL = "#1b3a6b"
BG_RAIL_GRADIENT = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1f5fbf, stop:1 #184c97)"
BG_RAIL_TOP = "#1f5fbf"
BG_RAIL_BOTTOM = "#184c97"
TEXT_PRIMARY = "#28323f"
TEXT_SECONDARY = "#7e8794"
TEXT_DARK = "#1b2330"
TEXT_ON_RAIL = "rgba(255, 255, 255, 0.66)"
TEXT_ON_RAIL_ACTIVE = "#ffffff"
BORDER = "#e2e6ec"
BORDER_STRONG = "#dde2e9"
BORDER_LIGHT = "#d8dee6"

PRIMARY_HOVER = "#2b7cf0"
PRIMARY_PRESSED = "#1a5fc4"
PRIMARY_DISABLED = "#a8c4f0"
FOCUS_RING = PRIMARY

FONT_FAMILY = '"PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_SIZE_BASE = "12.5px"
FONT_SIZE_STATUS = "11px"
FONT_SIZE_SIDEBAR_SECONDARY = "10.5px"
FONT_SIZE_NAV_LABEL = "9.5px"
FONT_WEIGHT_NAV_LABEL = "500"
FONT_SIZE_TITLE = "13px"
FONT_WEIGHT_TITLE = "600"

MENU_BAR_HEIGHT = 36
HEADER_TOOLBAR_HEIGHT = 36
ICON_RAIL_WIDTH = 60
TEXT_SIDEBAR_WIDTH = 248
STATUS_BAR_HEIGHT = 24
ICON_RAIL_ITEM_SIZE = 46
RADIUS_BUTTON = 5
RADIUS_CARD = 9
RADIUS_BADGE = 8
RADIUS_PANEL = 10
RADIUS_NAV_ITEM = 8

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
PAGE_MARGIN = 12
PANEL_PADDING = 10
CONTROL_HEIGHT = 28
CONTROL_HEIGHT_LG = 32

ICON_FILES = [
    "home.svg", "data.svg", "well-log.svg", "seismic.svg", "sequence.svg",
    "stratigraphy.svg",
    "visualization.svg", "preparation.svg", "mapping.svg", "review.svg",
]

PAGE_NAMES = [
    "首页", "数据", "测井预测", "地震预测", "层序格架",
    "地层对比",
    "可视化", "制备", "编图", "成图审核",
]
# Brief Chinese descriptions for nav-icon tooltips.
PAGE_DESCRIPTIONS = [
    "项目概览与流程导航",
    "导入与管理数据资产",
    "基于测井的沉积相预测",
    "基于地震的沉积相预测",
    "层序地层格架构建",
    "多井连井地层对比",
    "相带与古地理可视化",
    "制图数据制备与清洗",
    "古地理图编制工作台",
    "成图质检与成果导出",
]

STEP_COLORS = ["#1f6fe0", "#0f93a4", "#6f47cf", "#c47e12", "#e2705b", "#7e8794"]
STEP_LABELS = [
    "数据管理", "数据转换", "制图数据制备",
    "沉积相预测", "古地理图编制", "质控与导出",
]
STATUS_TEXT = {
    "complete": "完成",
    "running": "进行中",
    "pending": "待开始",
    "warning": "警告",
    "failed": "失败",
    "ready": "就绪",
    "skipped": "已跳过",
    "mock": "Mock",
}
ERROR_RED = "#dc2626"
WARNING = "#c47e12"  # amber, previously only embedded in STEP_COLORS

QC_RESULT_COLORS = {
    "pass": SUCCESS,
    "warning": WARNING,
    "error": ERROR_RED,
}
QC_RESULT_LABELS = {
    "pass": "✓通过",
    "warning": "!警告",
    "error": "!待处理",
}
DEFAULT_QC_RULES = [
    "层级一致性", "未分类区域", "低可信区",
    "边界碎斑异常", "图例符号完整性", "字段与输出格式完整性",
]
RULE_DESCRIPTIONS = {
    "层级一致性": "各层级结构与命名是否一致",
    "未分类区域": "是否存在未分类或未赋值区域",
    "低可信区": "低可信区是否已复核确认",
    "边界碎斑异常": "是否存在碎斑、孤岛等异常斑块",
    "图例符号完整性": "图例符号与备注是否完整",
    "字段与输出格式完整性": "字段是否齐全、格式是否规范",
    # QC engine rule keys map to display via these too:
    "facies_polygons_present": "古地理图相带多边形是否存在",
    "target_horizon_present": "古地理图是否关联目标层位",
    "facies_geometry_valid": "相带多边形几何是否有效（无自交）",
    "well_overlays_present": "图面是否叠加井位",
    "contour_lines_present": "是否存在等值线线要素",
    "well_table_qc_clean": "井点表 MAD/砂地比异常是否已清理",
}
RESOURCE_LABELS = {
    "well_log": "测井数据",
    "seismic": "地震数据",
    "horizon": "层位数据",
}
RESOURCE_UNITS = {
    "well_log": "井",
    "seismic": "条测线",
    "horizon": "层位",
}

TASK_STATUS_COLORS = {"complete": SUCCESS, "pending": TEXT_SECONDARY, "running": PRIMARY, "failed": ERROR_RED}
TASK_STATUS_LABELS = {"complete": "已生成", "pending": "待生成", "running": "进行中", "failed": "失败"}
# 「克里金(MVP·线性)」is intentionally labelled: backend is SciPy linear, not
# full variogram kriging (ISS-KRIG-01). Keep alias "克里金" in factor_interpolation.
INTERPOLATION_METHODS = ["克里金(MVP·线性)", "IDW", "样条", "方向趋势"]
INTERPOLATION_METHOD_TOOLTIPS = {
    "克里金(MVP·线性)": "MVP 占位：SciPy linear 三角剖分插值，非变差函数克里金",
    "IDW": "反距离加权；支持断层屏障 fault_polylines",
    "样条": "SciPy cubic 样条插值",
    "方向趋势": "各向异性方向加权趋势面（ISS-ALG-02）",
}
SMOOTHING_LEVELS = ["弱", "中", "强"]
SEQUENCE_SCHEMES = ["三级层序格架（推荐）", "四级高频层序", "体系域二分方案"]
SYSTEMS_TRACT_LABELS = ["LST", "TST", "HST"]

QSS_TEMPLATE = f"""
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE};
    color: {TEXT_PRIMARY};
}}
QFrame#MenuBar {{
    background: {BG_HEADER}; border-bottom: 1px solid {BORDER_STRONG};
    min-height: {MENU_BAR_HEIGHT}px; max-height: {MENU_BAR_HEIGHT}px;
}}
QPushButton#ProjectMenuButton {{
    background: transparent; border: none; color: {TEXT_PRIMARY}; padding: 0;
}}
QPushButton#ProjectMenuButton:hover {{ color: {PRIMARY}; }}
/* Inline-styled PDF paging buttons keep their functional objectName; the
   focus rule below mirrors SecondaryButton so keyboard focus is visible. */
QPushButton#DataPreviewPdfPrevious,
QPushButton#DataPreviewPdfNext {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 4px 12px;
    min-height: {CONTROL_HEIGHT}px;
    background: {BG_SIDEBAR};
}}
QPushButton#DataPreviewPdfPrevious:focus,
QPushButton#DataPreviewPdfNext:focus {{
    border: 1px solid {FOCUS_RING};
}}
QPushButton#PrimaryButton {{
    background: {PRIMARY}; color: #ffffff; border: none;
    border-radius: {RADIUS_BUTTON}px;
    padding: 4px 14px;
    min-height: {CONTROL_HEIGHT_LG}px;
}}
QPushButton#PrimaryButton:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#PrimaryButton:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton#PrimaryButton:disabled {{
    background: {PRIMARY_DISABLED}; color: #ffffff;
}}
QPushButton#PrimaryButton:focus {{
    border: 1px solid {FOCUS_RING};
}}
QPushButton#SecondaryButton {{
    background: {BG_SIDEBAR}; color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 4px 12px;
    min-height: {CONTROL_HEIGHT}px;
}}
QPushButton#SecondaryButton:hover {{ background: {BG_SEARCH}; }}
QPushButton#SecondaryButton:pressed {{ background: {BORDER_LIGHT}; }}
QPushButton#SecondaryButton:disabled {{
    color: {TEXT_SECONDARY}; border-color: {BORDER};
}}
QPushButton#SecondaryButton:checked {{
    background: {BG_SEARCH}; border-color: {PRIMARY}; color: {TEXT_PRIMARY};
}}
QPushButton#SecondaryButton:focus {{
    border: 1px solid {FOCUS_RING};
}}
QLineEdit#SearchBox {{
    background: {BG_SEARCH}; border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px; padding: 4px 8px; color: {TEXT_PRIMARY};
    min-height: {CONTROL_HEIGHT}px;
}}
QLineEdit#SearchBox:focus {{ border: 1px solid {FOCUS_RING}; }}
QLineEdit {{
    min-height: {CONTROL_HEIGHT}px;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px 8px;
    background: {BG_SIDEBAR};
}}
QLineEdit:focus {{ border: 1px solid {FOCUS_RING}; }}
QComboBox {{
    min-height: {CONTROL_HEIGHT}px;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px 8px;
    background: {BG_SIDEBAR};
}}
QComboBox:focus {{ border: 1px solid {FOCUS_RING}; }}
QHeaderView::section {{
    background: {BG_HEADER};
    color: {TEXT_PRIMARY};
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    border-right: 1px solid {BORDER};
    padding: 4px 8px;
    font-weight: 600;
    min-height: {CONTROL_HEIGHT}px;
}}
QTableView, QTableWidget {{
    gridline-color: {BORDER};
    selection-background-color: #d6e6fb;
    selection-color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    background: {BG_SIDEBAR};
}}
QFrame#PanelCard {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ToolbarStrip {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#EmptyStateLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_BASE};
}}
QFrame#IconRail {{
    background: {BG_RAIL_GRADIENT};
    min-width: {ICON_RAIL_WIDTH}px; max-width: {ICON_RAIL_WIDTH}px;
}}
QToolButton[navItem="true"] {{
    background: transparent; color: {TEXT_ON_RAIL}; border: none;
    border-radius: {RADIUS_NAV_ITEM}px;
    min-width: {ICON_RAIL_ITEM_SIZE}px; max-width: {ICON_RAIL_ITEM_SIZE}px;
    min-height: {ICON_RAIL_ITEM_SIZE}px; max-height: {ICON_RAIL_ITEM_SIZE}px;
    font-size: {FONT_SIZE_NAV_LABEL}; font-weight: {FONT_WEIGHT_NAV_LABEL};
}}
QToolButton[navItem="true"]:hover {{ background: rgba(255, 255, 255, 0.08); }}
QToolButton[navItem="true"][active="true"] {{
    background: rgba(255, 255, 255, 0.18); color: {TEXT_ON_RAIL_ACTIVE};
}}
QFrame#TextSidebar {{
    background: {BG_SIDEBAR}; border-right: 1px solid {BORDER};
    min-width: {TEXT_SIDEBAR_WIDTH}px; max-width: {TEXT_SIDEBAR_WIDTH}px;
}}
QFrame#StatusBar {{
    background: {BG_SEARCH}; border-top: 1px solid {BORDER_STRONG};
    min-height: {STATUS_BAR_HEIGHT}px; max-height: {STATUS_BAR_HEIGHT}px;
    font-size: {FONT_SIZE_STATUS}; color: {TEXT_SECONDARY};
}}
QFrame#PagePlaceholder {{ background: {BG_BODY}; }}
QWidget#MapEditToolbar {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ToolbarSeparator {{
    background: {BORDER};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}
QFrame#MapLayerTree,
QFrame#MapAttributeTable,
QFrame#MapReferencePanel,
QFrame#MapCanvasPanel,
QFrame#MapChromePanel {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#MapDockTitle {{
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE_TITLE};
    font-weight: {FONT_WEIGHT_TITLE};
    border: none;
    background: transparent;
}}
QTreeWidget#MapLayerTreeWidget {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px;
}}
QTableWidget#MapAttributeTableWidget {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
}}
QLabel#StatusCoordLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_STATUS};
    font-family: "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
}}
/* Multi-panel work pages — shared dock chrome (prediction / prep / viz / sequence) */
QFrame#PredictionTaskPanel,
QFrame#PredictionEvidencePanel,
QFrame#WellLogCanvasPanel,
QFrame#SeismicTaskPanel,
QFrame#SeismicControlPanel,
QFrame#SeismicViewPanel,
QFrame#FactorTaskPanel,
QFrame#BoundaryPanel,
QFrame#VisualizationSummaryPanel,
QFrame#VisualizationTracePanel,
QFrame#CompositeVisualizationPanel,
QFrame#SequenceTargetPanel,
QFrame#SequenceBoundaryTable,
QFrame#QCIssueTable,
QFrame#FactorPreviewCard {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QListWidget#WorkListWidget {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px;
}}
QLabel#WorkFieldLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_STATUS};
    border: none;
    background: transparent;
}}
QLabel#WorkFieldValue {{
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE_TITLE};
    font-weight: 500;
    border: none;
    background: transparent;
}}
"""
