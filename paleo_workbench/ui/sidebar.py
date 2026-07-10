from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens


class TextSidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TextSidebar")
        layout = QVBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.context_label = QLabel(tokens.PAGE_NAMES[0])
        self.context_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.context_label)
        self._content_labels: list[QLabel] = []
        self._render_context(tokens.PAGE_NAMES[0])
        layout.addStretch()

    def set_context(self, name: str) -> None:
        self.context_label.setText(name)
        if name == "数据":
            self.update_data_context(resource_count=0, artifact_count=0)
        elif name == "编图":
            self.update_mapping_context()
        else:
            self._render_context(name)

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
    ) -> None:
        """Show active map name, horizon, and dirty state for the 编图 page."""
        self.context_label.setText("编图")
        name_text = map_name or "未选择"
        horizon_text = horizon or "—"
        status_text = "未保存" if dirty else "已保存"
        self._render_lines(
            [
                ("编图上下文", True),
                (f"图件: {name_text}", False),
                (f"层位: {horizon_text}", False),
                (f"状态: {status_text}", False),
                ("相带画布", False),
                ("图面元素", False),
            ]
        )

    def _render_context(self, name: str) -> None:
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
            "编图": [
                ("编图上下文", True),
                ("图件: 未选择", False),
                ("层位: —", False),
                ("状态: 已保存", False),
                ("相带画布", False),
                ("图面元素", False),
            ],
            "成图审核": [
                ("成图审核", True),
                ("质检规则", False),
                ("问题列表", False),
                ("导出成果", False),
            ],
        }
        self._render_lines(page_lines.get(name, [(name, True)]))

    def _render_lines(self, lines: list[tuple[str, bool]]) -> None:
        for label in self._content_labels:
            self._layout.removeWidget(label)
            label.setParent(None)
        self._content_labels = []

        insert_at = 1
        for text, heading in lines:
            label = QLabel(text)
            label.setWordWrap(True)
            if heading:
                label.setStyleSheet(
                    f"color: {tokens.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;"
                )
            else:
                label.setStyleSheet(
                    f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
                )
            self._layout.insertWidget(insert_at, label)
            self._content_labels.append(label)
            insert_at += 1
