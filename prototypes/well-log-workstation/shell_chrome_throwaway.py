#!/usr/bin/env python3
"""THROW AWAY prototype — ResFormSTAR-class shell chrome (wayfinder #214).

Locks IA from #211 (L): left 工区/井/图件 · center document tabs + canvas · right inspector.
Does NOT implement real workspace persistence or engine presentation templates.
"""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenuBar,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# --- optional WellLogEngine view ---
_WELLLOG = None
try:
    from welllog import WellLogView
    from welllog._QtWidgets import welllog as _wl_qt

    _WELLLOG = (_wl_qt, WellLogView)
except Exception:
    _WELLLOG = None


class MockMultiTrackCanvas(QFrame):
    """Stand-in for WellLogView when bindings are missing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 500)
        self.setStyleSheet("background: #fafafa; border: 1px solid #ccc;")
        self._title = "Mock canvas (no welllog wheel)"

    def set_caption(self, text: str) -> None:
        self._title = text
        self.update()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # depth axis
        p.setPen(QPen(QColor("#333"), 1))
        p.drawLine(40, 30, 40, h - 20)
        p.drawText(8, 28, "MD")
        # three fake tracks
        margins = [50, 50 + (w - 70) // 3, 50 + 2 * (w - 70) // 3]
        tw = (w - 70) // 3 - 8
        for i, x0 in enumerate(margins):
            p.setPen(QPen(QColor("#999"), 1))
            p.drawRect(x0, 30, tw, h - 50)
            p.drawText(x0 + 4, 48, ["GR", "RT", "DEN"][i])
            p.setPen(QPen(QColor("#1a6fb5" if i == 0 else "#c45c26"), 2))
            path_y0, path_y1 = 60, h - 30
            for yi in range(path_y0, path_y1, 3):
                t = (yi - path_y0) / max(1, path_y1 - path_y0)
                x = x0 + 10 + (tw - 20) * (0.5 + 0.4 * math.sin(t * 12 + i))
                if yi == path_y0:
                    p.drawPoint(int(x), yi)
                else:
                    p.drawLine(int(prev_x), yi - 3, int(x), yi)  # type: ignore[name-defined]
                prev_x = x
        p.setPen(QColor("#666"))
        p.drawText(50, h - 6, self._title)
        p.end()


class ShellPrototype(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            "THROW AWAY · Well Log Workstation shell (L) · wayfinder #214"
        )
        self.resize(1280, 800)

        mb = QMenuBar(self)
        for name in ("文件", "图件", "图版", "导出", "帮助"):
            mb.addMenu(name)
        self.setMenuBar(mb)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(4, 4, 4, 4)

        banner = QLabel(
            "PROTOTYPE ONLY — 不连真实工区/不存盘。验证：左树 · 中标签+画布 · 右检视 是否够用。"
        )
        banner.setStyleSheet(
            "background: #fff3cd; color: #664d03; padding: 6px; border: 1px solid #ffecb5;"
        )
        outer.addWidget(banner)

        split = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT: workspace tree ---
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.addWidget(QLabel("工区 · demo-field"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称"])
        ws = QTreeWidgetItem(["工区 demo-field"])
        wells = QTreeWidgetItem(["井"])
        for w in ("Well-A", "Well-B", "Well-C"):
            wells.addChild(QTreeWidgetItem([w]))
        plots = QTreeWidgetItem(["图件"])
        plots.addChild(QTreeWidgetItem(["Well-A 单井分析图"]))
        plots.addChild(QTreeWidgetItem(["A–C 地层对比图"]))
        ws.addChild(wells)
        ws.addChild(plots)
        self.tree.addTopLevelItem(ws)
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self._on_tree)
        left_l.addWidget(self.tree)
        split.addWidget(left)

        # --- CENTER: tabs + canvas ---
        center = QWidget()
        c_l = QVBoxLayout(center)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.single_host = QWidget()
        sh = QVBoxLayout(self.single_host)
        self.canvas_label = QLabel("中栏 · 单井分析图 · Well-A")
        sh.addWidget(self.canvas_label)
        self.engine_or_mock = self._make_canvas()
        sh.addWidget(self.engine_or_mock, 1)
        self.tabs.addTab(self.single_host, "单井分析图 · Well-A")

        corr = QWidget()
        cr = QVBoxLayout(corr)
        cr.addWidget(QLabel("中栏 · 地层对比图-lite · Well-A / B / C（占位）"))
        mock2 = MockMultiTrackCanvas()
        mock2.set_caption("Correlation-lite mock · shared depth")
        cr.addWidget(mock2, 1)
        self.tabs.addTab(corr, "地层对比图 · A–C")
        self.tabs.currentChanged.connect(self._on_tab)
        c_l.addWidget(self.tabs)
        split.addWidget(center)

        # --- RIGHT: inspector ---
        right = QWidget()
        r_l = QVBoxLayout(right)
        r_l.addWidget(QLabel("属性 / 图版 / 层位"))
        r_l.addWidget(QLabel("图版模板（库 · 只应用）"))
        self.templates = QComboBox()
        self.templates.addItems(
            ["标准三轨 GR-RT-DEN", "储层评价五轨", "简化 GR-only"]
        )
        self.templates.currentTextChanged.connect(self._on_template)
        r_l.addWidget(self.templates)
        r_l.addWidget(QLabel("层位"))
        tops = QListWidget()
        for t in ("T1 顶", "T2 底", "煤层 A"):
            tops.addItem(QListWidgetItem(t))
        r_l.addWidget(tops)
        r_l.addWidget(QLabel("状态（原型可见）"))
        self.state = QTextEdit()
        self.state.setReadOnly(True)
        self.state.setMaximumHeight(160)
        r_l.addWidget(self.state)
        r_l.addStretch(1)
        split.addWidget(right)

        split.setSizes([220, 720, 280])
        outer.addWidget(split, 1)

        self._emit_state("ready")

    def _make_canvas(self) -> QWidget:
        if _WELLLOG is None:
            m = MockMultiTrackCanvas()
            m.set_caption("Mock multi-track · install welllog for real WellLogView")
            return m
        wl_qt, View = _WELLLOG
        try:
            wl_qt.configure_well_log_surface_format()
        except Exception:
            pass
        view = View()
        # light synthetic submit if numpy present
        try:
            import numpy as np

            n = 2000
            d = np.linspace(1000.0, 1400.0, n)
            v = (40 + 25 * np.sin(np.linspace(0, 8 * np.pi, n))).astype(float)
            d.setflags(write=False)
            v.setflags(write=False)
            view.submit_curve(
                d,
                v,
                "d0000000-0000-4000-8000-000000000001",
                "d0000000-0000-4000-8000-000000000002",
                "d0000000-0000-4000-8000-000000000003",
                "GR",
                "m",
                "API",
            )
        except Exception as exc:
            self._banner_note = str(exc)
        return view

    def _on_tree(self, cur: QTreeWidgetItem | None, _prev) -> None:
        if cur is None:
            return
        self._emit_state(f"tree_select={cur.text(0)}")

    def _on_tab(self, idx: int) -> None:
        self._emit_state(f"tab_index={idx} title={self.tabs.tabText(idx)}")

    def _on_template(self, name: str) -> None:
        self._emit_state(f"template_apply={name} (host JSON → Presentation stub)")

    def _emit_state(self, event: str) -> None:
        engine = "WellLogView" if _WELLLOG else "MockMultiTrackCanvas"
        self.state.setPlainText(
            f"event: {event}\n"
            f"shell: L (left/center/right)\n"
            f"canvas: {engine}\n"
            f"workspace: demo-field (in-memory only)\n"
            f"docs: S1 单井 + 对比-lite tabs\n"
            f"templates: library-only (H)\n"
        )


def main() -> int:
    app = QApplication(sys.argv)
    win = ShellPrototype()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
