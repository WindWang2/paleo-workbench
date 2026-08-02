"""Main window chrome for Well Log Workstation — L layout (#211 / #216).

Empty panes are intentional in ticket 01; data arrives in #217+.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenuBar,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from well_log_workstation.qt_platform import effective_qt_platform_hint


class WellLogWorkstationWindow(QMainWindow):
    """Log-first shell: left tree · center document tabs · right inspector."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WellLogWorkstationWindow")
        self.setWindowTitle("Well Log Workstation")
        self.resize(1280, 800)

        self._build_menus()
        self._build_body()
        self._build_status()

    def _build_menus(self) -> None:
        bar = QMenuBar(self)
        for name in ("文件", "图件", "图版", "导出", "帮助"):
            menu = bar.addMenu(name)
            menu.setObjectName(f"Menu_{name}")
            # Placeholders — wired in later tickets
            act = menu.addAction("…")
            act.setEnabled(False)
        self.setMenuBar(bar)

    def _build_body(self) -> None:
        root = QWidget()
        root.setObjectName("ShellRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("ShellSplitter")

        split.addWidget(self._build_left())
        split.addWidget(self._build_center())
        split.addWidget(self._build_right())
        split.setSizes([240, 760, 280])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)

        outer.addWidget(split, 1)

    def _build_left(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("LeftPane")
        layout = QVBoxLayout(pane)
        title = QLabel("工区")
        title.setObjectName("LeftPaneTitle")
        layout.addWidget(title)

        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setObjectName("WorkspaceTree")
        self.workspace_tree.setHeaderLabels(["名称"])
        # Empty skeleton until #217 fills from workspace.json
        root = QTreeWidgetItem(["（未打开工区）"])
        wells = QTreeWidgetItem(["井"])
        plots = QTreeWidgetItem(["图件"])
        root.addChild(wells)
        root.addChild(plots)
        self.workspace_tree.addTopLevelItem(root)
        self.workspace_tree.expandAll()
        layout.addWidget(self.workspace_tree, 1)
        return pane

    def _build_center(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("CenterPane")
        layout = QVBoxLayout(pane)

        self.document_tabs = QTabWidget()
        self.document_tabs.setObjectName("DocumentTabs")
        self.document_tabs.setTabsClosable(True)
        self.document_tabs.setDocumentMode(True)

        placeholder = QFrame()
        placeholder.setObjectName("CanvasPlaceholder")
        placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        ph = QVBoxLayout(placeholder)
        lab = QLabel(
            "画布区\n\n"
            "单井分析图 = 一口井 · 多图道（图版模板，#219）\n"
            "地层对比图-lite = 多井共享深度（#222）\n\n"
            "（#216：空壳可导航）"
        )
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setWordWrap(True)
        lab.setObjectName("CanvasPlaceholderLabel")
        ph.addWidget(lab)

        self.document_tabs.addTab(placeholder, "（无打开图件）")
        layout.addWidget(self.document_tabs, 1)
        return pane

    def _build_right(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("RightPane")
        layout = QVBoxLayout(pane)

        layout.addWidget(QLabel("属性 / 图版 / 层位"))
        layout.addWidget(QLabel("图版模板（库 · 应用见 #219）"))
        self.template_list = QListWidget()
        self.template_list.setObjectName("TemplateList")
        self.template_list.addItem("（模板库未加载）")
        layout.addWidget(self.template_list)

        layout.addWidget(QLabel("层位"))
        self.tops_list = QListWidget()
        self.tops_list.setObjectName("TopsList")
        self.tops_list.addItem("（无层位）")
        layout.addWidget(self.tops_list)
        layout.addStretch(1)
        return pane

    def _build_status(self) -> None:
        status = QStatusBar(self)
        status.setObjectName("MainStatusBar")
        hint = effective_qt_platform_hint()
        status.showMessage(f"Well Log Workstation · Qt platform: {hint}")
        self.setStatusBar(status)
