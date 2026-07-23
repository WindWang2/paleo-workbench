"""Design tokens for the AppShell — single source of truth.

All values extracted from the standalone prototype via headless browser
computed-CSS inspection. See docs/superpowers/specs/2026-07-05-appshell-design.md.
"""
from __future__ import annotations

# Slate 石墨专业调色板 (ArcGIS Pro 浅色质感): 深板岩蓝主色 + 天青强调。
PRIMARY = "#334155"        # 深板岩蓝 — 主色 / 强调控件 / 激活态
ACCENT = "#0ea5e9"         # 天青 — hover 强调 / 微交互高光
SUCCESS = "#059669"
WARNING = "#d97706"
ERROR = "#dc2626"          # general error color
ERROR_RED = "#b91c1c"      # severe/QC error color
TEAL = "#0d9488"
# UI 框架背景层（浅色）
BG_BODY = "#f1f5f9"        # 冷灰 — 页面画布区底色
BG_HEADER = "#ffffff"
BG_SIDEBAR = "#ffffff"
BG_SEARCH = "#f1f5f9"      # 输入框 / hover 底色
BG_RAIL = "#ffffff"
BG_RAIL_GRADIENT = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8fafc)"
BG_RAIL_TOP = "#ffffff"
BG_RAIL_BOTTOM = "#f8fafc"
TEXT_PRIMARY = "#0f172a"
TEXT_SECONDARY = "#475569"
TEXT_DARK = "#020617"
TEXT_ON_RAIL = "#475569"
TEXT_ON_RAIL_ACTIVE = "#334155"
BORDER = "#e2e8f0"
BORDER_STRONG = "#cbd5e1"
BORDER_LIGHT = "#f1f5f9"

# 数据画布深色区语义令牌（地图编辑 / 3D 视口 / 地震剖面背景）
BG_CANVAS = "#1e293b"                # 画布深色底
BG_CANVAS_PANEL = "rgba(15, 23, 42, 0.88)"   # 画布上浮层栏
TEXT_ON_CANVAS = "#f1f5f9"           # 画布上文字
BORDER_CANVAS = "rgba(51, 65, 85, 0.85)"     # 画布上边框
# QSS 内联语义色（菜单/nav 激活底 / 表格选中）
BG_NAV_ACTIVE = "#e2e8f0"            # 冷灰中性激活底（非蓝调）
BG_MENU_HOVER = "#f1f5f9"
BG_SELECTION = "#dbeafe"             # 表格选中（天青浅）

PRIMARY_HOVER = "#1e293b"
PRIMARY_PRESSED = "#0f172a"
PRIMARY_DISABLED = "#94a3b8"
FOCUS_RING = ACCENT

# Glassmorphism & Micro-interaction Tokens
BG_GLASS = "rgba(255, 255, 255, 0.88)"
BG_GLASS_BORDER = "rgba(255, 255, 255, 0.6)"
SHADOW_SOFT = "0 4px 16px rgba(15, 23, 42, 0.08)"
SHADOW_CARD = "0 2px 8px rgba(15, 23, 42, 0.05)"
SHADOW_CARD_HOVER = "0 6px 20px rgba(14, 165, 233, 0.14)"
HOVER_GLOW = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(14, 165, 233, 0.08), stop:1 rgba(51, 65, 85, 0.04))"

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
RADIUS_BUTTON = 6
RADIUS_CARD = 10
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
    "visualization.svg",  # fallback for 3d-modeling icon
]

PAGE_NAMES = [
    "首页", "数据", "测井预测", "地震预测", "层序格架",
    "地层对比",
    "可视化", "制备", "编图", "成图审核", "三维建模",
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
    "三维地质建模与剖面雕刻",
]

STEP_COLORS = ["#334155", "#0ea5e9", "#6366f1", WARNING, "#e2705b", "#7e8794"]
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


def build_qss(density: str = "comfortable") -> str:
    padding_y = 6 if density == "comfortable" else 3
    padding_x = 12 if density == "comfortable" else 8
    btn_height = 30 if density == "comfortable" else 24

    return f'''
    QWidget {{
        font-family: {FONT_FAMILY};
        color: {TEXT_PRIMARY};
        background-color: {BG_BODY};
        font-size: {FONT_SIZE_BASE};
    }}
    QLabel {{
        background-color: transparent;
    }}
    QMainWindow, QDialog, QStackedWidget, QScrollArea, QWidget#AppShell, QWidget#HomePage, QWidget#HomeContainer, QWidget#ModuleRelationshipWidget, QWidget#ModuleRelationshipCanvas {{
        background-color: {BG_BODY};
    }}
    QPushButton {{
        background-color: {BG_SIDEBAR};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
        padding: {padding_y}px {padding_x}px;
        min-height: {btn_height}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {BG_SEARCH};
        border-color: {BORDER_STRONG};
    }}
    QPushButton:pressed {{
        background-color: {BORDER_LIGHT};
    }}
    QPushButton#PrimaryButton {{
        background-color: {PRIMARY};
        color: #ffffff;
        border: 1px solid {PRIMARY};
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: {PRIMARY_HOVER};
        border-color: {PRIMARY_HOVER};
    }}
    QPushButton#PrimaryButton:pressed {{
        background-color: {PRIMARY_PRESSED};
    }}
    QPushButton#PrimaryButton:disabled {{
        background-color: {PRIMARY_DISABLED}; color: #ffffff; border: none;
    }}
    QPushButton#PrimaryButton:focus {{
        border: 1px solid {FOCUS_RING};
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background-color: {BG_SIDEBAR};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
        padding: {padding_y}px {padding_x}px;
        selection-background-color: {PRIMARY};
        selection-color: #ffffff;
        min-height: {CONTROL_HEIGHT}px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {PRIMARY};
    }}
    QTableWidget, QTreeView, QListView, QTableView {{
        background-color: {BG_SIDEBAR};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CARD}px;
        gridline-color: {BORDER_LIGHT};
        selection-background-color: {BG_SELECTION};
        selection-color: {TEXT_PRIMARY};
    }}
    QHeaderView::section {{
        background-color: {BG_SEARCH};
        color: {TEXT_SECONDARY};
        padding: 6px 10px;
        border: none;
        border-bottom: 1px solid {BORDER};
        border-right: 1px solid {BORDER};
        font-weight: 600;
        min-height: {CONTROL_HEIGHT}px;
    }}
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CARD}px;
        background-color: {BG_SIDEBAR};
    }}
    QTabBar::tab {{
        background-color: {BG_SEARCH};
        color: {TEXT_SECONDARY};
        padding: 8px 16px;
        border-top-left-radius: {RADIUS_BUTTON}px;
        border-top-right-radius: {RADIUS_BUTTON}px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {BG_SIDEBAR};
        color: {PRIMARY};
        font-weight: 600;
        border-bottom: 2px solid {PRIMARY};
    }}
    QMenuBar {{
        background-color: {BG_HEADER};
        color: {TEXT_PRIMARY};
        border-bottom: 1px solid {BORDER};
    }}
    QMenuBar::item {{
        background-color: transparent;
        padding: 6px 12px;
        color: {TEXT_PRIMARY};
        border-radius: 4px;
    }}
    QMenuBar::item:selected, QMenuBar::item:pressed {{
        background-color: {BG_SEARCH};
        color: {PRIMARY};
    }}
    QMenu {{
        background-color: {BG_HEADER};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        background-color: transparent;
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
        color: {TEXT_PRIMARY};
    }}
    QMenu::item:selected {{
        background-color: {BG_MENU_HOVER};
        color: {PRIMARY};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER};
        margin: 4px 0px;
    }}

    QFrame#MenuBar {{
        background: {BG_HEADER}; border-bottom: 1px solid {BORDER_STRONG};
        min-height: {MENU_BAR_HEIGHT}px; max-height: {MENU_BAR_HEIGHT}px;
    }}
    QPushButton#ProjectMenuButton,
    QPushButton#ToolsMenuButton {{
        background: transparent; border: none; color: {TEXT_PRIMARY}; padding: 0;
    }}
    QPushButton#ProjectMenuButton:hover,
    QPushButton#ToolsMenuButton:hover {{ color: {PRIMARY}; }}
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
        border-right: 1px solid {BORDER};
        min-width: {ICON_RAIL_WIDTH}px; max-width: {ICON_RAIL_WIDTH}px;
    }}
    QToolButton[navItem="true"] {{
        background: transparent; color: {TEXT_ON_RAIL}; border: none;
        border-radius: {RADIUS_NAV_ITEM}px;
        min-width: {ICON_RAIL_ITEM_SIZE}px; max-width: {ICON_RAIL_ITEM_SIZE}px;
        min-height: {ICON_RAIL_ITEM_SIZE}px; max-height: {ICON_RAIL_ITEM_SIZE}px;
        font-size: {FONT_SIZE_NAV_LABEL}; font-weight: {FONT_WEIGHT_NAV_LABEL};
    }}
    QToolButton[navItem="true"]:hover {{ background: {BG_SEARCH}; color: {PRIMARY}; }}
    QToolButton[navItem="true"][active="true"] {{
        background: {BG_NAV_ACTIVE}; color: {TEXT_ON_RAIL_ACTIVE}; font-weight: 600;
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
    QFrame#PredictionTaskPanel,
    QFrame#PredictionEvidencePanel,
    QFrame#WellLogCanvasPanel,
    QFrame#SeismicTaskPanel,
    QFrame#SeismicControlPanel,
    QFrame#SeismicViewPanel,
    QFrame#SeismicAttributePanel,
    QFrame#SeismicContextToolbar,
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
    QFrame#WorkflowStepper {{
        background: {BG_HEADER};
        border-bottom: 1px solid {BORDER};
    }}
    QPushButton[stageItem="true"] {{
        background: transparent;
        color: {TEXT_SECONDARY};
        font-size: 12px;
        font-weight: 500;
        border: 1px solid transparent;
        border-radius: 18px;
        padding: 4px 12px;
    }}
    QPushButton[stageItem="true"]:hover {{
        background: {BG_SEARCH};
        color: {TEXT_PRIMARY};
    }}
    QPushButton[stageItem="true"][active="true"] {{
        background: {PRIMARY};
        color: #ffffff;
        font-weight: 600;
    }}
    QLabel#StepperArrow {{
        color: {TEXT_SECONDARY};
        font-size: 14px;
        font-weight: bold;
    }}
    QFrame#ContextSidebar {{
        background: {BG_SIDEBAR};
        border-right: 1px solid {BORDER};
    }}
    QPushButton[subpageItem="true"] {{
        background: {BG_SEARCH};
        color: {TEXT_PRIMARY};
        font-size: 11.5px;
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
        padding: 4px 8px;
    }}
    QPushButton[subpageItem="true"]:hover {{
        border-color: {PRIMARY};
    }}
    QPushButton[subpageItem="true"][active="true"] {{
        background: {PRIMARY};
        color: #ffffff;
        border-color: {PRIMARY};
        font-weight: 600;
    }}
    QPushButton#SidebarCollapseBtn {{
        background: transparent;
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
    }}
    QPushButton#SidebarCollapseBtn:hover {{
        background: {BG_SEARCH};
        color: {TEXT_PRIMARY};
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

    QWidget#SeismicPredictionPage {{
        background: {BG_BODY};
    }}
    QWidget#SeismicPredictionPage QLabel#MapDockTitle,
    QWidget#SeismicPredictionPage QLabel#WorkFieldValue {{
        color: {TEXT_PRIMARY};
    }}
    QWidget#SeismicPredictionPage QLabel#WorkFieldLabel {{
        color: {TEXT_SECONDARY};
    }}
    QTreeWidget#SeismicAttributeTree {{
        background: {BG_SIDEBAR};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
        padding: 4px;
    }}
    QTreeWidget#SeismicAttributeTree::item {{
        padding: 5px 4px;
        border-radius: 3px;
    }}
    QTreeWidget#SeismicAttributeTree::item:selected {{
        background: {PRIMARY};
        color: #ffffff;
    }}
    QTreeWidget#SeismicAttributeTree::item:hover {{
        background: {BG_SEARCH};
    }}
    QFrame#SeismicAttributeCard {{
        background: {BG_SEARCH};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
    }}
    QFrame#SeismicViewHost {{
        background: {BG_SIDEBAR};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_BUTTON}px;
    }}
    QLabel#SeismicAttributeCardLabel {{
        color: {TEXT_PRIMARY};
        font-weight: 600;
        font-size: {FONT_SIZE_STATUS};
    }}
    QLabel#SeismicAttributeCardStatus {{
        color: {SUCCESS};
        font-size: {FONT_SIZE_STATUS};
    }}
    QWidget#SeismicPredictionPage QPushButton#SecondaryButton {{
        background: {BG_SIDEBAR};
        color: {TEXT_PRIMARY};
        border-color: {BORDER};
    }}
    QWidget#SeismicPredictionPage QComboBox {{
        background: {BG_SIDEBAR};
        color: {TEXT_PRIMARY};
        border-color: {BORDER};
    }}
    '''

QSS_TEMPLATE = build_qss()

def format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    if size_bytes >= 1024 * 1024:
        val = size_bytes / (1024 * 1024)
        return f"{val:.1f} M" if val % 1 != 0 else f"{int(val)} M"
    elif size_bytes >= 1024:
        val = size_bytes / 1024
        return f"{val:.1f} K" if val % 1 != 0 else f"{int(val)} K"
    else:
        return f"{size_bytes} B"
def build_modern_qss(font_size: int = 12, density: str = "comfortable") -> str:
    return build_qss(density=density)
