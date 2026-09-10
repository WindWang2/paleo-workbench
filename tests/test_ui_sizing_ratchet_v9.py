"""V9 structural sizing ratchet — keep rigid dimensions from creeping back.

The V9 audit classified 454 sizing call sites; 62 were FORBIDDEN_LARGE (rigid
constraints on docks/trees/panels/pages/central content) and the worst of them
locked dock resizing (see docs/development/adaptive-workstation-ui-v9/).
This ratchet fails when NEW rigid sizing appears, or when an allowlisted
count grows. It is an upper bound: shrinking a count passes silently —
please update the snapshot when you remove allowlisted sites so the next
tightening is still visible.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Scope: everything that builds production UI chrome. Prototypes are dead
#: reference code; tests and docs are out of scope by construction.
SCOPE_DIRS = (
    REPO / "paleo_workbench" / "ui",
    REPO / "paleo_workbench" / "viz" / "hosts",
)
SCOPE_FILES = (REPO / "paleo_workbench" / "app.py",)
EXCLUDED_PARTS = {"prototypes"}

# --- rules --------------------------------------------------------------

#: fixed width/height/size with a numeric literal >= 100 px on UI code.
RULE_FIXED_LARGE = re.compile(r"\.setFixed(?:Width|Height|Size)\(\s*(\d{3,})")

#: minimum width / minimum size with the width literal >= 400 px.
RULE_MIN_LARGE = re.compile(r"\.setMinimumWidth\(\s*(\d{3,})\s*\)")
RULE_MIN_SIZE_LARGE = re.compile(r"\.setMinimumSize\(\s*(\d{3,})\s*,")

#: QDockWidget construction outside the workstation shell.
RULE_QDOCK_CONSTRUCTION = re.compile(r"\bQDockWidget\s*\(")

#: programmatic dock resizing outside the dock framework.
RULE_RESIZE_DOCKS = re.compile(r"\.resizeDocks\(")

#: non-collapsible splitters (page side panels must stay collapsible-or-
#: scrollable; new ones need a documented entry).
RULE_NON_COLLAPSIBLE = re.compile(r"\.setChildrenCollapsible\(False\)")

#: literal maximum width caps >= 300 px on large containers (min+max pairs
#: are fixed width by other means; toolbar controls below 300 stay legal).
RULE_MAX_LARGE = re.compile(r"\.setMaximumWidth\(\s*(\d{3,})\s*\)")
MAX_LARGE_SNAPSHOT: dict[str, int] = {
    "paleo_workbench/ui/workstation/app_bar.py": 1,  # command input 580
}

#: theme-drift pattern: setStyleSheet whose statement references compile-time
#: token color constants (light-theme snapshots). Migrate to style.bind.
RULE_DRIFTED_STYLESHEET = re.compile(r"setStyleSheet\(")
_DRIFT_COLOR_TOKEN = re.compile(
    r"tokens\.\w*(BG_|TEXT_|BORDER|ACCENT|SUCCESS|WARNING|DANGER|DISABLED|SELECTION)\w*"
)

#: snapshot of remaining raw setStyleSheet+token-color sites (2026-09-10,
#: after the V9 migration of the 9 worst offender files). Ratchet: no growth.
DRIFTED_STYLESHEET_SNAPSHOT: dict[str, int] = {
    "paleo_workbench/ui/map_status_bar.py": 3,
    "paleo_workbench/ui/pages/activity_card.py": 3,
    "paleo_workbench/ui/pages/action_header.py": 2,
    "paleo_workbench/ui/pages/map_canvas_panel.py": 2,
    "paleo_workbench/ui/pages/map_chrome_panel.py": 2,
    "paleo_workbench/ui/pages/preview_settings_panel.py": 2,
    "paleo_workbench/ui/pages/relink_dialog.py": 2,
    "paleo_workbench/ui/pages/start_guide_card.py": 2,
    "paleo_workbench/ui/pages/well_seismic_joint_page.py": 2,
    "paleo_workbench/ui/pages/well_table_panel.py": 2,
    "paleo_workbench/viz/hosts/well_log_host.py": 1,
    "paleo_workbench/ui/pages/catalog_health_dialog.py": 1,
    "paleo_workbench/ui/pages/composite_visualization_panel.py": 1,
    "paleo_workbench/ui/pages/data_asset_table.py": 1,
    "paleo_workbench/ui/pages/data_toolbar.py": 1,
    "paleo_workbench/ui/pages/filter_chips_bar.py": 1,
    "paleo_workbench/ui/pages/governance_dialog.py": 1,
    "paleo_workbench/ui/pages/home_page.py": 1,
    "paleo_workbench/ui/pages/map_edit_view.py": 1,
    "paleo_workbench/ui/pages/map_reference_panel.py": 1,
    "paleo_workbench/ui/pages/module_relationship.py": 1,
    "paleo_workbench/ui/pages/pdf_preview_widget.py": 1,
    "paleo_workbench/ui/pages/resource_table.py": 1,
    "paleo_workbench/ui/pages/seismic_view_panel.py": 1,
    "paleo_workbench/ui/pages/well_log_canvas_panel.py": 1,
    "paleo_workbench/ui/pages/workflow_contract_panel.py": 1,
}

#: snapshot of sanctioned exceptions. Keys are repo-relative posix paths.
#: Counts may only shrink — never raise them without an ADR note in
#: docs/development/adaptive-workstation-ui-v9/.
ALLOWLIST: dict[str, dict[str, int]] = {
    # bounded dialog surfaces (legitimately bounded windows)
    "paleo_workbench/ui/workstation/mapping_stage_bar.py": {
        "fixed_large": 1,  # horizon combo (toolbar control, 160px)
    },
    "paleo_workbench/ui/data_lifecycle_controller.py": {"min_large": 1},  # _DeliveryDialog
    "paleo_workbench/app.py": {"min_size_large": 1},  # sanctioned window floor 960x600
    "paleo_workbench/ui/preview_settings_dialog.py": {"min_large": 1},
    "paleo_workbench/ui/pages/create_factor_map_dialog.py": {"min_large": 1},
    "paleo_workbench/ui/pages/governance_dialog.py": {"min_large": 1},
    "paleo_workbench/ui/pages/new_project_wizard.py": {"min_large": 1},
    "paleo_workbench/ui/pages/tag_widgets.py": {"min_size_large": 1},
    "paleo_workbench/ui/workstation/tool_page_dialog.py": {"min_size_large": 1},
    "paleo_workbench/ui/pages/well_log_track_settings.py": {"min_large": 1},
    # home relationship diagram: painting canvas widths, inside its own
    # scroll containers and the V9 HubScrollArea (scrolls, never blocks docks)
    "paleo_workbench/ui/pages/home_page.py": {"min_large": 2},
    "paleo_workbench/ui/pages/module_relationship.py": {"min_large": 2},
    # historical non-collapsible splitters inside scroll-wrapped pages
    "paleo_workbench/ui/pages/data_workspace.py": {"non_collapsible": 2},
    "paleo_workbench/ui/pages/geological_modeling_3d_page.py": {"non_collapsible": 1},
    "paleo_workbench/ui/pages/home_page.py#collapsible": {"non_collapsible": 1},
    "paleo_workbench/ui/pages/preparation_page.py": {"non_collapsible": 1},
    "paleo_workbench/ui/pages/project_well_map_page.py": {"non_collapsible": 1},
    "paleo_workbench/ui/pages/stratigraphy_correlation_page.py": {"non_collapsible": 1},
    "paleo_workbench/ui/pages/summary_table_preview_widget.py": {"non_collapsible": 1},
}

#: single construction site for QDockWidget (dock identity is declarative).
QDOCK_ALLOWED_FILES = {"paleo_workbench/ui/workstation/shell.py"}
#: single authority for programmatic dock resizing. visual_qa_* drivers
#: simulate user interactions (including programmatic sizing to set up the
#: "user arranged this dock" precondition) — they never run in production.
RESIZE_DOCKS_ALLOWED_FILES = {
    "paleo_workbench/ui/dock_framework.py",
    "paleo_workbench/ui/visual_qa_v9.py",
}


def _iter_py_files():
    for directory in SCOPE_DIRS:
        for path in directory.rglob("*.py"):
            if EXCLUDED_PARTS & set(path.parts):
                continue
            yield path
    yield from SCOPE_FILES


def _rule_hits(source: str, rule: re.Pattern, threshold: int) -> int:
    hits = 0
    for match in rule.finditer(source):
        value = int(match.group(1)) if match.groups() else None
        if value is None or value >= threshold:
            hits += 1
    return hits


def test_no_new_rigid_fixed_sizes():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        allowed = ALLOWLIST.get(rel, {}).get("fixed_large", 0)
        hits = _rule_hits(source, RULE_FIXED_LARGE, 100)
        if hits > allowed:
            offenders.append(f"{rel}: {hits} fixed>=100px call(s) (allowed {allowed})")
    assert not offenders, (
        "new fixed width/height/size >= 100px on UI chrome "
        "(use QSizePolicy / minimum floors / scroll areas):\n  "
        + "\n  ".join(offenders)
    )


def test_no_new_large_minimum_widths():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        hits = _rule_hits(source, RULE_MIN_LARGE, 400) + _rule_hits(
            source, RULE_MIN_SIZE_LARGE, 400
        )
        allowed = ALLOWLIST.get(rel, {}).get("min_large", 0) + ALLOWLIST.get(
            rel, {}
        ).get("min_size_large", 0)
        if hits > allowed:
            offenders.append(f"{rel}: {hits} min>=400px call(s) (allowed {allowed})")
    assert not offenders, (
        "new minimum width >= 400px on UI chrome (large containers must "
        "shrink-or-scroll):\n  " + "\n  ".join(offenders)
    )


def test_qdockwidget_construction_stays_in_shell():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        if rel in QDOCK_ALLOWED_FILES:
            continue
        if RULE_QDOCK_CONSTRUCTION.search(source):
            offenders.append(rel)
    assert not offenders, (
        "QDockWidget must only be constructed in the workstation shell "
        "(dock identity lives in ui/dock_framework.py):\n  " + "\n  ".join(offenders)
    )


def test_resize_docks_authority_is_the_framework():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        if rel in RESIZE_DOCKS_ALLOWED_FILES:
            continue
        if RULE_RESIZE_DOCKS.search(source):
            offenders.append(rel)
    assert not offenders, (
        "QMainWindow.resizeDocks must only be called from ui/dock_framework.py "
        "(first-run/reset or grow-only affordances):\n  " + "\n  ".join(offenders)
    )


def test_no_new_non_collapsible_page_splitters():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        allowed = ALLOWLIST.get(rel, {}).get("non_collapsible", 0) + ALLOWLIST.get(
            rel + "#collapsible", {}
        ).get("non_collapsible", 0)
        hits = len(RULE_NON_COLLAPSIBLE.findall(source))
        if hits > allowed:
            offenders.append(
                f"{rel}: {hits} setChildrenCollapsible(False) (allowed {allowed})"
            )
    assert not offenders, (
        "page splitters must stay collapsible (narrow workspaces rely on "
        "collapse + scroll degradation):\n  " + "\n  ".join(offenders)
    )


def test_no_new_large_maximum_widths():
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        hits = _rule_hits(source, RULE_MAX_LARGE, 300)
        allowed = MAX_LARGE_SNAPSHOT.get(rel, 0)
        if hits > allowed:
            offenders.append(f"{rel}: {hits} max<=literal site(s) (allowed {allowed})")
    assert not offenders, (
        "new literal setMaximumWidth >= 300 on UI chrome — a min+max pair is "
        "a fixed width by other means: " + "; ".join(offenders)
    )


def test_no_new_theme_drifted_stylesheets():
    """setStyleSheet + 编译期 token 颜色常量 = 主题切换漂移（暗色下保持浅色）。

    新代码必须走 ``style.bind(widget, render)``（render 内重取
    ``style.palette()``）。存量站点被快照锁定，只减不增。
    """
    offenders = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        hits = 0
        for match in RULE_DRIFTED_STYLESHEET.finditer(source):
            window = source[match.start() : match.start() + 500]
            if _DRIFT_COLOR_TOKEN.search(window):
                hits += 1
        allowed = DRIFTED_STYLESHEET_SNAPSHOT.get(rel, 0)
        if hits > allowed:
            offenders.append(f"{rel}: {hits} drifted site(s) (allowed {allowed})")
    assert not offenders, (
        "new setStyleSheet with compile-time token colors — use "
        "style.bind() with a re-fetching palette() renderer:\n  "
        + "\n  ".join(offenders)
    )
