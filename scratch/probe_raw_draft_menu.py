"""Verify the native-tree 「复制为草稿…」 patch.

Runs against the real QgisLayerTreePanel. Simulates what the C++ menu
provider produces for each branch, then calls the same slot QGIS calls
(contextMenuAboutToShow -> _on_native_menu_about_to_show) and inspects the
resulting QMenu.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "raw_draft_menu_test.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from paleo_workbench.ui.qgis_stack.layer_tree_panel import (  # noqa: E402
    QgisLayerTreePanel,
)

RAW_DRAFT = "复制为草稿…"


class Verdict:
    def __init__(self, enabled: bool, reason: str = "") -> None:
        self.enabled = enabled
        self.disabled_reason = reason


class Facts:
    def __init__(self, *, raw_protected: bool, toggle_ok: bool = True) -> None:
        self.raw_protected = raw_protected
        self.toggle_editing = Verdict(
            toggle_ok, "" if toggle_ok else "图层角色不可编辑（RAW/冻结/锁定）")
        self.repair_geometry = Verdict(False, "非面图层")


def build_menu(menu, texts: tuple[str, ...]) -> None:
    """Mimic one C++ provider branch (separators as '')."""
    for text in texts:
        if not text:
            menu.addSeparator()
        else:
            menu.addAction(text)


ELSE_BRANCH = (
    "Zoom to Layer(s)", "Show Feature Count", "",
    "Rename Layer", "", "图层属性…",
)
EDITABLE_BRANCH = (
    "Zoom to Layer(s)", "Show Feature Count", "",
    "打开属性表", "开始/停止编辑", "",
    "图层属性…", "符号系统…", "标注…", "",
    "Rename Layer", "复制图层", "删除图层", "",
    "修复无效几何…", "导出图层…",
)

DOC = "res_layer_seismic_mock"


def run_case(label: str, branch: tuple[str, ...], facts: Facts) -> list[str]:
    panel = QgisLayerTreePanel(menu_probe=lambda _doc: facts)
    panel._selected_doc_id = DOC
    captured: list[str] = []
    panel.duplicate_layer_requested.connect(lambda lid: captured.append(lid))

    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    build_menu(menu, branch)
    panel._on_native_menu_about_to_show(menu)      # exactly what QGIS calls
    texts = [a.text() if not a.isSeparator() else "---" for a in menu.actions()]

    out(f"=== {label} ===")
    out(f"  before: {[t for t in branch if t]!r}")
    out(f"  after : {texts}")
    out(f"  has 「{RAW_DRAFT}」 : {RAW_DRAFT in texts}")
    if RAW_DRAFT in texts:
        idx = texts.index(RAW_DRAFT)
        out(f"  position = {idx} (between {texts[idx-1]!r} and {texts[idx+1]!r})")
        act = next(a for a in menu.actions() if a.text() == RAW_DRAFT)
        out(f"  enabled = {act.isEnabled()}  tooltip = {act.toolTip()!r}")
        act.trigger()
        menu.close()
        out(f"  triggered -> duplicate_layer_requested {captured!r}")
    # gating sanity on the editable branch
    for a in menu.actions():
        if a.text() == "开始/停止编辑":
            out(f"  「开始/停止编辑」 enabled={a.isEnabled()} tooltip={a.toolTip()!r}")
    menu.deleteLater()
    return texts


run_case("A. RAW-protected layer, ELSE branch (the reported case)",
         ELSE_BRANCH, Facts(raw_protected=True))
out()
run_case("B. editable layer, EDITABLE branch", EDITABLE_BRANCH,
         Facts(raw_protected=False))
out()
run_case("C. plain base layer (raw_protected False, else branch)",
         ELSE_BRANCH, Facts(raw_protected=False))

out()
out("DONE")
_fh.close()
print("done")
