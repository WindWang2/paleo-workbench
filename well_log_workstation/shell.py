"""Main window chrome for Well Log Workstation — L layout (#216–#219)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from well_log_workstation.las_import import LasImportError, import_las_into_workspace
from well_log_workstation.multi_track_canvas import MultiTrackCanvas
from well_log_workstation.plot_document import (
    PlotDocument,
    create_single_well_plot,
    load_plot_document,
    save_plot_document,
)
from well_log_workstation.qt_platform import effective_qt_platform_hint
from well_log_workstation.session_store import HostSessionStore
from well_log_workstation.template_model import (
    HostPresentation,
    PlotTemplate,
    apply_template,
    get_builtin_template,
    list_builtin_templates,
)
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
        self._selected_well_id: str | None = None
        self._active_plot_id: str | None = None
        self._presentation: HostPresentation | None = None
        self._templates: list[PlotTemplate] = list_builtin_templates()

        self._build_menus()
        self._build_body()
        self._build_status()
        self._populate_templates()
        self._refresh_tree()

    @property
    def workspace(self) -> Workspace | None:
        return self._workspace

    @property
    def active_presentation(self) -> HostPresentation | None:
        return self._presentation

    @property
    def active_plot_id(self) -> str | None:
        return self._active_plot_id

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

        plot_menu = bar.addMenu("图件")
        plot_menu.setObjectName("Menu_图件")
        self._act_new_single_plot = plot_menu.addAction("新建单井分析图…")
        self._act_new_single_plot.setObjectName("Action_NewSingleWellPlot")
        self._act_new_single_plot.triggered.connect(self._on_new_single_well_plot)
        self._act_new_single_plot.setEnabled(False)

        template_menu = bar.addMenu("图版")
        template_menu.setObjectName("Menu_图版")
        self._act_apply_template = template_menu.addAction("应用当前图版到选中井")
        self._act_apply_template.setObjectName("Action_ApplyTemplate")
        self._act_apply_template.triggered.connect(self._on_apply_template)
        self._act_apply_template.setEnabled(False)

        for name in ("导出", "帮助"):
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
        self.workspace_tree.currentItemChanged.connect(self._on_tree_selection)
        self.workspace_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        layout.addWidget(self.workspace_tree, 1)
        return pane

    def _build_center(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("CenterPane")
        layout = QVBoxLayout(pane)

        self.document_tabs = QTabWidget()
        self.document_tabs.setObjectName("DocumentTabs")
        self.document_tabs.setTabsClosable(False)
        self.document_tabs.setDocumentMode(True)

        host = QWidget()
        host.setObjectName("SingleWellPlotHost")
        hl = QVBoxLayout(host)
        self.plot_caption = QLabel("单井分析图 · 多图道（选择井并应用图版）")
        self.plot_caption.setObjectName("PlotCaption")
        hl.addWidget(self.plot_caption)
        self.multi_track_canvas = MultiTrackCanvas()
        hl.addWidget(self.multi_track_canvas, 1)

        self.document_tabs.addTab(host, "单井分析图（多图道）")
        layout.addWidget(self.document_tabs, 1)
        return pane

    def _build_right(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("RightPane")
        layout = QVBoxLayout(pane)

        layout.addWidget(QLabel("属性 / 图版 / 层位"))
        layout.addWidget(QLabel("图版模板（库 · 只应用）"))
        self.template_list = QListWidget()
        self.template_list.setObjectName("TemplateList")
        self.template_list.currentItemChanged.connect(
            lambda *_: self._sync_apply_enabled()
        )
        layout.addWidget(self.template_list)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("应用到选中井")
        self.apply_btn.setObjectName("Button_ApplyTemplate")
        self.apply_btn.clicked.connect(self._on_apply_template)
        self.apply_btn.setEnabled(False)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

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

    def _populate_templates(self) -> None:
        self.template_list.clear()
        if not self._templates:
            self.template_list.addItem("（无内置图版）")
            return
        for t in self._templates:
            item = QListWidgetItem(t.name)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.template_list.addItem(item)
        self.template_list.setCurrentRow(0)

    def _sync_apply_enabled(self) -> None:
        has_well = self._workspace is not None and self._selected_well_id is not None
        # Session may reload from disk on open; enable if well is in catalog.
        in_catalog = False
        if self._workspace and self._selected_well_id:
            in_catalog = any(
                w.id == self._selected_well_id for w in self._workspace.wells
            )
        ok = (
            has_well
            and in_catalog
            and self.template_list.currentItem() is not None
            and bool(self._templates)
        )
        self.apply_btn.setEnabled(ok)
        self._act_apply_template.setEnabled(ok)
        self._act_new_single_plot.setEnabled(ok)

    def _update_status(self) -> None:
        hint = effective_qt_platform_hint()
        if self._workspace is None:
            msg = f"Well Log Workstation · 未打开工区 · Qt: {hint}"
        else:
            well = self._selected_well_id or "—"
            tracks = (
                self._presentation.track_count if self._presentation else 0
            )
            msg = (
                f"工区: {self._workspace.name} · "
                f"井 {len(self._workspace.wells)} · "
                f"选中 {well[:8]}… · "
                f"图道 {tracks} · "
                f"Qt: {hint}"
            )
        self.statusBar().showMessage(msg)

    def set_workspace(self, ws: Workspace | None) -> None:
        self._workspace = ws
        if ws is None:
            self.session.clear()
            self._selected_well_id = None
            self._active_plot_id = None
            self._presentation = None
            self.multi_track_canvas.set_presentation(None)
            self.plot_caption.setText("单井分析图 · 多图道（选择井并应用图版）")
            self.document_tabs.setTabText(0, "单井分析图（多图道）")
        self._act_import_las.setEnabled(ws is not None)
        self._refresh_tree()
        self._sync_apply_enabled()
        self._update_status()
        if ws is not None:
            self.setWindowTitle(f"{ws.name} — Well Log Workstation")
        else:
            self.setWindowTitle("Well Log Workstation")

    def import_las_path(self, las_path: Path | str) -> str:
        if self._workspace is None:
            raise WorkspaceError("请先打开或新建工区")
        result = import_las_into_workspace(self._workspace, las_path)
        self.session.put(result.document)
        self._selected_well_id = result.catalog_well_id
        self._refresh_tree()
        self._select_well_in_tree(result.catalog_well_id)
        self._sync_apply_enabled()
        self._update_status()
        return result.catalog_well_id

    def _current_template_id(self) -> str | None:
        item = self.template_list.currentItem()
        if item is None:
            return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return str(tid) if tid else None

    def apply_template_to_well(
        self, well_id: str, template_id: str, *, plot_id: str | None = None
    ) -> HostPresentation:
        """Apply builtin template to a session well; show multi-track plot."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        doc = self.session.ensure_well_loaded(self._workspace, well_id)
        template = get_builtin_template(template_id)
        if template is None:
            raise WorkspaceError(f"未知图版: {template_id}")
        presentation = apply_template(template, doc)
        if presentation.curve_track_count < 1:
            raise WorkspaceError(
                "图版未能绑定任何曲线（检查 LAS 助记符与图版 mnemonics）"
            )
        self._selected_well_id = well_id
        self._presentation = presentation
        if plot_id is not None:
            self._active_plot_id = plot_id
        self.multi_track_canvas.set_presentation(presentation)
        self.plot_caption.setText(
            f"单井分析图 · {presentation.well_name} · "
            f"{presentation.template_name} · "
            f"{presentation.track_count} 图道"
        )
        tab = f"单井·多图道 · {presentation.well_name}"
        if self._active_plot_id:
            tab = f"{tab} · {self._active_plot_id[:8]}"
        self.document_tabs.setTabText(0, tab)
        self._sync_apply_enabled()
        self._update_status()
        return presentation

    def create_single_well_plot_document(
        self, well_id: str, template_id: str
    ) -> PlotDocument:
        """Create plots/<id>.json, catalog entry, open multi-track view."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        doc = self.session.ensure_well_loaded(self._workspace, well_id)
        plot = create_single_well_plot(
            self._workspace,
            well_id=well_id,
            well_name=doc.well_name,
            template_id=template_id,
        )
        self._active_plot_id = plot.id
        self.apply_template_to_well(well_id, template_id, plot_id=plot.id)
        self._refresh_tree()
        return plot

    def open_plot_document(self, plot_id: str) -> PlotDocument:
        """Load plot metadata, reload well, re-apply template into canvas."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        plot = load_plot_document(self._workspace, plot_id)
        if plot.type != "single_well":
            raise WorkspaceError("暂仅支持打开单井分析图（#222 对比图）")
        if not plot.well_ids:
            raise WorkspaceError("图件未绑定井")
        well_id = plot.well_ids[0]
        if not plot.template_id:
            raise WorkspaceError("图件未绑定图版")
        self._active_plot_id = plot.id
        self._selected_well_id = well_id
        self.apply_template_to_well(well_id, plot.template_id, plot_id=plot.id)
        # Keep template selection in sync
        for i in range(self.template_list.count()):
            item = self.template_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == plot.template_id:
                self.template_list.setCurrentRow(i)
                break
        self._select_well_in_tree(well_id)
        self._refresh_tree()
        return plot

    def _select_well_in_tree(self, well_id: str) -> None:
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == "well" and data.get("id") == well_id:
                return item
            for i in range(item.childCount()):
                hit = walk(item.child(i))
                if hit is not None:
                    return hit
            return None

        for i in range(self.workspace_tree.topLevelItemCount()):
            hit = walk(self.workspace_tree.topLevelItem(i))
            if hit is not None:
                self.workspace_tree.setCurrentItem(hit)
                return

    def _on_tree_selection(
        self, cur: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None
    ) -> None:
        if cur is None:
            return
        data = cur.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "well":
            self._selected_well_id = str(data.get("id"))
            self._sync_apply_enabled()
            self._update_status()

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != "plot":
            return
        plot_id = str(data.get("id") or "")
        if not plot_id:
            return
        try:
            self.open_plot_document(plot_id)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "打开图件失败", str(exc))

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
        if self._selected_well_id:
            self._select_well_in_tree(self._selected_well_id)

    def _on_new_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择空目录作为新工区")
        if not path:
            return
        try:
            ws = create_workspace(Path(path))
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
                f"{extra}\n\n"
                f"请在右栏选择图版并「应用到选中井」以显示多图道。",
            )
        except (LasImportError, WorkspaceError) as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))

    def _on_apply_template(self) -> None:
        if self._selected_well_id is None:
            QMessageBox.information(self, "应用图版", "请先在左树选择一口井。")
            return
        template_id = self._current_template_id()
        if not template_id:
            QMessageBox.information(self, "应用图版", "请选择图版模板。")
            return
        try:
            # Update open plot document template if one is active for this well
            if (
                self._active_plot_id
                and self._workspace is not None
            ):
                try:
                    plot = load_plot_document(self._workspace, self._active_plot_id)
                    if plot.well_ids == [self._selected_well_id]:
                        plot.template_id = template_id
                        save_plot_document(self._workspace, plot)
                except WorkspaceError:
                    pass
            pres = self.apply_template_to_well(
                self._selected_well_id,
                template_id,
                plot_id=self._active_plot_id,
            )
            QMessageBox.information(
                self,
                "图版已应用",
                f"井 {pres.well_name}\n"
                f"图版 {pres.template_name}\n"
                f"图道数 {pres.track_count}（曲线道 {pres.curve_track_count}）",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "应用图版失败", str(exc))

    def _on_new_single_well_plot(self) -> None:
        if self._selected_well_id is None:
            QMessageBox.information(self, "新建单井分析图", "请先选择一口井。")
            return
        template_id = self._current_template_id()
        if not template_id:
            QMessageBox.information(self, "新建单井分析图", "请选择图版模板。")
            return
        try:
            plot = self.create_single_well_plot_document(
                self._selected_well_id, template_id
            )
            QMessageBox.information(
                self,
                "图件已创建",
                f"已保存 {plot.path}\n"
                f"井绑定 {', '.join(plot.well_ids)}\n"
                f"图版 {plot.template_id}\n"
                f"双击左树图件可重新打开。",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "新建图件失败", str(exc))
