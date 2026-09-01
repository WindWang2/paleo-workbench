"""Workstation V3 design-system regression suite.

Pins the redesigned token sheet:
* API stability — palette_for / build_qss / PAGE_NAMES / PAGE_DESCRIPTIONS /
  ICON_FILES stay index-aligned with ui/navigation.py (11 pages) and every
  icon file referenced by ICON_FILES exists on disk,
* one token vocabulary across light / dark / high_contrast,
* a white light-theme activity rail plus curated dark/high-contrast rails,
* WCAG floors for every primary text/badge pair — each floor is set at or
  above the old slate sheet's measured ratio, so contrast strictly improves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench import tokens
from paleo_workbench.ui import tokens as ui_tokens

_ICONS_DIR = Path(tokens.__file__).parent / "ui" / "assets" / "icons"


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    def channel(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(int(h[0:2], 16)) + 0.7152 * channel(int(h[2:4], 16)) + 0.0722 * channel(int(h[4:6], 16))


def _ratio(fg: str, bg: str) -> float:
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# Public API stability
# ---------------------------------------------------------------------------

def test_workstation_light_identity_values():
    assert tokens.PRIMARY == "#0b5563"
    assert tokens.ACCENT == "#a65313"
    assert tokens.BG_BODY == "#f4f6f8"
    assert tokens.BG_SIDEBAR == "#ffffff"
    assert tokens.BG_RAIL == "#ffffff"
    assert tokens.RADIUS_BUTTON == 4
    assert tokens.RADIUS_CARD == 4
    assert tokens.PAGE_MARGIN == 16
    assert tokens.FONT_SIZE_TITLE == "14px"
    assert tokens.FONT_WEIGHT_TITLE == "700"


def test_navigation_arrays_stay_index_aligned():
    assert len(tokens.PAGE_NAMES) == 11
    assert len(tokens.PAGE_DESCRIPTIONS) == len(tokens.PAGE_NAMES)
    assert len(tokens.ICON_FILES) == len(tokens.PAGE_NAMES)
    # index 10 is the joint-analysis page absorbed into GEOMODEL (PRD #85/#91)
    assert tokens.PAGE_NAMES[10] == "井震联合"
    for name in tokens.ICON_FILES:
        assert (_ICONS_DIR / name).exists(), f"missing nav icon {name}"
    # ui/tokens.py remains a pure re-export shim
    assert ui_tokens.PAGE_NAMES is tokens.PAGE_NAMES
    assert ui_tokens.build_qss is tokens.build_qss
    assert ui_tokens.palette_for is tokens.palette_for


def test_palette_functions_keep_their_signatures():
    for theme in ("light", "dark", "high_contrast"):
        qss = tokens.build_qss(density="comfortable", theme=theme)
        assert isinstance(qss, str) and len(qss) > 5_000
    assert set(tokens.palette_for("dark")) == set(tokens.palette_for("light"))
    assert tokens.palette_for("nonsense") == tokens.palette_for("light")
    assert tokens.QSS_TEMPLATE == tokens.build_qss()
    assert tokens.build_modern_qss() == tokens.build_qss()


def test_three_themes_share_one_token_vocabulary():
    light = tokens.palette_for("light")
    dark = tokens.palette_for("dark")
    hc = tokens.palette_for("high_contrast")
    assert set(light) == set(dark) == set(hc)
    for key in ("BG_BODY", "PRIMARY", "ACCENT", "TEXT_PRIMARY", "TEXT_SECONDARY",
                "BORDER", "BG_RAIL", "ON_PRIMARY", "BG_RAIL_ACTIVE", "TOOLTIP_BG"):
        assert key in light and key in dark and key in hc
    assert all(isinstance(v, (str, int, float)) for v in light.values())


def test_dark_is_dark_and_high_contrast_is_pure():
    dark = tokens.palette_for("dark")
    bg = dark["BG_BODY"].lstrip("#")
    assert sum(int(bg[i:i + 2], 16) for i in (0, 2, 4)) < 200
    hc = tokens.palette_for("high_contrast")
    assert hc["BG_BODY"] == "#ffffff"
    assert hc["PRIMARY"] == "#000000"
    assert hc["TEXT_PRIMARY"] == "#000000"
    assert hc["BORDER"] == "#000000"


def test_icon_rail_adapts_to_theme():
    light = tokens.palette_for("light")
    assert light["BG_RAIL"] == "#ffffff"
    assert light["BG_RAIL_GRADIENT"] == "#ffffff"
    for theme in ("dark", "high_contrast"):
        palette = tokens.palette_for(theme)
        rail = palette["BG_RAIL"]
        rgb = [int(rail.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        assert sum(rgb) < 150, f"{theme} rail must stay dark, got {rail}"
        assert palette["BG_RAIL_GRADIENT"].startswith("qlineargradient"), (
            f"{theme} rail gradient must paint a surface"
        )


def test_rail_hover_pair_is_readable_in_every_theme():
    """Round-1 review P1: HC hover paired BG_RAIL_HOVER #1f1f1f with
    TEXT_ON_RAIL_ACTIVE #000000 → 1.27:1. Pin the palette pair AND verify
    both QSS hover rules (navItem + dockRailItem) actually pair those two
    tokens, so the sheet cannot silently re-pair them."""
    import re

    for theme in ("light", "dark", "high_contrast"):
        p = tokens.palette_for(theme)
        ratio = _ratio(p["TEXT_ON_RAIL_ACTIVE"], p["BG_RAIL_HOVER"])
        assert ratio >= 4.5, f"{theme} rail hover text: {ratio:.2f} < 4.5"
        # hover surface must read as a distinct step on the rail — strong in
        # HC (review P1 flagged #1f1f1f-on-#000000 = 1.15:1), subtle-but-present
        # in light/dark like the old sheet
        surface = _ratio(p["BG_RAIL_HOVER"], p["BG_RAIL"])
        floor = 3.0 if theme == "high_contrast" else 1.1
        assert surface >= floor, f"{theme} hover surface vs rail: {surface:.2f} < {floor}"
        qss = tokens.build_qss(theme=theme)
        for selector in (r'QToolButton\[navItem="true"\]:hover',
                         r'QToolButton\[dockRailItem="true"\]:hover'):
            m = re.search(selector + r" \{([^}]*)\}", qss)
            assert m, f"{theme} missing rule {selector}"
            block = m.group(1)
            assert p["BG_RAIL_HOVER"] in block, f"{selector} lost hover surface"
            assert p["TEXT_ON_RAIL_ACTIVE"] in block, f"{selector} lost hover text"


# ---------------------------------------------------------------------------
# WCAG contrast floors (at or above the old slate sheet's ratios)
# ---------------------------------------------------------------------------

def test_light_theme_text_contrast_floors():
    p = tokens.palette_for("light")
    pairs = [
        ("TEXT_PRIMARY", "BG_BODY", 14.5),
        ("TEXT_PRIMARY", "BG_SIDEBAR", 15.0),
        ("TEXT_SECONDARY", "BG_SIDEBAR", 6.3),
        ("PRIMARY", "BG_BODY", 7.7),        # PRIMARY used as text (tabs/menus)
        ("ON_PRIMARY", "PRIMARY", 7.5),     # primary buttons / active chips
        ("TEXT_ON_RAIL", "BG_RAIL", 6.3),
        ("TEXT_ON_RAIL_ACTIVE", "BG_RAIL_ACTIVE", 7.0),
        ("TEXT_PRIMARY", "BG_SELECTION", 12.9),
        ("ACCENT", "BG_SIDEBAR", 5.0),      # focus ring (non-text needs ≥ 3)
    ]
    for fg_key, bg_key, floor in pairs:
        ratio = _ratio(p[fg_key], p[bg_key])
        assert ratio >= floor, f"{fg_key} on {bg_key}: {ratio:.2f} < {floor}"


def test_dark_theme_text_contrast_floors():
    p = tokens.palette_for("dark")
    pairs = [
        ("TEXT_PRIMARY", "BG_BODY", 15.0),
        ("TEXT_SECONDARY", "BG_SIDEBAR", 8.0),
        ("PRIMARY", "BG_BODY", 9.5),        # bright petrol text on charcoal
        ("ON_PRIMARY", "PRIMARY", 9.0),
        ("TEXT_ON_RAIL", "BG_RAIL", 10.0),
        ("TEXT_ON_RAIL_ACTIVE", "BG_RAIL_ACTIVE", 10.0),
        ("TEXT_PRIMARY", "BG_SELECTION", 9.4),
    ]
    for fg_key, bg_key, floor in pairs:
        ratio = _ratio(p[fg_key], p[bg_key])
        assert ratio >= floor, f"{fg_key} on {bg_key}: {ratio:.2f} < {floor}"


def test_badge_chips_keep_white_text_readable_in_both_themes():
    for theme, floor in (("light", 7.0), ("dark", 4.9)):
        p = tokens.palette_for(theme)
        for key in ("BADGE_WARNING", "BADGE_SUCCESS", "BADGE_PRIMARY"):
            ratio = _ratio("#ffffff", p[key])
            assert ratio >= floor, f"{theme} {key}: {ratio:.2f} < {floor}"


def test_dark_badge_chips_stand_off_the_panel():
    p = tokens.palette_for("dark")
    for key in ("BADGE_WARNING", "BADGE_SUCCESS", "BADGE_PRIMARY"):
        ratio = _ratio(p[key], p["BG_SIDEBAR"])
        assert ratio >= 3.0, f"{key} chip vs panel: {ratio:.2f} < 3.0"


def test_workflow_stage_colors_carry_white_text():
    for color in tokens.STEP_COLORS:
        ratio = _ratio("#ffffff", color)
        assert ratio >= 4.5, f"stage color {color}: {ratio:.2f} < 4.5"


# ---------------------------------------------------------------------------
# Stylesheet rendering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("density,padding,min_height", [
    ("comfortable", "padding: 6px 12px", "min-height: 30px"),
    ("compact", "padding: 3px 8px", "min-height: 24px"),
])
@pytest.mark.parametrize("theme", ["light", "dark", "high_contrast"])
def test_build_qss_density_and_theme_matrix(theme, density, padding, min_height):
    qss = tokens.build_qss(density=density, theme=theme)
    assert padding in qss
    assert min_height in qss
    for selector in ("QPushButton", "QMenu", "QTableView", "QHeaderView::section"):
        assert selector in qss
    # shell hooks the app-shell mission consumes must survive the redesign
    for hook in ("QWidget#AppShell", "QFrame#IconRail", '[navItem="true"]',
                 '[active="true"]', '[stageItem="true"]',
                 "QPushButton#PrimaryButton", "QPushButton#SecondaryButton",
                 "QLineEdit#SearchBox"):
        assert hook in qss, f"{theme}/{density} lost {hook}"


@pytest.mark.parametrize("theme", ["light", "dark", "high_contrast"])
def test_qss_uses_on_primary_for_primary_surfaces(theme):
    palette = tokens.palette_for(theme)
    qss = tokens.build_qss(theme=theme)
    assert f"color: {palette['ON_PRIMARY']}" in qss


@pytest.mark.parametrize("theme", ["light", "dark", "high_contrast"])
def test_legacy_slate_palette_is_gone(theme):
    qss = tokens.build_qss(theme=theme)
    for legacy in ("#334155", "#0ea5e9", "#f1f5f9", "#e2e8f0", "#1e293b", "#475569"):
        assert legacy not in qss, f"{theme} still carries legacy slate {legacy}"
