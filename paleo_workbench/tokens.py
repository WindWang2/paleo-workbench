"""Design tokens for the native Qt workstation — single source of truth.

The Workstation V3 language uses white working surfaces, cool-gray structure,
petrol selection, and restrained amber process feedback.  Its rectilinear
panels deliberately read as a scientific desktop tool rather than a web
dashboard.  Light, dark and high-contrast themes share the same vocabulary.

Every theme — light / dark / high_contrast — is a curated palette of the
same token vocabulary resolved through :func:`palette_for`; the stylesheet
below is rendered from that palette by :func:`build_qss`. Structural tokens
(metrics, spacing, type scale) are shared; color-carrying tokens are
overridden per theme. WCAG: badge chips keep white-text ratios ≥ 4.5:1 and
all primary text pairs improve on the old slate sheet (pinned in
``tests/test_tokens.py``).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Workstation palette — signal colors
# ---------------------------------------------------------------------------
PRIMARY = "#0b5563"        # petrol — selection / primary command
ACCENT = "#a65313"         # amber — focus / processing emphasis
SUCCESS = "#15803d"
WARNING = "#b45309"
ERROR = "#d31f1f"          # general error color
ERROR_RED = "#b91c1c"      # severe/QC error color
TEAL = "#0f766e"
# White desktop chrome and cool-gray hierarchy.
BG_BODY = "#f4f6f8"
BG_HEADER = "#ffffff"
BG_SIDEBAR = "#ffffff"
BG_SEARCH = "#edf1f4"
BG_RAIL = "#ffffff"
BG_RAIL_GRADIENT = "#ffffff"
BG_RAIL_TOP = "#ffffff"
BG_RAIL_BOTTOM = "#ffffff"
TEXT_PRIMARY = "#18232d"
TEXT_SECONDARY = "#53616c"
TEXT_DARK = "#101820"
TEXT_ON_RAIL = "#53616c"
TEXT_ON_RAIL_ACTIVE = "#0b5563"
BORDER = "#d6dde3"
BORDER_STRONG = "#b8c3cc"
BORDER_LIGHT = "#e6ebef"

# 数据画布深色区语义令牌（地图编辑 / 3D 视口 / 地震剖面背景）
BG_CANVAS = "#f3f5f7"
BG_CANVAS_PANEL = "rgba(255, 255, 255, 0.94)"
TEXT_ON_CANVAS = "#18232d"
BORDER_CANVAS = "rgba(83, 97, 108, 0.42)"
# QSS 内联语义色（菜单/nav 激活底 / 表格选中）
BG_NAV_ACTIVE = "#e1eef1"
BG_MENU_HOVER = "#edf2f4"
BG_SELECTION = "#d8ebef"
# 徽章专用深色（配白字达 WCAG ≥ 4.5:1；主 WARNING/SUCCESS 用于正文文字色）
BADGE_WARNING = "#92400e"            # white-on ≈ 7.1:1
BADGE_SUCCESS = "#166534"            # white-on ≈ 7.1:1
BADGE_PRIMARY = "#134e4a"            # white-on ≈ 9.5:1

PRIMARY_HOVER = "#084b58"
PRIMARY_PRESSED = "#063d48"
PRIMARY_DISABLED = "#8c99a3"
# 主色面上的文字色（浅色主题=白，深色主题=深墨，高对比=白）
ON_PRIMARY = "#ffffff"

# 图标栏交互态（深色栏专用，三主题各自策展）
BG_RAIL_HOVER = "#edf2f4"
BG_RAIL_ACTIVE = "#e1eef1"
RAIL_SEPARATOR = "rgba(83, 97, 108, 0.25)"

# 工具提示 / 分隔手柄（主题感知，修复旧深色主题下浅字浅底的提示框）
TOOLTIP_BG = "#18232d"
TOOLTIP_TEXT = "#ffffff"
SPLITTER_HANDLE = "rgba(83, 97, 108, 0.28)"
SPLITTER_HANDLE_HOVER = "rgba(11, 85, 99, 0.55)"

FOCUS_RING = ACCENT

# Glassmorphism & Micro-interaction Tokens
BG_GLASS = "rgba(255, 255, 255, 0.92)"
BG_GLASS_BORDER = "rgba(255, 255, 255, 0.55)"
SHADOW_SOFT = "0 4px 16px rgba(24, 35, 45, 0.10)"
SHADOW_CARD = "0 2px 8px rgba(24, 35, 45, 0.06)"
SHADOW_CARD_HOVER = "0 6px 20px rgba(11, 85, 99, 0.14)"
HOVER_GLOW = "#edf2f4"

FONT_FAMILY = '"Inter", "SF Pro Text", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif'
# Modular type scale (base 13px, Minor Third 1.2): ms(-2)=9, ms(-1)=11, ms(0)=13.
# Professional GIS density: 13px body (not 16px); title distinguished by
# weight 700 + one step up (14px) for stronger hierarchy than the old sheet.
FONT_SIZE_BASE = "13px"              # ms(0) — 正文 / 默认
FONT_SIZE_STATUS = "11px"            # ms(-1) — 状态栏 / 次要 / 徽章
FONT_SIZE_SIDEBAR_SECONDARY = "11px"  # ms(-1) — 对齐刻度
FONT_SIZE_NAV_LABEL = "9px"          # ms(-2) — 导航标签
FONT_WEIGHT_NAV_LABEL = "600"        # 加重以在深色栏上保持小字可读
FONT_SIZE_TITLE = "14px"             # ms(0)+1 — 面板标题抬升一档
FONT_WEIGHT_TITLE = "700"

MENU_BAR_HEIGHT = 40
HEADER_TOOLBAR_HEIGHT = 40
ICON_RAIL_WIDTH = 54
TEXT_SIDEBAR_WIDTH = 256
STATUS_BAR_HEIGHT = 26
ICON_RAIL_ITEM_SIZE = 48
RADIUS_BUTTON = 4
RADIUS_CARD = 4
RADIUS_BADGE = 4
RADIUS_PANEL = 4
RADIUS_NAV_ITEM = 4

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 20
PAGE_MARGIN = 16
PANEL_PADDING = 12
CONTROL_HEIGHT = 30
CONTROL_HEIGHT_LG = 34

ICON_FILES = [
    "home.svg", "data.svg", "well-log.svg", "seismic.svg", "sequence.svg",
    "stratigraphy.svg",
    "visualization.svg", "preparation.svg", "mapping.svg", "review.svg",
    "visualization.svg",  # fallback for 3d-modeling icon (includes joint analysis)
]

PAGE_NAMES = [
    "首页", "数据", "测井预测", "地震预测", "层序格架",
    "地层对比",
    "可视化", "制备", "编图", "成图审核", "井震联合",
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
    "井震联合 3D 视口与 Time 连井剖面",
]

# 工作流阶段色（白字徽章底色，全部 ≥ 4.5:1）
STEP_COLORS = ["#0b5563", "#a65313", "#4a5899", "#4d6b2f", "#a44a3f", "#5d564b"]
STEP_LABELS = [
    "数据管理", "数据转换", "制图数据制备",
    "沉积相预测", "古地理图编制", "质控与导出",
]
STATUS_TEXT = {
    "complete": "已完成",
    "stale": "需更新",
    "running": "处理中",
    "pending": "待开始",
    "warning": "警告",
    "failed": "异常",
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
# 「克里金」is REAL variogram ordinary kriging (geoviz_plots.factor.kriging):
# empirical variogram fit + OK solve with kriging variance output (ISS-KRIG-01
# resolved — the MVP linear placeholder is gone). The workflow routes the UI
# label to the engine method via METHOD_LABEL_TO_ENGINE.
INTERPOLATION_METHODS = ["克里金", "IDW", "约束IDW", "样条", "方向趋势"]
INTERPOLATION_METHOD_TOOLTIPS = {
    "克里金": "真实普通克里金：经验变差函数拟合 + 克里金求解（含克里金方差）",
    "IDW": "反距离加权；支持断层屏障 fault_polylines",
    "约束IDW": "约束反距离加权：断层/屏障区域分割 + 方向走廊各向异性 + 井点锚定（来自 haiyou-visualization）",
    "样条": "SciPy cubic 样条插值",
    "方向趋势": "各向异性方向加权趋势面（ISS-ALG-02）",
}
SMOOTHING_LEVELS = ["弱", "中", "强"]
SEQUENCE_SCHEMES = ["三级层序格架（推荐）", "四级高频层序", "体系域二分方案"]
SYSTEMS_TRACT_LABELS = ["LST", "TST", "HST"]



# ---------------------------------------------------------------------------
# Theme palettes: one token vocabulary, three curated palettes.
# LIGHT is the Workstation production look; DARK / HIGH_CONTRAST override the
# color-carrying tokens while inheriting every structural token unchanged.
# The light icon rail is white; dark and high-contrast palettes remain curated.
# ---------------------------------------------------------------------------

_DARK_OVERRIDES = {
    "PRIMARY": "#2dd4bf",            # 亮石化青 — 深底上的主色/文字/按钮底
    "ACCENT": "#e8863d",             # 亮铜 — 深底上的焦点/hover
    "ON_PRIMARY": "#06201d",         # 亮主色按钮上用深墨字（GitHub-dark 式）
    "BG_BODY": "#0e1514",
    "BG_HEADER": "#141c1b",
    "BG_SIDEBAR": "#151d1c",
    "BG_SEARCH": "#1d2624",
    "BG_RAIL": "#0a1211",
    "BG_RAIL_GRADIENT": (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f1a18, stop:1 #0a1211)"
    ),
    "BG_RAIL_TOP": "#0f1a18",
    "BG_RAIL_BOTTOM": "#0a1211",
    "BG_RAIL_HOVER": "#16221f",
    "BG_RAIL_ACTIVE": "#1c3a36",
    "RAIL_SEPARATOR": "rgba(169, 195, 189, 0.30)",
    "TEXT_PRIMARY": "#e8ece9",
    "TEXT_SECONDARY": "#a8b5b0",
    "TEXT_DARK": "#f2f5f2",
    "TEXT_ON_RAIL": "#a9c3bd",
    "TEXT_ON_RAIL_ACTIVE": "#e8f4f1",
    "BORDER": "#2b3432",
    "BORDER_STRONG": "#3c4744",
    "BORDER_LIGHT": "#202927",
    "BG_CANVAS": "#0b1110",
    "BG_CANVAS_PANEL": "rgba(9, 14, 13, 0.9)",
    "TEXT_ON_CANVAS": "#e8ece9",
    "BORDER_CANVAS": "rgba(78, 94, 90, 0.60)",
    "BG_NAV_ACTIVE": "#24302d",
    "BG_MENU_HOVER": "#1d2624",
    "BG_SELECTION": "#1f403c",
    "BADGE_WARNING": "#b45309",      # white-on ≈ 5.0:1（深色面板上 ≥ 3:1）
    "BADGE_SUCCESS": "#15803d",
    "BADGE_PRIMARY": "#0f766e",
    "PRIMARY_HOVER": "#5adcc9",
    "PRIMARY_PRESSED": "#1fa898",
    "PRIMARY_DISABLED": "#455350",
    "FOCUS_RING": "#e8863d",
    "TOOLTIP_BG": "#0a1211",
    "TOOLTIP_TEXT": "#e8ece9",
    "SPLITTER_HANDLE": "rgba(120, 140, 134, 0.45)",
    "SPLITTER_HANDLE_HOVER": "rgba(232, 134, 61, 0.50)",
    "BG_GLASS": "rgba(21, 29, 28, 0.90)",
    "BG_GLASS_BORDER": "rgba(60, 71, 68, 0.55)",
}

_HIGH_CONTRAST_OVERRIDES = {
    "PRIMARY": "#000000",
    "ACCENT": "#005fd0",
    "ON_PRIMARY": "#ffffff",
    "BG_BODY": "#ffffff",
    "BG_HEADER": "#ffffff",
    "BG_SIDEBAR": "#ffffff",
    "BG_SEARCH": "#ffffff",
    "BG_RAIL": "#000000",
    # solid-black gradient: "none" would paint the rail transparent and hide
    # the light-stroke nav icons — the rail must stay a dark surface in HC too
    "BG_RAIL_GRADIENT": (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #000000, stop:1 #000000)"
    ),
    "BG_RAIL_TOP": "#000000",
    "BG_RAIL_BOTTOM": "#000000",
    "BG_RAIL_HOVER": "#e6e6e6",
    "BG_RAIL_ACTIVE": "#ffffff",
    "RAIL_SEPARATOR": "rgba(255, 255, 255, 0.60)",
    "TEXT_PRIMARY": "#000000",
    "TEXT_SECONDARY": "#1a1a1a",
    "TEXT_DARK": "#000000",
    "TEXT_ON_RAIL": "#ffffff",
    "TEXT_ON_RAIL_ACTIVE": "#000000",
    "BORDER": "#000000",
    "BORDER_STRONG": "#000000",
    "BORDER_LIGHT": "#000000",
    "BG_CANVAS": "#000000",
    "BG_CANVAS_PANEL": "rgba(0, 0, 0, 0.95)",
    "TEXT_ON_CANVAS": "#ffffff",
    "BORDER_CANVAS": "rgba(255, 255, 255, 0.90)",
    "BG_NAV_ACTIVE": "#e0e0e0",
    "BG_MENU_HOVER": "#f0f0f0",
    "BG_SELECTION": "#e0e0e0",
    "PRIMARY_HOVER": "#262626",
    "PRIMARY_PRESSED": "#404040",
    "PRIMARY_DISABLED": "#757575",
    "FOCUS_RING": "#005fd0",
    "TOOLTIP_BG": "#ffffff",
    "TOOLTIP_TEXT": "#000000",
    "SPLITTER_HANDLE": "rgba(0, 0, 0, 0.60)",
    "SPLITTER_HANDLE_HOVER": "rgba(0, 95, 208, 0.80)",
    "BG_GLASS": "rgba(255, 255, 255, 0.96)",
    "BG_GLASS_BORDER": "rgba(0, 0, 0, 0.80)",
}

_THEME_OVERRIDES = {
    "light": {},
    "dark": _DARK_OVERRIDES,
    "high_contrast": _HIGH_CONTRAST_OVERRIDES,
}


def palette_for(theme: str = "light") -> dict:
    """Full token palette for *theme* (``light`` / ``dark`` / ``high_contrast``).

    Light is the Stratum production palette itself; the other themes are
    curated overrides of the same token names — never a separate vocabulary.
    """
    key = str(theme).lower().replace("-", "_")
    if key not in _THEME_OVERRIDES:
        key = "light"
    palette = {
        name: value
        for name, value in globals().items()
        if name.isupper()
        and not name.startswith("_")
        and isinstance(value, (str, int, float))
        and name not in {"INTERPOLATION_METHODS", "SMOOTHING_LEVELS", "SEQUENCE_SCHEMES", "SYSTEMS_TRACT_LABELS"}
    }
    palette.update(_THEME_OVERRIDES[key])
    return palette



def build_qss(density: str = "comfortable", theme: str = "light") -> str:
    """Render the application stylesheet from the *theme* palette.

    The stylesheet below is the single production sheet; every theme
    (light / dark / high_contrast) is a palette of the same token
    vocabulary resolved through :func:`palette_for` — never a second,
    parallel mini-stylesheet.
    """
    from types import SimpleNamespace

    t = SimpleNamespace(**palette_for(theme))
    padding_y = 6 if density == "comfortable" else 3
    padding_x = 12 if density == "comfortable" else 8
    btn_height = 30 if density == "comfortable" else 24

    return f'''
    /* ── Stratum base ─────────────────────────────────────────────── */
    QWidget {{
        font-family: {t.FONT_FAMILY};
        color: {t.TEXT_PRIMARY};
        background-color: {t.BG_BODY};
        font-size: {t.FONT_SIZE_BASE};
    }}
    QLabel {{
        background-color: transparent;
    }}
    QMainWindow, QDialog, QStackedWidget, QScrollArea, QWidget#AppShell, QWidget#HomePage, QWidget#HomeContainer, QWidget#ModuleRelationshipWidget, QWidget#ModuleRelationshipCanvas {{
        background-color: {t.BG_BODY};
    }}
    QPushButton {{
        background-color: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: {padding_y}px {padding_x}px;
        min-height: {btn_height}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {t.BG_SEARCH};
        border-color: {t.BORDER_STRONG};
    }}
    QPushButton:pressed {{
        background-color: {t.BORDER_LIGHT};
    }}
    QPushButton:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QPushButton:disabled {{
        background-color: {t.BG_SIDEBAR};
        color: {t.PRIMARY_DISABLED};
        border-color: {t.BORDER};
    }}
    QPushButton#PrimaryButton {{
        background-color: {t.PRIMARY};
        color: {t.ON_PRIMARY};
        border: 1px solid {t.PRIMARY};
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: {t.PRIMARY_HOVER};
        border-color: {t.PRIMARY_HOVER};
    }}
    QPushButton#PrimaryButton:pressed {{
        background-color: {t.PRIMARY_PRESSED};
    }}
    QPushButton#PrimaryButton:disabled {{
        background-color: {t.BG_SEARCH}; color: {t.TEXT_SECONDARY}; border: 1px solid {t.BORDER};
    }}
    QPushButton#PrimaryButton:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background-color: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: {padding_y}px {padding_x}px;
        selection-background-color: {t.PRIMARY};
        selection-color: {t.ON_PRIMARY};
        min-height: {t.CONTROL_HEIGHT}px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        background-color: {t.BG_SEARCH};
        color: {t.PRIMARY_DISABLED};
        border-color: {t.BORDER};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px;
        selection-background-color: {t.BG_NAV_ACTIVE};
        selection-color: {t.TEXT_PRIMARY};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 26px;
        padding: 2px 8px;
        border-radius: 3px;
    }}
    QCheckBox, QRadioButton {{
        background: transparent;
        spacing: 6px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER_STRONG};
    }}
    QCheckBox::indicator {{
        border-radius: 3px;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {t.ACCENT};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {t.PRIMARY};
        border-color: {t.PRIMARY};
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        background: {t.BG_SEARCH};
        border-color: {t.BORDER};
    }}
    QToolBar {{
        background-color: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        spacing: 2px;
        padding: 3px;
    }}
    QToolBar::separator {{
        width: 1px;
        background: {t.BORDER};
        margin: 4px 6px;
    }}
    QToolButton {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 3px;
    }}
    QToolButton:hover {{
        background-color: {t.BG_SEARCH};
        border: 1px solid {t.BORDER_LIGHT};
    }}
    QToolButton:pressed {{
        background-color: {t.BG_NAV_ACTIVE};
        border: 1px solid {t.BORDER_STRONG};
    }}
    QToolButton:checked {{
        background-color: {t.BG_NAV_ACTIVE};
        border: 1px solid {t.PRIMARY};
    }}
    QToolButton:disabled {{
        background-color: transparent;
        border: 1px solid transparent;
    }}
    QTableWidget, QTreeView, QListView, QTableView {{
        background-color: {t.BG_SIDEBAR};
        alternate-background-color: {t.BG_BODY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
        gridline-color: {t.BORDER_LIGHT};
        selection-background-color: {t.BG_SELECTION};
        selection-color: {t.TEXT_PRIMARY};
        outline: none;
    }}
    QTableView::item, QTreeView::item, QListView::item {{
        padding: 4px 6px;
    }}
    QTreeView::item, QListView::item {{
        border-radius: 3px;
    }}
    QTreeView::item:selected, QListView::item:selected {{
        background-color: {t.BG_SELECTION};
        color: {t.TEXT_PRIMARY};
    }}
    QTreeView::item:hover, QListView::item:hover {{
        background-color: {t.BG_SEARCH};
    }}
    QHeaderView::section {{
        background-color: {t.BG_SEARCH};
        color: {t.TEXT_SECONDARY};
        padding: 6px 10px;
        border: none;
        border-bottom: 1px solid {t.BORDER};
        border-right: 1px solid {t.BORDER};
        font-weight: 600;
        min-height: {t.CONTROL_HEIGHT}px;
    }}
    QTableCornerButton::section {{
        background-color: {t.BG_SEARCH};
        border: none;
    }}
    QTabWidget::pane {{
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
        background-color: {t.BG_SIDEBAR};
    }}
    QTabBar::tab {{
        background-color: {t.BG_SEARCH};
        color: {t.TEXT_SECONDARY};
        padding: 8px 16px;
        border-top-left-radius: {t.RADIUS_BUTTON}px;
        border-top-right-radius: {t.RADIUS_BUTTON}px;
        margin-right: 2px;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t.BG_NAV_ACTIVE};
        color: {t.TEXT_PRIMARY};
    }}
    QTabBar::tab:selected {{
        background-color: {t.BG_SIDEBAR};
        color: {t.PRIMARY};
        font-weight: 600;
        border-bottom: 2px solid {t.PRIMARY};
    }}
    QTabBar::tab:focus {{
        border-bottom: 2px solid {t.FOCUS_RING};
    }}
    QMenuBar {{
        background-color: {t.BG_HEADER};
        color: {t.TEXT_PRIMARY};
        border-bottom: 1px solid {t.BORDER};
    }}
    QMenuBar::item {{
        background-color: transparent;
        padding: 6px 12px;
        color: {t.TEXT_PRIMARY};
        border-radius: 3px;
    }}
    QMenuBar::item:selected, QMenuBar::item:pressed {{
        background-color: {t.BG_MENU_HOVER};
        color: {t.PRIMARY};
    }}
    QMenu {{
        background-color: {t.BG_HEADER};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 4px;
        padding: 4px;
    }}
    QMenu::item {{
        background-color: transparent;
        padding: 6px 24px 6px 12px;
        border-radius: 3px;
        color: {t.TEXT_PRIMARY};
    }}
    QMenu::item:selected {{
        background-color: {t.BG_MENU_HOVER};
        color: {t.PRIMARY};
    }}
    QMenu::item:disabled {{
        color: {t.PRIMARY_DISABLED};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {t.BORDER};
        margin: 4px 0px;
    }}
    QToolTip {{
        background-color: {t.TOOLTIP_BG};
        color: {t.TOOLTIP_TEXT};
        border: 1px solid {t.ACCENT};
        padding: 6px 8px;
        font-size: 12px;
    }}
    QProgressBar {{
        background-color: {t.BG_SEARCH};
        border: 1px solid {t.BORDER};
        border-radius: 5px;
        color: {t.TEXT_SECONDARY};
        text-align: center;
        font-size: {t.FONT_SIZE_STATUS};
        min-height: 14px;
    }}
    QProgressBar::chunk {{
        background-color: {t.PRIMARY};
        border-radius: 4px;
    }}
    QSplitter::handle {{
        /* 暖色常显，提示可拖动；hover 铜色高亮 */
        background-color: {t.SPLITTER_HANDLE};
    }}
    QSplitter::handle:horizontal {{
        width: 4px;
    }}
    QSplitter::handle:vertical {{
        height: 4px;
    }}
    QSplitter::handle:hover {{
        background-color: {t.SPLITTER_HANDLE_HOVER};
    }}
    QGroupBox {{
        font-weight: 600;
    }}
    QGroupBox::title {{
        color: {t.TEXT_PRIMARY};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.BORDER_STRONG};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.PRIMARY_DISABLED};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t.BORDER_STRONG};
        border-radius: 4px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {t.PRIMARY_DISABLED};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0px;
        height: 0px;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    /* ── App shell chrome ─────────────────────────────────────────── */
    QFrame#MenuBar {{
        background: {t.BG_HEADER}; border-bottom: 1px solid {t.BORDER_STRONG};
        min-height: {t.MENU_BAR_HEIGHT}px; max-height: {t.MENU_BAR_HEIGHT}px;
    }}
    /* UI v2 Ribbon (variant A) */
    QFrame#RibbonBar {{
        background: {t.BG_HEADER}; border-bottom: 1px solid {t.BORDER_STRONG};
    }}
    QFrame#RibbonTopRow {{ background: transparent; }}
    QLabel#RibbonAppBadge {{
        color: {t.TEXT_SECONDARY}; font-size: {t.FONT_SIZE_STATUS}px;
    }}
    QPushButton#RibbonTab {{
        background: transparent; border: none; border-bottom: 2px solid transparent;
        color: {t.TEXT_PRIMARY}; padding: 4px 14px; font-size: {t.FONT_SIZE_BASE}px;
    }}
    QPushButton#RibbonTab:hover {{ background: {t.BG_MENU_HOVER}; }}
    QPushButton#RibbonTab[active="true"] {{
        color: {t.PRIMARY}; border-bottom: 2px solid {t.ACCENT}; font-weight: 600;
    }}
    QPushButton#RibbonAppMenuButton {{
        background: transparent; border: none; color: {t.TEXT_PRIMARY};
        font-size: 14px; padding: 0 6px;
    }}
    QPushButton#RibbonAppMenuButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton#RibbonCollapseButton {{
        background: transparent; border: none; color: {t.TEXT_SECONDARY};
        font-size: 12px; padding: 0 6px;
    }}
    QPushButton#RibbonCollapseButton:hover {{ background: {t.BG_MENU_HOVER}; color: {t.TEXT_PRIMARY}; }}
    QFrame#RibbonBody {{ background: {t.BG_HEADER}; }}
    QFrame#RibbonGroup {{ background: transparent; }}
    QLabel#RibbonGroupCaption {{
        color: {t.TEXT_SECONDARY}; font-size: {t.FONT_SIZE_STATUS}px;
    }}
    QFrame#RibbonGroupSeparator {{
        color: {t.BORDER}; background: {t.BORDER};
        max-width: 1px; margin: 8px 2px;
    }}
    QToolButton#RibbonButton {{
        background: transparent; border: 1px solid transparent; border-radius: {t.RADIUS_BUTTON}px;
        color: {t.TEXT_PRIMARY}; padding: 3px 8px; font-size: {t.FONT_SIZE_STATUS}px;
    }}
    QToolButton#RibbonButton:hover {{ background: {t.BG_MENU_HOVER}; border-color: {t.BORDER}; }}
    QToolButton#RibbonButton:checked {{
        background: {t.PRIMARY}; color: {t.ON_PRIMARY}; border-color: {t.PRIMARY_PRESSED};
    }}
    QToolButton#RibbonButton:disabled {{ color: {t.PRIMARY_DISABLED}; }}
    QLabel#RibbonHint {{ color: {t.TEXT_SECONDARY}; font-size: {t.FONT_SIZE_STATUS}px; }}
    /* Hub sub-module pill switcher */
    QWidget#SubmoduleSwitcher {{
        background: {t.BG_HEADER}; border-bottom: 1px solid {t.BORDER_LIGHT};
    }}
    QPushButton#SubmodulePill {{
        background: {t.BG_SEARCH}; color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER}; border-radius: 14px;
        padding: 4px 16px; font-size: {t.FONT_SIZE_STATUS}px;
    }}
    QPushButton#SubmodulePill:hover {{ border-color: {t.PRIMARY}; }}
    QPushButton#SubmodulePill[active="true"] {{
        background: {t.PRIMARY}; color: {t.ON_PRIMARY}; border-color: {t.PRIMARY};
        font-weight: 600;
    }}
    QPushButton#ProjectMenuButton,
    QPushButton#ViewMenuButton,
    QPushButton#ToolsMenuButton,
    QPushButton#HelpMenuButton {{
        background: transparent; border: none; color: {t.TEXT_PRIMARY}; padding: 0;
    }}
    /* 顶部菜单条按标准菜单栏处理：隐藏下拉指示箭头，避免与文字重叠 */
    QPushButton#ProjectMenuButton::menu-indicator,
    QPushButton#ViewMenuButton::menu-indicator,
    QPushButton#ToolsMenuButton::menu-indicator,
    QPushButton#HelpMenuButton::menu-indicator {{
        image: none; width: 0;
    }}
    QPushButton#ProjectMenuButton:hover,
    QPushButton#ViewMenuButton:hover,
    QPushButton#ToolsMenuButton:hover,
    QPushButton#HelpMenuButton:hover {{ color: {t.PRIMARY}; }}
    QPushButton#DataPreviewPdfPrevious,
    QPushButton#DataPreviewPdfNext {{
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px 12px;
        min-height: {t.CONTROL_HEIGHT}px;
        background: {t.BG_SIDEBAR};
    }}
    QPushButton#DataPreviewPdfPrevious:focus,
    QPushButton#DataPreviewPdfNext:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QPushButton#SecondaryButton {{
        background: {t.BG_SIDEBAR}; color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px 12px;
        min-height: {t.CONTROL_HEIGHT}px;
    }}
    QPushButton#SecondaryButton:hover {{ background: {t.BG_SEARCH}; }}
    QPushButton#SecondaryButton:pressed {{ background: {t.BORDER_LIGHT}; }}
    QPushButton#SecondaryButton:disabled {{
        color: {t.TEXT_SECONDARY}; border-color: {t.BORDER};
    }}
    QPushButton#SecondaryButton:checked {{
        background: {t.BG_SEARCH}; border-color: {t.PRIMARY}; color: {t.TEXT_PRIMARY};
    }}
    QPushButton#SecondaryButton:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QLineEdit#SearchBox {{
        background: {t.BG_SEARCH}; border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px; padding: 4px 8px; color: {t.TEXT_PRIMARY};
        min-height: {t.CONTROL_HEIGHT}px;
    }}
    QLineEdit#SearchBox:focus {{ border: 1px solid {t.FOCUS_RING}; }}
    QFrame#PanelCard {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QFrame#WellMapPanel {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QFrame#WellMapPanelHeader {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.BORDER};
    }}
    QToolButton#WellMapPanelToggle {{
        background: transparent;
        border: none;
        color: {t.TEXT_PRIMARY};
        font-weight: 600;
        padding: 2px 4px;
    }}
    QLabel#WellMapPanelCount {{
        color: {t.TEXT_SECONDARY};
    }}
    QFrame#ToolbarStrip {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QLabel#EmptyStateLabel {{
        color: {t.TEXT_SECONDARY};
        font-size: {t.FONT_SIZE_BASE};
    }}

    /* 深色图标栏：三主题统一深石板底，激活项带铜色指示条 */
    QFrame#IconRail {{
        background: {t.BG_RAIL_GRADIENT};
        border-right: 1px solid {t.BORDER};
        min-width: {t.ICON_RAIL_WIDTH}px; max-width: {t.ICON_RAIL_WIDTH}px;
    }}
    QFrame#RailSeparator {{
        background: {t.RAIL_SEPARATOR};
        border: none;
        min-height: 1px;
        max-height: 1px;
        margin: 3px 8px;
    }}
    QToolButton[navItem="true"] {{
        background: transparent; color: {t.TEXT_ON_RAIL}; border: none;
        border-left: 3px solid transparent;
        border-radius: {t.RADIUS_NAV_ITEM}px;
        min-width: {t.ICON_RAIL_ITEM_SIZE}px; max-width: {t.ICON_RAIL_ITEM_SIZE}px;
        min-height: {t.ICON_RAIL_ITEM_SIZE}px; max-height: {t.ICON_RAIL_ITEM_SIZE}px;
        font-size: {t.FONT_SIZE_NAV_LABEL}; font-weight: {t.FONT_WEIGHT_NAV_LABEL};
    }}
    QToolButton[navItem="true"]:hover {{ background: {t.BG_RAIL_HOVER}; color: {t.TEXT_ON_RAIL_ACTIVE}; }}
    QToolButton[navItem="true"]:focus {{ outline: 2px solid {t.FOCUS_RING}; }}
    QToolButton[navItem="true"][active="true"] {{
        background: {t.BG_RAIL_ACTIVE}; color: {t.TEXT_ON_RAIL_ACTIVE};
        border-left: 3px solid {t.ACCENT}; font-weight: 600;
    }}
    /* Generic QToolButton focus (covers QToolButton beyond the icon rail) */
    QToolButton:focus {{ border: 1px solid {t.FOCUS_RING}; }}
    QFrame#StatusBar {{
        background: {t.BG_SEARCH}; border-top: 1px solid {t.BORDER_STRONG};
        min-height: {t.STATUS_BAR_HEIGHT}px; max-height: {t.STATUS_BAR_HEIGHT}px;
        font-size: {t.FONT_SIZE_STATUS}; color: {t.TEXT_SECONDARY};
    }}
    QFrame#MapStatusBar {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        font-size: {t.FONT_SIZE_STATUS};
        color: {t.TEXT_SECONDARY};
    }}
    QFrame#PagePlaceholder {{ background: {t.BG_BODY}; }}
    QWidget#MapEditToolbar {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QFrame#ToolbarSeparator {{
        background: {t.BORDER};
        border: none;
        max-width: 1px;
        min-width: 1px;
    }}
    QFrame#MapLayerTree,
    QFrame#MapAttributeTable,
    QFrame#MapReferencePanel,
    QFrame#MapCanvasPanel,
    QFrame#MapChromePanel {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QLabel#MapDockTitle {{
        color: {t.TEXT_PRIMARY};
        font-size: {t.FONT_SIZE_TITLE};
        font-weight: {t.FONT_WEIGHT_TITLE};
        border: none;
        border-left: 3px solid {t.ACCENT};
        padding-left: 8px;
        background: transparent;
    }}
    QFrame#MapDockRail {{
        background: {t.BG_RAIL_GRADIENT};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QFrame#MapDockArea {{
        background: transparent;
        border: none;
    }}
    QToolButton[dockRailItem="true"] {{
        background: transparent;
        color: {t.TEXT_ON_RAIL};
        border: 1px solid transparent;
        border-radius: {t.RADIUS_BUTTON}px;
    }}
    QToolButton[dockRailItem="true"]:hover {{
        background: {t.BG_RAIL_HOVER};
        color: {t.TEXT_ON_RAIL_ACTIVE};
        border: 1px solid {t.BORDER_LIGHT};
    }}
    QToolButton[dockRailItem="true"]:checked {{
        background: {t.BG_RAIL_ACTIVE};
        color: {t.TEXT_ON_RAIL_ACTIVE};
        border: 1px solid {t.ACCENT};
    }}
    QToolButton[dockRailItem="true"]:focus {{
        border: 1px solid {t.FOCUS_RING};
    }}
    QToolButton#MapPanelsMenuButton {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px;
    }}
    QToolButton#MapPanelsMenuButton:hover {{
        background: {t.BG_SEARCH};
        border-color: {t.BORDER_STRONG};
    }}
    QToolButton#MapPanelsMenuButton::menu-indicator {{
        image: none;
        width: 0px;
    }}
    QTreeWidget#MapLayerTreeWidget {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 2px;
    }}
    QTableWidget#MapAttributeTableWidget {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
    }}
    QLabel#StatusCoordLabel {{
        color: {t.TEXT_SECONDARY};
        font-size: {t.FONT_SIZE_STATUS};
        font-family: "JetBrains Mono", "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
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
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QListWidget#WorkListWidget {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 2px;
    }}
    QFrame#WorkflowStepper {{
        background: {t.BG_HEADER};
        border-bottom: 1px solid {t.BORDER};
    }}
    QPushButton[stageItem="true"] {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        font-size: {t.FONT_SIZE_BASE};
        font-weight: 500;
        border: 1px solid transparent;
        border-radius: 16px;
        padding: 4px 12px;
    }}
    QPushButton[stageItem="true"]:hover {{
        background: {t.BG_SEARCH};
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton[stageItem="true"][active="true"] {{
        background: {t.PRIMARY};
        color: {t.ON_PRIMARY};
        font-weight: 600;
    }}
    QLabel#StepperArrow {{
        color: {t.TEXT_SECONDARY};
        font-size: 13px;
        font-weight: bold;
    }}
    QLabel#WorkFieldLabel {{
        color: {t.TEXT_SECONDARY};
        font-size: {t.FONT_SIZE_STATUS};
        border: none;
        background: transparent;
    }}
    QLabel#WorkFieldValue {{
        color: {t.TEXT_PRIMARY};
        font-size: {t.FONT_SIZE_TITLE};
        font-weight: 500;
        border: none;
        background: transparent;
    }}

    QWidget#SeismicPredictionPage {{
        background: {t.BG_BODY};
    }}
    QWidget#SeismicPredictionPage QLabel#MapDockTitle,
    QWidget#SeismicPredictionPage QLabel#WorkFieldValue {{
        color: {t.TEXT_PRIMARY};
    }}
    QWidget#SeismicPredictionPage QLabel#WorkFieldLabel {{
        color: {t.TEXT_SECONDARY};
    }}
    QTreeWidget#SeismicAttributeTree {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px;
    }}
    QTreeWidget#SeismicAttributeTree::item {{
        padding: 5px 4px;
        border-radius: 3px;
    }}
    QTreeWidget#SeismicAttributeTree::item:selected {{
        background: {t.PRIMARY};
        color: {t.ON_PRIMARY};
    }}
    QTreeWidget#SeismicAttributeTree::item:hover {{
        background: {t.BG_SEARCH};
    }}
    QFrame#SeismicAttributeCard {{
        background: {t.BG_SEARCH};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
    }}
    QFrame#SeismicViewHost {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
    }}
    QLabel#SeismicAttributeCardLabel {{
        color: {t.TEXT_PRIMARY};
        font-weight: 600;
        font-size: {t.FONT_SIZE_STATUS};
    }}
    QLabel#SeismicAttributeCardStatus {{
        color: {t.SUCCESS};
        font-size: {t.FONT_SIZE_STATUS};
    }}
    QWidget#SeismicPredictionPage QPushButton#SecondaryButton {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER};
    }}
    QWidget#SeismicPredictionPage QComboBox {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER};
    }}

    /* ── Workstation V3: native Qt shell ─────────────────────────── */
    QWidget#WorkstationFrame,
    QFrame#WorkstationDocumentRegion,
    QStackedWidget#WorkstationDocumentStack,
    QWidget#LinkedInterpretationWorkspace {{
        background: {t.BG_BODY};
        border: none;
    }}
    QFrame#WorkstationAppBar {{
        background: {t.BG_HEADER};
        border: none;
        border-bottom: 1px solid {t.BORDER_STRONG};
    }}
    QLabel#WorkstationBrand {{
        color: {t.TEXT_PRIMARY};
        font-size: 14px;
        font-weight: 700;
        padding-right: 8px;
    }}
    QToolButton#WorkstationProjectButton {{
        background: transparent;
        color: {t.TEXT_PRIMARY};
        border: none;
        border-left: 1px solid {t.BORDER};
        border-radius: 0px;
        padding: 4px 10px;
        font-weight: 600;
    }}
    QToolButton#WorkstationProjectButton:hover {{
        background: {t.BG_MENU_HOVER};
    }}
    QLineEdit#WorkstationCommandInput {{
        background: {t.BG_BODY};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 4px;
        min-height: 28px;
        padding: 2px 10px;
    }}
    QLineEdit#WorkstationCommandInput:focus {{
        background: {t.BG_SIDEBAR};
        border-color: {t.PRIMARY};
    }}
    QToolButton#WorkstationChromeButton,
    QToolButton#WorkstationSyncState,
    QToolButton#WorkstationTaskButton,
    QToolButton#WorkstationAgentButton {{
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
        border-radius: 3px;
        min-height: 26px;
        padding: 2px 7px;
    }}
    QToolButton#WorkstationSyncState {{
        color: {t.PRIMARY};
    }}
    QToolButton#WorkstationTaskButton[activeTasks="true"] {{
        color: {t.WARNING};
        background: {t.BG_SEARCH};
    }}
    QToolButton#WorkstationAgentButton {{
        color: {t.PRIMARY};
        border-color: {t.BORDER};
        font-weight: 600;
    }}
    QFrame#WorkstationNavigationRegion,
    QFrame#WorkstationActivityRail,
    QFrame#WorkstationExplorer,
    QFrame#WorkstationInspector,
    QFrame#WorkstationProcessHub {{
        background: {t.BG_SIDEBAR};
        border: none;
    }}
    QFrame#WorkstationActivityRail {{
        border-right: 1px solid {t.BORDER};
    }}
    QFrame#WorkstationExplorer {{
        border-right: 1px solid {t.BORDER_STRONG};
    }}
    QToolButton#WorkstationActivityButton {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0px;
        padding: 3px 1px;
        font-size: 9px;
        font-weight: 600;
    }}
    QToolButton#WorkstationActivityButton:hover {{
        background: {t.BG_RAIL_HOVER};
        color: {t.TEXT_PRIMARY};
    }}
    QToolButton#WorkstationActivityButton:checked {{
        background: {t.BG_RAIL_ACTIVE};
        color: {t.PRIMARY};
        border-left: 3px solid {t.PRIMARY};
    }}
    QToolButton#WorkstationRailCollapseButton {{
        color: {t.TEXT_SECONDARY};
        border: none;
        border-top: 1px solid {t.BORDER};
        border-radius: 0px;
        min-height: 24px;
    }}
    QLabel#WorkstationPanelTitle,
    QLabel#WorkstationInspectorHeader {{
        color: {t.TEXT_PRIMARY};
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#WorkstationInspectorHeader {{
        min-height: 30px;
        padding: 0px 10px;
        border-bottom: 1px solid {t.BORDER};
    }}
    QLabel#WorkstationPanelFootnote,
    QLabel#WorkstationAgentContext {{
        color: {t.TEXT_SECONDARY};
        font-size: 11px;
    }}
    QLineEdit#WorkstationExplorerSearch,
    QLineEdit#WorkstationAgentInput {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        min-height: 28px;
        padding: 2px 7px;
    }}
    /* Inspector 字段值：可选取的只读 editor —— 扁平浅底，缺失值弱化 */
    QLineEdit#WorkstationInspectorValue {{
        background: {t.BG_BODY};
        color: {t.TEXT_PRIMARY};
        border: 1px solid transparent;
        border-radius: 2px;
        min-height: 24px;
        padding: 1px 6px;
        selection-background-color: {t.BG_SELECTION};
        selection-color: {t.TEXT_PRIMARY};
    }}
    QLineEdit#WorkstationInspectorValue:hover {{
        border-color: {t.BG_SEARCH};
    }}
    QLineEdit#WorkstationInspectorValue:focus {{
        border-color: {t.BORDER_STRONG};
        background: {t.BG_SIDEBAR};
    }}
    QLineEdit#WorkstationInspectorValue[missing="true"] {{
        color: {t.TEXT_SECONDARY};
        font-style: italic;
    }}
    QTreeView#WorkstationExplorerTree {{
        background: {t.BG_SIDEBAR};
        border: none;
        border-top: 1px solid {t.BORDER_LIGHT};
        border-radius: 0px;
        padding-top: 3px;
    }}
    QTreeView#WorkstationExplorerTree::item {{
        min-height: 22px;
        padding: 1px 4px;
        border-radius: 0px;
    }}
    QTreeView#WorkstationExplorerTree::item:selected {{
        background: {t.BG_SELECTION};
        color: {t.TEXT_PRIMARY};
        border-left: 2px solid {t.PRIMARY};
    }}
    QTabBar#WorkstationDocumentTabs {{
        background: {t.BG_SEARCH};
        border-bottom: 1px solid {t.BORDER_STRONG};
    }}
    QTabBar#WorkstationDocumentTabs::tab {{
        background: {t.BG_SEARCH};
        color: {t.TEXT_SECONDARY};
        border: none;
        border-right: 1px solid {t.BORDER};
        border-radius: 0px;
        min-height: 32px;
        max-height: 32px;
        padding: 0px 12px;
        margin: 0px;
    }}
    QTabBar#WorkstationDocumentTabs::tab:selected {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border-top: 2px solid {t.PRIMARY};
        font-weight: 600;
    }}
    QFrame#WorkstationContextBar {{
        background: {t.BG_SIDEBAR};
        border: none;
        border-bottom: 1px solid {t.BORDER};
    }}
    /* Composite full-bleed overlay: hairline float strip, no SaaS card chrome */
    QFrame#WorkstationOverlayToolbar {{
        background: {t.BG_HEADER};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 3px;
        padding: 0px;
    }}
    QFrame#WorkstationContextSeparator {{
        background: {t.BORDER};
        border: none;
        margin: 5px 3px;
    }}
    QToolButton#WorkstationContextButton,
    QToolButton#WorkstationLinkButton {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
        border-radius: 3px;
        padding: 3px 7px;
    }}
    QToolButton#WorkstationContextButton:hover,
    QToolButton#WorkstationLinkButton:hover {{
        background: {t.BG_SEARCH};
        color: {t.TEXT_PRIMARY};
    }}
    QToolButton#WorkstationLinkButton:checked {{
        background: {t.BG_SELECTION};
        color: {t.PRIMARY};
        border-color: {t.PRIMARY};
    }}
    QFrame#WorkstationDocumentPane {{
        background: {t.BG_SIDEBAR};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 2px;
    }}
    QFrame#WorkstationDocumentPaneHeader {{
        background: {t.BG_SEARCH};
        border: none;
        border-bottom: 1px solid {t.BORDER};
    }}
    QLabel#WorkstationDocumentPaneTitle {{
        color: {t.TEXT_PRIMARY};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#WorkstationLinkBadge {{
        color: {t.PRIMARY};
        background: {t.BG_SELECTION};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        padding: 1px 5px;
        font-size: 10px;
    }}
    QFrame#WorkstationDocumentPaneHost {{
        background: {t.BG_SIDEBAR};
        border: none;
    }}
    QLabel#WorkstationDocumentEmptyState {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px dashed {t.BORDER_STRONG};
        border-radius: 4px;
        font-size: 12px;
        padding: 18px 14px;
    }}
    QFrame#WorkstationInspector {{
        border-left: 1px solid {t.BORDER_STRONG};
    }}
    QTabWidget#WorkstationInspectorTabs::pane,
    QTabWidget#WorkstationProcessTabs::pane {{
        background: {t.BG_SIDEBAR};
        border: none;
        border-top: 1px solid {t.BORDER};
        border-radius: 0px;
    }}
    QTabWidget#WorkstationInspectorTabs QTabBar::tab,
    QTabWidget#WorkstationProcessTabs QTabBar::tab {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_SECONDARY};
        border: none;
        border-radius: 0px;
        padding: 5px 10px;
    }}
    QTabWidget#WorkstationInspectorTabs QTabBar::tab:selected,
    QTabWidget#WorkstationProcessTabs QTabBar::tab:selected {{
        color: {t.PRIMARY};
        border-bottom: 2px solid {t.PRIMARY};
        font-weight: 600;
    }}
    QFrame#WorkstationProcessHub {{
        border-top: 1px solid {t.BORDER_STRONG};
    }}
    /* 综合编修 / shell：可浮动 dock 标题条（对齐 V3 light tokens） */
    QDockWidget {{
        color: {t.TEXT_PRIMARY};
        font-size: 12px;
        border: 1px solid {t.BORDER};
        border-radius: 0px;
    }}
    QDockWidget::title {{
        background: {t.BG_HEADER};
        color: {t.TEXT_PRIMARY};
        border: none;
        border-bottom: 1px solid {t.BORDER};
        padding: 5px 10px;
        font-weight: 700;
        text-align: left;
    }}
    QDockWidget::title:hover {{
        background: {t.BG_SEARCH};
    }}
    QDockWidget::close-button,
    QDockWidget::float-button {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 2px;
        padding: 1px;
        icon-size: 12px;
    }}
    QDockWidget::close-button:hover,
    QDockWidget::float-button:hover {{
        background: {t.BG_SEARCH};
        border-color: {t.BORDER};
    }}
    /* FloatController top-level chrome (mapping / legacy float path) */
    QWidget#FloatingPanel {{
        background: {t.BG_HEADER};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 3px;
    }}
    QWidget#FloatingPanelTitleBar {{
        background: {t.BG_HEADER};
        border: none;
        border-bottom: 1px solid {t.BORDER};
        min-height: 28px;
        max-height: 28px;
    }}
    QLabel#FloatingPanelTitle {{
        color: {t.TEXT_PRIMARY};
        font-size: 12px;
        font-weight: 700;
        padding-left: 2px;
    }}
    QWidget#FloatingPanelContent {{
        background: {t.BG_SIDEBAR};
        border: none;
    }}
    QTextBrowser#WorkstationAgentHistory {{
        background: {t.BG_SIDEBAR};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        padding: 5px;
    }}
    QLabel#WorkstationAgentConsent {{
        color: {t.TEXT_SECONDARY};
        background: {t.BG_SEARCH};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        padding: 4px 7px;
    }}
    QTreeWidget#WorkstationTaskTree {{
        background: {t.BG_SIDEBAR};
        border: none;
        border-radius: 0px;
    }}
    QTreeWidget#WorkstationTaskTree::item {{
        min-height: 24px;
    }}
    /* 任务进度：slim 无边框条，颜色按任务状态（运行=amber 过程色） */
    QProgressBar#WorkstationTaskProgress {{
        background: {t.BG_SEARCH};
        border: none;
        border-radius: 3px;
        min-height: 6px;
        max-height: 6px;
    }}
    QProgressBar#WorkstationTaskProgress::chunk {{
        background-color: {t.PRIMARY};
        border-radius: 3px;
    }}
    QProgressBar#WorkstationTaskProgress[taskState="running"]::chunk {{
        background-color: {t.ACCENT};
    }}
    QProgressBar#WorkstationTaskProgress[taskState="queued"]::chunk {{
        background-color: {t.PRIMARY_DISABLED};
    }}
    QProgressBar#WorkstationTaskProgress[taskState="done"]::chunk {{
        background-color: {t.SUCCESS};
    }}
    QProgressBar#WorkstationTaskProgress[taskState="failed"]::chunk {{
        background-color: {t.ERROR_RED};
    }}
    QPushButton#WorkstationTertiaryButton {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        min-height: 26px;
        padding: 2px 8px;
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
