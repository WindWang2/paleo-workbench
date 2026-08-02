"""Main window chrome for Well Log Workstation — L layout (#211 / #216 / #217)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from well_log_workstation.las_import import LasImportError, import_las_into_workspace
from well_log_workstation.qt_platform import effective_qt_platform_hint
from well_log_workstation.session_store import HostSessionStore
from well_log_workstation.workspace import (
    Workspace,
    WorkspaceError,
    create_workspace,
    open_workspace,
)


class WellLogWorkstationWindow(QMainWindow):
    """Log-first shell: left tree · center document tabs · right inspector."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WellLogWorkstationWindow")
        self.setWindowTitle("Well Log Workstation")
        self.resize(1280, 800)

        self._workspace: Workspace | None = None
        self.session = HostSessionStore()

        self._build_menus()
        self._build_body()
        self._build_status()
        self._refresh_tree()

    @property
    def workspace(self) -> Workspace | None:
        return self._workspace

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("文件")
        file_menu.setObjectName("Menu_文件")
        act_new = file_menu.addAction("新建工区…")
        act_new.setObjectName("Action_NewWorkspace")
        act_new.triggered.connect(self._on_new_workspace)
        act_open = file_menu.addAction("打开工区…")
        act_open.setObjectName("Action_OpenWorkspace")
        act_open.triggered.connect(self._on_open_workspace)
        file_menu.addSeparator()
        self._act_import_las = file_menu.addAction("导入 LAS…")
        self._act_import_las.setObjectName("Action_ImportLas")
        self._act_import_las.triggered.connect(self._on_import_las)
        self._act_import_las.setEnabled(False)
        file_menu.addSeparator()
        act_quit = file_menu.addAction("退出")
        act_quit.triggered.connect(self.close)

        for name in ("图件", "图版", "导出", "帮助"):
            menu = bar.addMenu(name)
            menu.setObjectName(f"Menu_{name}")
            act = menu.addAction("…")
            act.setEnabled(False)

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
        self.left_title = QLabel("工区")
        self.left_title.setObjectName("LeftPaneTitle")
        layout.addWidget(self.left_title)

        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setObjectName("WorkspaceTree")
        self.workspace_tree.setHeaderLabels(["名称"])
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
            "单井分析图 = 一口井 · 多图道（#219）\n"
            "地层对比图-lite（#222）\n\n"
            "先用「文件 → 打开/新建工区」加载目录工区。"
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
        self.setStatusBar(status)
        self._update_status()

    def _update_status(self) -> None:
        hint = effective_qt_platform_hint()
        if self._workspace is None:
            msg = f"Well Log Workstation · 未打开工区 · Qt: {hint}"
        else:
            msg = (
                f"工区: {self._workspace.name} · "
                f"{self._workspace.root} · "
                f"井 {len(self._workspace.wells)} · "
                f"图件 {len(self._workspace.plots)} · "
                f"Qt: {hint}"
            )
        self.statusBar().showMessage(msg)

    def set_workspace(self, ws: Workspace | None) -> None:
        """Programmatic API for tests and future host wiring."""
        self._workspace = ws
        if ws is None:
            self.session.clear()
        self._act_import_las.setEnabled(ws is not None)
        self._refresh_tree()
        self._update_status()
        if ws is not None:
            self.setWindowTitle(f"{ws.name} — Well Log Workstation")
        else:
            self.setWindowTitle("Well Log Workstation")

    def import_las_path(self, las_path: Path | str) -> str:
        """Import LAS into the open workspace; returns catalog well id.

        Raises LasImportError / WorkspaceError for the caller to surface.
        """
        if self._workspace is None:
            raise WorkspaceError("请先打开或新建工区")
        result = import_las_into_workspace(self._workspace, las_path)
        self.session.put(result.document)
        self._refresh_tree()
        self._update_status()
        return result.catalog_well_id

    def _refresh_tree(self) -> None:
        tree = self.workspace_tree
        tree.clear()
        if self._workspace is None:
            self.left_title.setText("工区")
            root = QTreeWidgetItem(["（未打开工区）"])
            root.addChild(QTreeWidgetItem(["井"]))
            root.addChild(QTreeWidgetItem(["图件"]))
            tree.addTopLevelItem(root)
            tree.expandAll()
            return

        ws = self._workspace
        self.left_title.setText(f"工区 · {ws.name}")
        root = QTreeWidgetItem([ws.name])
        root.setData(0, Qt.ItemDataRole.UserRole, {"kind": "workspace"})

        wells_node = QTreeWidgetItem(["井"])
        wells_node.setData(0, Qt.ItemDataRole.UserRole, {"kind": "wells_folder"})
        for well in ws.wells:
            item = QTreeWidgetItem([well.name])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"kind": "well", "id": well.id, "path": well.path},
            )
            item.setToolTip(0, well.path or well.id)
            wells_node.addChild(item)
        if not ws.wells:
            empty = QTreeWidgetItem(["（无井）"])
            empty.setDisabled(True)
            wells_node.addChild(empty)

        plots_node = QTreeWidgetItem(["图件"])
        plots_node.setData(0, Qt.ItemDataRole.UserRole, {"kind": "plots_folder"})
        for plot in ws.plots:
            label = plot.name
            if plot.type == "correlation":
                label = f"{plot.name} [对比]"
            elif plot.type == "single_well":
                label = f"{plot.name} [单井·多图道]"
            item = QTreeWidgetItem([label])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"kind": "plot", "id": plot.id, "type": plot.type},
            )
            plots_node.addChild(item)
        if not ws.plots:
            empty = QTreeWidgetItem(["（无图件）"])
            empty.setDisabled(True)
            plots_node.addChild(empty)

        root.addChild(wells_node)
        root.addChild(plots_node)
        tree.addTopLevelItem(root)
        tree.expandAll()

    def _on_new_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择空目录作为新工区")
        if not path:
            return
        try:
            # Prefer create in empty dir; if path is empty create works.
            # If user picks non-empty, create_workspace errors.
            target = Path(path)
            if not any(target.iterdir()) if target.is_dir() else True:
                ws = create_workspace(target)
            else:
                # Offer create under a child if non-empty? Keep strict.
                ws = create_workspace(target)
            self.set_workspace(ws)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "新建工区失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "新建工区失败", str(exc))

    def _on_open_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "打开工区目录")
        if not path:
            return
        try:
            ws = open_workspace(path)
            self.set_workspace(ws)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "打开工区失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "打开工区失败", str(exc))

    def _on_import_las(self) -> None:
        if self._workspace is None:
            QMessageBox.information(self, "导入 LAS", "请先打开或新建工区。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 LAS 文件",
            "",
            "LAS (*.las *.LAS);;All (*.*)",
        )
        if not path:
            return
        try:
            well_id = self.import_las_path(path)
            doc = self.session.get(well_id)
            n_curves = len(doc.curves) if doc else 0
            extra = ""
            if doc and doc.diagnostics:
                extra = "\n\n提示:\n- " + "\n- ".join(doc.diagnostics[:8])
            QMessageBox.information(
                self,
                "导入成功",
                f"已导入井「{doc.well_name if doc else well_id}」\n"
                f"曲线数: {n_curves}\n"
                f"路径: {doc.source_path if doc else ''}"
                f"{extra}",
            )
        except (LasImportError, WorkspaceError) as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))
