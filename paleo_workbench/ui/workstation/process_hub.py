from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
)

from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace


class ProcessHub(QFrame):
    """Bottom Agent region: Agent console plus processing / logs / console tabs.

    任务中心（TaskCenter）是独立的 dock 面板，由 WorkstationFrame 创建并
    停靠——不再与 Agent 焊在同一窗格里，两者可分别浮动 / 显隐。
    """

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationProcessHub")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("WorkstationProcessTabs")
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs)

        self.agent = AgentWorkspace(project, self.tabs)
        self.tabs.addTab(self.agent, "Agent")

        self.processing = QPlainTextEdit(self.tabs)
        self.processing.setReadOnly(True)
        self.processing.setPlainText(
            "处理管线会在这里显示输入、参数、阶段、输出和血缘。\n"
            "长时间操作同时进入任务中心，可取消并在页面切换后继续观察。"
        )
        self.tabs.addTab(self.processing, "处理")

        self.logs = QPlainTextEdit(self.tabs)
        self.logs.setReadOnly(True)
        self.logs.setPlainText("工作站日志已就绪。")
        self.tabs.addTab(self.logs, "日志")

        self.console = QPlainTextEdit(self.tabs)
        self.console.setReadOnly(True)
        self.console.setPlainText("Paleo Workbench console\nProject context is available through typed actions.")
        self.tabs.addTab(self.console, "控制台")

    def set_project(self, project, project_path: str | None = None) -> None:
        self.agent.set_project(project, project_path)

    def show_agent(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.agent.command_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def submit_agent_command(self, text: str) -> None:
        self.show_agent()
        self.agent.submit(text)

    def shutdown(self) -> None:
        pass
