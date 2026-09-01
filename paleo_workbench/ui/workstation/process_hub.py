from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace
from paleo_workbench.ui.workstation.task_center import TaskCenter


class ProcessHub(QFrame):
    """Bottom process region: Agent, tasks, processing, logs, and console."""

    task_count_changed = Signal(int)

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

        agent_page = QWidget(self.tabs)
        agent_layout = QVBoxLayout(agent_page)
        agent_layout.setContentsMargins(0, 0, 0, 0)
        agent_layout.setSpacing(0)
        self.agent_splitter = QSplitter(Qt.Orientation.Horizontal, agent_page)
        self.agent = AgentWorkspace(project, self.agent_splitter)
        self.task_center = TaskCenter(self.agent_splitter)
        self.agent_splitter.addWidget(self.agent)
        self.agent_splitter.addWidget(self.task_center)
        self.agent_splitter.setStretchFactor(0, 1)
        self.agent_splitter.setStretchFactor(1, 1)
        self.agent_splitter.setSizes([620, 620])
        agent_layout.addWidget(self.agent_splitter)
        self.tabs.addTab(agent_page, "Agent")

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

        self.task_center.active_count_changed.connect(self.task_count_changed)

    def set_project(self, project, project_path: str | None = None) -> None:
        self.agent.set_project(project, project_path)

    def show_agent(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.agent.command_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def show_tasks(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.task_center.tree.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def submit_agent_command(self, text: str) -> None:
        self.show_agent()
        self.agent.submit(text)

    def shutdown(self) -> None:
        self.task_center.shutdown()
