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

FONT_FAMILY = '"PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_SIZE_BASE = "12.5px"
FONT_SIZE_STATUS = "11px"
FONT_SIZE_SIDEBAR_SECONDARY = "10.5px"
FONT_SIZE_NAV_LABEL = "9.5px"
FONT_WEIGHT_NAV_LABEL = "500"

MENU_BAR_HEIGHT = 36
HEADER_TOOLBAR_HEIGHT = 38
ICON_RAIL_WIDTH = 60
TEXT_SIDEBAR_WIDTH = 248
STATUS_BAR_HEIGHT = 24
ICON_RAIL_ITEM_SIZE = 46
RADIUS_BUTTON = 5
RADIUS_CARD = 9
RADIUS_BADGE = 8
RADIUS_PANEL = 10
RADIUS_NAV_ITEM = 8

ICON_FILES = [
    "home.svg", "data.svg", "well-log.svg", "seismic.svg", "sequence.svg",
    "visualization.svg", "preparation.svg", "mapping.svg", "review.svg",
]

PAGE_NAMES = [
    "首页", "数据", "测井预测", "地震预测", "层序格架",
    "可视化", "制备", "编图", "成图审核",
]

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
QFrame#HeaderToolbar {{
    background: {BG_HEADER}; border-bottom: 1px solid {BORDER};
    min-height: {HEADER_TOOLBAR_HEIGHT}px; max-height: {HEADER_TOOLBAR_HEIGHT}px;
}}
QPushButton#PrimaryButton {{
    background: {PRIMARY}; color: #ffffff; border: none;
    border-radius: {RADIUS_BUTTON}px; padding: 4px 12px;
}}
QPushButton#SecondaryButton {{
    background: transparent; color: {TEXT_PRIMARY}; border: none;
    border-radius: {RADIUS_BUTTON}px; padding: 4px 12px;
}}
QPushButton#SecondaryButton:hover {{ background: {BG_SEARCH}; }}
QLineEdit#SearchBox {{
    background: {BG_SEARCH}; border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px; padding: 4px 8px; color: {TEXT_PRIMARY};
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
"""
