"""Inventory the real entry points of the running shell.

Answers "why do I see no entry point": whether the start guide card is
visible for an empty project, which panels are shown/hidden by default, and
what the top-level clickable texts actually are.

Writes .workbuddy/ui_map.txt incrementally so a late crash still leaves data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "ui_map.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


# 1. project loader first (must precede any PySide6 import) ---------------
import paleo_workbench  # noqa: E402,F401

out("step1 paleo_workbench imported")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDockWidget,
    QPushButton,
    QToolButton,
)

app = QApplication.instance() or QApplication(sys.argv)
out("step2 QApplication ready")

from paleo_workbench.app import PaleoWorkbenchWindow  # noqa: E402

win = PaleoWorkbenchWindow()
out(f"step3 window built  size={win.size().width()}x{win.size().height()}")

shell = win.app_shell
ws = shell.workstation

# --- panel visibility --------------------------------------------------
out()
out("=== panel visibility (isHidden == explicitly hidden) ===")
for name, widget in (
    ("app_shell", shell),
    ("workstation", ws),
    ("app_bar", ws.app_bar),
    ("activity_rail", ws.activity_rail),
    ("explorer", ws.explorer),
    ("composite(编图文档)", ws.composite),
    ("stage_bar(阶段条)", getattr(ws, "stage_bar", None)),
    ("page_stack", shell.page_stack),
    ("home_page(项目概述)", shell.home_page),
    ("start_guide_card", getattr(shell.home_page, "start_guide_card", None)),
    ("inspector dock", getattr(ws, "inspector_dock", None)),
    ("agent dock", getattr(ws, "agent_dock", None)),
):
    if widget is None:
        out(f"  {name:24s} <absent>")
        continue
    out(f"  {name:24s} hidden={widget.isHidden()!s:5s} visible={widget.isVisible()}")

# --- dock widgets ------------------------------------------------------
out()
out("=== QDockWidget registry ===")
for dock in win.findChildren(QDockWidget):
    out(f"  title={dock.windowTitle()!r:24s} hidden={dock.isHidden()}")

# --- activity rail modes ----------------------------------------------
out()
out("=== activity rail (left edge) buttons ===")
for key, btn in getattr(ws.activity_rail, "buttons", {}).items():
    out(f"  {key:12s} text={btn.text()!r:10s} tooltip={btn.toolTip()!r}")

# --- top bar clickable texts ------------------------------------------
out()
out("=== app bar (top) ===")
bar = ws.app_bar
out(f"  project_button text = {bar.project_button.text()!r}")
out("  project menu items:")
for act in bar.project_button.menu().actions():
    out(f"    - {act.text()!r}  (separator={act.isSeparator()})")
out(f"  workspace_combo items = {[bar.workspace_combo.itemText(i) for i in range(bar.workspace_combo.count())]}")
out(f"  view_button text = {bar.view_button.text()!r}")
out(f"  task_button text = {bar.task_button.text()!r}")
out(f"  agent_button text = {bar.agent_button.text()!r}")
out(f"  command_input placeholder = {bar.command_input.placeholderText()!r}")

# --- start guide card buttons -----------------------------------------
out()
out("=== 项目概述 start guide card ===")
guide = getattr(shell.home_page, "start_guide_card", None)
if guide is not None:
    out(f"  title    = {guide.title_label.text()!r}")
    out(f"  subtitle = {guide.subtitle_label.text()!r}")
    for name in ("new_project_button", "open_project_button", "open_sample_button"):
        b = getattr(guide, name, None)
        if b is not None:
            out(f"  button {name:22s} text={b.text()!r} hidden={b.isHidden()} enabled={b.isEnabled()}")

# --- stage bar segments ------------------------------------------------
out()
out("=== stage bar segments (编图阶段) ===")
sbar = getattr(ws, "stage_bar", None)
if sbar is not None:
    for attr in dir(sbar):
        if attr.startswith("_"):
            continue
    from PySide6.QtWidgets import QLabel

    for lbl in sbar.findChildren(QLabel):
        t = lbl.text()
        if t:
            out(f"  label: {t!r}  hidden={lbl.isHidden()}")

# --- every visible button text, for a real inventory -------------------
out()
out("=== all QPushButton texts in the shell (hidden flag shown) ===")
seen = set()
for b in shell.findChildren(QPushButton):
    t = b.text()
    if not t or t in seen:
        continue
    seen.add(t)
    out(f"  hidden={b.isHidden()!s:5s} enabled={b.isEnabled()!s:5s} {t!r}")

out()
out("=== all QToolButton with text ===")
seen = set()
for b in shell.findChildren(QToolButton):
    t = b.text()
    if not t or t in seen:
        continue
    seen.add(t)
    out(f"  hidden={b.isHidden()!s:5s} {t!r}   tooltip={b.toolTip()!r}")

out()
out("=== QComboBox in the shell ===")
for c in shell.findChildren(QComboBox):
    items = [c.itemText(i) for i in range(min(c.count(), 8))]
    out(f"  obj={c.objectName()!r:32s} count={c.count()} items={items}")

out()
out("=== home page cards / side column ===")
hp = shell.home_page
for attr in ("onboarding_report_card", "_side_column"):
    w = getattr(hp, attr, None)
    if w is not None:
        out(f"  {attr:24s} hidden={w.isHidden()}")
out(f"  current page index = {shell.page_stack.currentIndex()}")
cur = shell.page_stack.currentWidget()
out(f"  current widget = {type(cur).__name__}")

out()
out("DONE")
_fh.close()
print("probe done ->", OUT)
