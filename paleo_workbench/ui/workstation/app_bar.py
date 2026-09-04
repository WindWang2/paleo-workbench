from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QToolButton,
)

from paleo_workbench import tokens
from paleo_workbench.ui.workstation.common import workstation_icon


class WorkstationAppBar(QFrame):
    """Global-only actions and project context for the workstation shell."""

    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    command_submitted = Signal(str)
    agent_requested = Signal()
    task_center_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationAppBar")
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        brand_icon = QLabel(self)
        brand_icon.setObjectName("WorkstationBrandIcon")
        brand_icon.setPixmap(
            workstation_icon("seismic.svg", tokens.PRIMARY).pixmap(20, 20)
        )
        layout.addWidget(brand_icon)

        self.brand_label = QLabel("Paleo Workbench", self)
        self.brand_label.setObjectName("WorkstationBrand")
        layout.addWidget(self.brand_label)

        self.project_button = QToolButton(self)
        self.project_button.setObjectName("WorkstationProjectButton")
        self.project_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.project_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_button.setIcon(workstation_icon("folder-open.svg"))
        self._project_menu = QMenu(self.project_button)
        self._project_menu.addAction("新建工程", self.new_project_requested.emit)
        self._project_menu.addAction("打开工程", self.open_project_requested.emit)
        self._project_menu.addAction("打开示例", self.open_sample_requested.emit)
        self._project_menu.addSeparator()
        self._project_menu.addAction("保存工程", self.save_project_requested.emit)
        self._project_menu.addAction("工程属性", self.properties_requested.emit)
        self.project_button.setMenu(self._project_menu)
        layout.addWidget(self.project_button)

        self.back_button = QToolButton(self)
        self.back_button.setObjectName("WorkstationChromeButton")
        self.back_button.setIcon(workstation_icon("arrow-left.svg"))
        self.back_button.setToolTip("后退")
        self.back_button.setEnabled(False)
        layout.addWidget(self.back_button)

        self.forward_button = QToolButton(self)
        self.forward_button.setObjectName("WorkstationChromeButton")
        self.forward_button.setIcon(workstation_icon("arrow-right.svg"))
        self.forward_button.setToolTip("前进")
        self.forward_button.setEnabled(False)
        layout.addWidget(self.forward_button)

        layout.addStretch(1)

        self.command_input = QLineEdit(self)
        self.command_input.setObjectName("WorkstationCommandInput")
        self.command_input.setPlaceholderText("搜索命令、数据或输入 Agent 指令 (Ctrl+K)")
        self.command_input.setClearButtonEnabled(True)
        self.command_input.setMinimumWidth(300)
        self.command_input.setMaximumWidth(580)
        self.command_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.command_input.returnPressed.connect(self._submit_command)
        layout.addWidget(self.command_input, 2)

        layout.addStretch(1)

        # B1/B16：视图菜单是主题与密度的生产入口（此前 set_theme 只有测试
        # 调用，暗色/高对比在生产不可达；Ribbon 密度按钮随 Ribbon 0 高不可见）。
        self.view_button = QToolButton(self)
        self.view_button.setObjectName("WorkstationChromeButton")
        self.view_button.setIcon(workstation_icon("rb-density-comfortable.svg"))
        self.view_button.setText("视图")
        self.view_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.view_button.setToolTip("主题与界面密度")
        self._view_menu = QMenu(self.view_button)
        self._theme_group = QActionGroup(self._view_menu)
        self._density_group = QActionGroup(self._view_menu)
        from paleo_workbench.ui.theme import DensityMode, ThemeMode, theme_manager

        for mode, label in (
            (ThemeMode.LIGHT, "浅色主题"),
            (ThemeMode.DARK, "深色主题"),
            (ThemeMode.HIGH_CONTRAST, "高对比主题"),
        ):
            action = self._view_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(theme_manager.current_theme is mode)
            action.setActionGroup(self._theme_group)
            action.triggered.connect(
                lambda _checked=False, m=mode: theme_manager.set_theme(m)
            )
        self._view_menu.addSeparator()
        for mode, label in (
            (DensityMode.COMPACT, "紧凑密度"),
            (DensityMode.COMFORTABLE, "舒适密度"),
        ):
            action = self._view_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(theme_manager.density is mode)
            action.setActionGroup(self._density_group)
            action.triggered.connect(
                lambda _checked=False, m=mode: theme_manager.set_density(m)
            )
        # 主题/密度变化时刷新勾选态（跨入口切换保持一致）。
        def _sync_view_checks(*_args) -> None:
            for action, mode in zip(self._theme_group.actions(), list(ThemeMode)):
                action.setChecked(theme_manager.current_theme is mode)
            for action, mode in zip(
                self._density_group.actions(), list(DensityMode)
            ):
                action.setChecked(theme_manager.density is mode)

        theme_manager.theme_changed.connect(_sync_view_checks)
        self.view_button.setMenu(self._view_menu)
        layout.addWidget(self.view_button)

        self.task_button = QToolButton(self)
        self.task_button.setObjectName("WorkstationTaskButton")
        self.task_button.setIcon(workstation_icon("rb-run.svg"))
        self.task_button.setText("任务 0")
        self.task_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.task_button.setToolTip("打开任务中心")
        self.task_button.clicked.connect(self.task_center_requested.emit)
        layout.addWidget(self.task_button)

        self.agent_button = QToolButton(self)
        self.agent_button.setObjectName("WorkstationAgentButton")
        self.agent_button.setIcon(workstation_icon("visualization.svg"))
        self.agent_button.setText("Agent")
        self.agent_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.agent_button.setToolTip("打开上下文感知 Agent 工作区")
        self.agent_button.clicked.connect(self.agent_requested.emit)
        layout.addWidget(self.agent_button)

        self.set_project("未命名工程", "")

    def set_project(self, name: str, region: str = "") -> None:
        project = str(name or "未命名工程")
        area = str(region or "").strip()
        if area.casefold() == project.casefold():
            area = ""
        self._project_region = area
        self.project_button.setText(f"{project}  /  {area}" if area else project)
        self.project_button.setToolTip("切换工程或打开工程操作")

    def set_project_name(self, name: str) -> None:
        self.set_project(name, getattr(self, "_project_region", ""))

    def set_task_count(self, active: int) -> None:
        count = max(0, int(active))
        self.task_button.setText(f"任务 {count}")
        self.task_button.setProperty("activeTasks", count > 0)
        self.task_button.style().unpolish(self.task_button)
        self.task_button.style().polish(self.task_button)

    def focus_command(self) -> None:
        self.command_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.command_input.selectAll()

    def _submit_command(self) -> None:
        text = self.command_input.text().strip()
        if not text:
            return
        self.command_input.clear()
        self.command_submitted.emit(text)
