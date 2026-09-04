from __future__ import annotations

import logging
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
)

from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace

#: 日志查看器行数上限：超出丢弃最旧（部件与内存缓冲同上限）。
LOG_LINE_CAP = 2000


class QtLogHandler(QObject, logging.Handler):
    """logging → Qt 的轻量桥：记录格式化后经信号送出（跨线程安全）。

    ``emit`` 可能在任意工作线程被调用：这里只做格式化 + Qt 信号发射
    （跨线程信号由 Qt 排队到接收方线程），绝不直接触碰界面部件；同时
    把行存入有界内存缓冲，供 1s 轮询定时器兜底取走——信号未连接或事件
    循环繁忙的窗口期内日志不丢行。
    """

    message_ready = Signal(str)

    def __init__(self, capacity: int = LOG_LINE_CAP, parent: QObject | None = None):
        QObject.__init__(self, parent)
        logging.Handler.__init__(self, level=logging.INFO)
        self._formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"
        )
        self._pending: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self._formatter.format(record)
        except Exception:  # noqa: BLE001 — logging 契约：handler 不得抛出
            self.handleError(record)
            return
        self._pending.append(line)
        self.message_ready.emit(line)

    def take_pending(self) -> list[str]:
        """取走尚未消费的格式化行（轮询路径），取后清空。"""
        lines = list(self._pending)
        self._pending.clear()
        return lines


class ProcessHub(QFrame):
    """Bottom Agent region: Agent console plus 任务 / 日志 / 控制台 tabs.

    任务中心（TaskCenter）是独立的 dock 面板，由 WorkstationFrame 创建并
    停靠——不再与 Agent 焊在同一窗格里，两者可分别浮动 / 显隐。
    「日志」是真实的日志查看器：轮询包内 logger 的内存 handler，
    readonly，行数上限 :data:`LOG_LINE_CAP`。
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
            "处理任务会在这里显示输入、参数、阶段、输出和血缘。\n"
            "长时间操作同时进入任务中心，可取消并在页面切换后继续观察。"
        )
        self.tabs.addTab(self.processing, "任务")

        # --- 日志查看器：包内 logger → 内存 handler → 1s 轮询 ------------
        self.logs = QPlainTextEdit(self.tabs)
        self.logs.setObjectName("WorkstationLogView")
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(LOG_LINE_CAP)
        self.tabs.addTab(self.logs, "日志")

        self._log_handler = QtLogHandler(parent=self)
        self._log_handler.message_ready.connect(self._drain_log_lines)
        self._log_source = logging.getLogger("paleo_workbench")
        # 默认继承 root 的 WARNING：降到 INFO 让查看器可见（包级，不动
        # root；应用未配置其它 handler，不会产生控制台噪音）。
        if self._log_source.level == logging.NOTSET:
            self._log_source.setLevel(logging.INFO)
        self._log_source.addHandler(self._log_handler)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(1000)
        self._log_timer.timeout.connect(self._drain_log_lines)
        self._log_timer.start()

        self.console = QPlainTextEdit(self.tabs)
        self.console.setReadOnly(True)
        self.console.setPlainText("预留：嵌入式控制台")
        self.tabs.addTab(self.console, "控制台")

    def set_project(self, project, project_path: str | None = None) -> None:
        self.agent.set_project(project, project_path)

    def show_agent(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.agent.command_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def submit_agent_command(self, text: str) -> None:
        self.show_agent()
        self.agent.submit(text)

    def _drain_log_lines(self, *_args) -> None:
        """信号槽与轮询定时器共用的取行入口（取后清空，绝不重复）。"""
        for line in self._log_handler.take_pending():
            self.logs.appendPlainText(line)

    def shutdown(self) -> None:
        # 摘除全局 logger 上的 handler：壳重建一次会新建一个 ProcessHub，
        # 不摘除的话 handler 会越积越多（每个都格式化一遍全部记录）。
        self._log_timer.stop()
        if self._log_handler in self._log_source.handlers:
            self._log_source.removeHandler(self._log_handler)
