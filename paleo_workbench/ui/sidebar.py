from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from paleo_workbench import tokens
from paleo_workbench.ui import navigation


class ContextSidebar(QFrame):
    """Dynamic context-sensitive ergonomic sidebar.

    Structure (Inverted-L Flow):
    1. Top Sub-page Segmented Control (switching sub-pages within current stage)
    2. Middle Context Information & Quick Actions
    3. Bottom Collapse/Expand Toggle
    """

    subpage_selected = Signal(int)
    collapsed_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContextSidebar")
        self._is_collapsed = False
        self._current_stage_index = 0
        self._active_page_index = navigation.PAGE_INDEX_DATA
        self.subpage_buttons: list[QPushButton] = []
        self._content_labels: list[QLabel] = []

        main_layout = QVBoxLayout(self)
        self._main_layout = main_layout
        self._layout = main_layout
        main_layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        main_layout.setSpacing(tokens.SPACE_2)

        # 1. Top Section: Sub-page Segmented Navigation Bar
        self.subpage_container = QWidget()
        self.subpage_layout = QVBoxLayout(self.subpage_container)
        self.subpage_layout.setContentsMargins(0, 0, 0, 0)
        self.subpage_layout.setSpacing(tokens.SPACE_1)
        main_layout.addWidget(self.subpage_container)

        # 2. Middle Section: Context Header & Lines
        self.context_label = QLabel(tokens.PAGE_NAMES[0])
        self.context_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE};"
            f" font-weight: {tokens.FONT_WEIGHT_TITLE};"
        )
        main_layout.addWidget(self.context_label)

        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(tokens.SPACE_2)
        main_layout.addWidget(self.content_container)

        main_layout.addStretch()

        # 3. Bottom Section: Ergonomic Collapse/Expand Toggle Button
        self.collapse_btn = QPushButton("◀ 收起")
        self.collapse_btn.setObjectName("SidebarCollapseBtn")
        self.collapse_btn.setToolTip("折叠/展开侧边栏")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFixedHeight(32)
        self.collapse_btn.clicked.connect(lambda: self.toggle_collapse())
        main_layout.addWidget(self.collapse_btn)

        # Initialize for default stage 0
        self.set_stage(navigation.STAGE_INDEX_DATA, navigation.PAGE_INDEX_DATA)
        self._render_context(tokens.PAGE_NAMES[0])

    @property
    def is_collapsed(self) -> bool:
        return self._is_collapsed

    def set_stage(self, stage_index: int, active_page_index: int = -1) -> None:
        """Update segmented sub-page control buttons for the selected Stage."""
        self._current_stage_index = stage_index
        subpage_indices = navigation.get_subpages_for_stage(stage_index)

        if active_page_index not in subpage_indices and subpage_indices:
            active_page_index = subpage_indices[0]
        self._active_page_index = active_page_index

        # Clear existing buttons
        for btn in self.subpage_buttons:
            self.subpage_layout.removeWidget(btn)
            btn.setParent(None)
        self.subpage_buttons.clear()

        for page_idx in subpage_indices:
            page_name = tokens.PAGE_NAMES[page_idx] if page_idx < len(tokens.PAGE_NAMES) else f"Page {page_idx}"
            btn = QPushButton(page_name)
            btn.setProperty("subpageItem", True)
            btn.setProperty("active", page_idx == active_page_index)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _checked=False, p=page_idx: self._on_subpage_clicked(p))
            self.subpage_buttons.append(btn)
            self.subpage_layout.addWidget(btn)

        self.subpage_container.setVisible(not self._is_collapsed and len(self.subpage_buttons) > 1)

    def _on_subpage_clicked(self, page_index: int) -> None:
        if page_index == self._active_page_index:
            return
        old_idx = self._active_page_index
        self._active_page_index = page_index

        for btn in self.subpage_buttons:
            is_active = (btn.text() == tokens.PAGE_NAMES[page_index])
            btn.setProperty("active", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.subpage_selected.emit(page_index)

    def toggle_collapse(self, collapsed: bool | None = None) -> None:
        if collapsed is None:
            collapsed = not self._is_collapsed
        if collapsed == self._is_collapsed:
            return

        self._is_collapsed = collapsed
        if collapsed:
            self.setFixedWidth(40)
            self.context_label.hide()
            self.content_container.hide()
            self.subpage_container.hide()
            self.collapse_btn.setText("▶")
        else:
            self.setMinimumWidth(180)
            self.setMaximumWidth(260)
            self.setFixedWidth(200)
            self.context_label.show()
            self.content_container.show()
            self.subpage_container.setVisible(len(self.subpage_buttons) > 1)
            self.collapse_btn.setText("◀ 收起")

        self.collapsed_changed.emit(self._is_collapsed)

    # --- Backward compatibility context methods ---

    def set_context(self, name: str) -> None:
        self.context_label.setText(name)
        if name == "数据":
            self.update_data_context(resource_count=0, artifact_count=0)
        elif name == "编图":
            self.update_mapping_context()
        else:
            self.update_context(name)

    def update_data_context(
        self,
        resource_count: int,
        artifact_count: int,
        issue_count: int = 0,
        selected_name: str = "未选择",
        selected_type: str = "",
        selected_format: str = "",
        reader_mode: str = "empty",
    ) -> None:
        self.context_label.setText("数据")
        format_text = (
            f"{selected_type} / {selected_format}"
            if selected_type or selected_format
            else "未选择"
        )
        self._render_lines(
            [
                ("数据概览", True),
                (f"资源 {resource_count}", False),
                (f"成果 {artifact_count}", False),
                (f"异常 {issue_count}", False),
                ("当前选择", True),
                (f"当前选择: {selected_name}", False),
                (f"格式: {format_text}", False),
                (f"阅读器: {reader_mode}", False),
                ("管理", True),
                ("导入文件 / 导入目录", False),
                ("重新扫描 / 移出项目", False),
                ("打开目录", False),
            ]
        )

    def update_mapping_context(
        self,
        map_name: str = "未选择",
        horizon: str = "",
        dirty: bool = False,
        preview: bool = False,
    ) -> None:
        self.context_label.setText("编图")
        name_text = map_name or "未选择"
        horizon_text = horizon or "—"
        status_text = "未保存" if dirty else "已保存"
        mode_text = "图面预览" if preview else "编辑"
        self._render_lines(
            [
                ("编图上下文", True),
                (f"图件: {name_text}", False),
                (f"层位: {horizon_text}", False),
                (f"状态: {status_text}", False),
                (f"模式: {mode_text}", False),
                ("相带画布", False),
                ("图面元素", False),
            ]
        )

    def update_context(self, name: str, progress: str = "", selection: str = "", tips: str = "") -> None:
        self.context_label.setText(name)
        lines = self._page_lines(name)
        if progress:
            lines.append(("工作流", True))
            lines.append((progress, False))
        if selection:
            lines.append(("当前选择", True))
            lines.append((selection, False))
        if tips:
            lines.append(("快捷操作", True))
            lines.append((tips, False))
        self._render_lines(lines)

    def _page_lines(self, name: str) -> list[tuple[str, bool]]:
        page_lines = {
            "首页": [
                ("项目总览", True),
                ("流程进度", False),
                ("近期活动", False),
                ("数据完整性", False),
            ],
            "测井预测": [
                ("测井预测", True),
                ("任务列表", False),
                ("曲线预览", False),
                ("证据贡献", False),
            ],
            "地震预测": [
                ("地震预测", True),
                ("任务列表", False),
                ("体数据视图", False),
                ("预测参数", False),
            ],
            "层序格架": [
                ("层序格架", True),
                ("目标层位", False),
                ("界面列表", False),
                ("体系域方案", False),
            ],
            "地层对比": [
                ("地层对比", True),
                ("对比井选择", False),
                ("连井剖面", False),
                ("导出 SVG", False),
            ],
            "可视化": [
                ("综合可视化", True),
                ("测井 / 地震 / 连井", False),
                ("资源与成果联动", False),
            ],
            "制备": [
                ("制图数据制备", True),
                ("单因素图", False),
                ("边界参数", False),
                ("批量生成", False),
            ],
            "成图审核": [
                ("成图审核", True),
                ("质检规则", False),
                ("问题列表", False),
                ("导出成果", False),
            ],
        }
        return page_lines.get(name, [(name, True)])

    def _render_context(self, name: str) -> None:
        self.update_context(name)

    def _render_lines(self, lines: list[tuple[str, bool]]) -> None:
        # Clear existing content labels
        for label in self._content_labels:
            self.content_layout.removeWidget(label)
            label.setParent(None)
        self._content_labels.clear()

        for text, heading in lines:
            label = QLabel(text)
            label.setWordWrap(True)
            if heading:
                label.setStyleSheet(
                    f"color: {tokens.TEXT_PRIMARY};"
                    f" font-size: {tokens.FONT_SIZE_SIDEBAR_SECONDARY}; font-weight: 600;"
                )
            else:
                label.setStyleSheet(
                    f"color: {tokens.TEXT_SECONDARY};"
                    f" font-size: {tokens.FONT_SIZE_SIDEBAR_SECONDARY};"
                )
            self.content_layout.addWidget(label)
            self._content_labels.append(label)


class TextSidebar(ContextSidebar):
    """Backward compatibility subclass for TextSidebar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TextSidebar")
