from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import field_value

_ATTRIBUTE_GROUPS = (
    ("振幅属性", ("振幅", "包络", "RMS振幅")),
    ("频率属性", ("瞬时频率",)),
    ("连续性属性", ("甜点", "相对阻抗")),
    ("结构属性", ("瞬时相位", "Dip_IL", "Dip_XL", "方位角", "平均曲率", "高斯曲率", "最大曲率")),
    ("多属性融合", ("RGB融合",)),
)

ALL_SEISMIC_ATTRIBUTES = [
    attr for _group, attrs in _ATTRIBUTE_GROUPS for attr in attrs
]


class SeismicContextToolbar(QFrame):
    """Single-row compact context toolbar with dropdown popovers for seismic prediction."""

    run_requested = Signal()
    demo_requested = Signal()
    attribute_changed = Signal(str)
    display_mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicContextToolbar")
        self._inferring = False
        self._suppress_signals = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_3)

        # 1. 工区地震体 (Source Volume Selector)
        source_label = QLabel("工区地震体")
        source_label.setObjectName("WorkFieldLabel")
        layout.addWidget(source_label)

        self.seismic_source_combo = QComboBox()
        self.seismic_source_combo.setObjectName("SeismicPredictionSourceCombo")
        self.seismic_source_combo.setPlaceholderText("选择数据管理中的 SEG-Y 地震体")
        self.seismic_source_combo.setToolTip(
            "选择工区数据中已归档的 .sgy / .segy 地震体，加载后可直接运行预测"
        )
        self.seismic_source_combo.setMinimumWidth(180)
        layout.addWidget(self.seismic_source_combo, 1)

        # 2. 地震属性下拉 (Seismic Attribute Selector)
        attr_label = QLabel("属性")
        attr_label.setObjectName("WorkFieldLabel")
        layout.addWidget(attr_label)

        self.attribute_combo = QComboBox()
        self.attribute_combo.setObjectName("SeismicAttributeDropdownCombo")
        self.attribute_combo.setToolTip("快速切换当前显示的地震属性")
        self.attribute_combo.addItems(ALL_SEISMIC_ATTRIBUTES)
        self.attribute_combo.currentTextChanged.connect(self._on_attribute_combo_changed)
        layout.addWidget(self.attribute_combo)

        # 3. 设置与属性弹出下拉按钮 (Settings & Context Dropdown Popover)
        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("SecondaryButton")
        self.settings_btn.setText("设置与详情 ▾")
        self.settings_btn.setToolTip("查看预测任务详情、目标层位、显示模式与状态")
        self.settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._build_settings_menu()
        layout.addWidget(self.settings_btn)

        # 4. 状态标签 (Status Indicator)
        status_prefix = QLabel("状态:")
        status_prefix.setObjectName("WorkFieldLabel")
        layout.addWidget(status_prefix)

        self.status_value = QLabel("—")
        self.status_value.setObjectName("WorkFieldValue")
        layout.addWidget(self.status_value)

        # 5. 弹性伸缩
        layout.addStretch(1)

        # 6. 操作按钮 (Action Buttons)
        self.demo_btn = QPushButton("运行演示预测")
        self.demo_btn.setObjectName("SecondaryButton")
        self.demo_btn.setToolTip(
            "显式演示模式：运行 DemoModelProvider（合成数据，非科学预测）"
        )
        self.demo_btn.clicked.connect(self.demo_requested.emit)
        layout.addWidget(self.demo_btn)

        self.run_btn = QPushButton("运行预测")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.setToolTip(
            "通过 ModelRegistry 解析生产模型后运行科学预测；"
            "未配置生产模型时不会自动运行 mock"
        )
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)

    def _build_settings_menu(self) -> None:
        """Create the popup menu containing context details and mode switches."""
        self.settings_menu = QMenu(self)
        self.settings_menu.setObjectName("SeismicSettingsMenu")

        # Context details card widget embedded inside QWidgetAction
        details_widget = QFrame()
        details_widget.setObjectName("SeismicSettingsDetailsCard")
        grid = QGridLayout(details_widget)
        grid.setContentsMargins(tokens.SPACE_3, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_2)
        grid.setSpacing(tokens.SPACE_2)

        # Task
        task_lbl = QLabel("任务:")
        task_lbl.setObjectName("WorkFieldLabel")
        self.task_value = QLabel("未选择预测任务")
        self.task_value.setObjectName("WorkFieldValue")
        grid.addWidget(task_lbl, 0, 0)
        grid.addWidget(self.task_value, 0, 1)

        # Horizon
        horizon_lbl = QLabel("层位:")
        horizon_lbl.setObjectName("WorkFieldLabel")
        self.horizon_value = QLabel("—")
        self.horizon_value.setObjectName("WorkFieldValue")
        grid.addWidget(horizon_lbl, 1, 0)
        grid.addWidget(self.horizon_value, 1, 1)

        # Attribute
        attr_lbl = QLabel("当前属性:")
        attr_lbl.setObjectName("WorkFieldLabel")
        self.attribute_value = QLabel("振幅")
        self.attribute_value.setObjectName("WorkFieldValue")
        grid.addWidget(attr_lbl, 2, 0)
        grid.addWidget(self.attribute_value, 2, 1)

        # Display Mode
        mode_lbl = QLabel("显示模式:")
        mode_lbl.setObjectName("WorkFieldLabel")
        self.mode_value = QLabel("vd")
        self.mode_value.setObjectName("WorkFieldValue")
        grid.addWidget(mode_lbl, 3, 0)
        grid.addWidget(self.mode_value, 3, 1)

        # Volume Shape
        shape_lbl = QLabel("体数据维度:")
        shape_lbl.setObjectName("WorkFieldLabel")
        self.shape_value = QLabel("—")
        self.shape_value.setObjectName("WorkFieldValue")
        grid.addWidget(shape_lbl, 4, 0)
        grid.addWidget(self.shape_value, 4, 1)

        # Output Nature
        mock_lbl = QLabel("输出性质:")
        mock_lbl.setObjectName("WorkFieldLabel")
        self.mock_value = QLabel("—")
        self.mock_value.setObjectName("WorkFieldValue")
        grid.addWidget(mock_lbl, 5, 0)
        grid.addWidget(self.mock_value, 5, 1)

        card_action = QWidgetAction(self.settings_menu)
        card_action.setDefaultWidget(details_widget)
        self.settings_menu.addAction(card_action)

        self.settings_menu.addSeparator()

        # Display Mode Submenu
        mode_menu = self.settings_menu.addMenu("切换显示模式")
        self._mode_group = QActionGroup(self)
        for mode_name in ("vd", "wiggle"):
            act = QAction(mode_name, self)
            act.setCheckable(True)
            if mode_name == "vd":
                act.setChecked(True)
            act.triggered.connect(lambda _c=False, m=mode_name: self._on_mode_action_triggered(m))
            self._mode_group.addAction(act)
            mode_menu.addAction(act)

        # Attribute Categories Submenu
        attr_menu = self.settings_menu.addMenu("切换地震属性")
        for group_label, labels in _ATTRIBUTE_GROUPS:
            group_sub = attr_menu.addMenu(group_label)
            for label in labels:
                act = QAction(label, self)
                act.triggered.connect(lambda _c=False, l=label: self._on_attr_action_triggered(l))
                group_sub.addAction(act)

        self.settings_btn.setMenu(self.settings_menu)

    def _on_attribute_combo_changed(self, text: str) -> None:
        if not self._suppress_signals and text:
            self.attribute_value.setText(text)
            self.attribute_changed.emit(text)

    def _on_mode_action_triggered(self, mode: str) -> None:
        self.mode_value.setText(mode)
        self.display_mode_changed.emit(mode)

    def _on_attr_action_triggered(self, label: str) -> None:
        self.set_selected_attribute(label)
        self.attribute_changed.emit(label)

    def set_selected_attribute(self, label: str) -> None:
        """Synchronize the attribute combo and label without recursion."""
        text = str(label or "").strip()
        if not text:
            return
        self.attribute_value.setText(text)
        self._suppress_signals = True
        idx = self.attribute_combo.findText(text)
        if idx >= 0:
            self.attribute_combo.setCurrentIndex(idx)
        self._suppress_signals = False

    def set_context(
        self,
        task,
        horizon: str,
        attribute: str,
        display_mode: str,
        volume_shape: tuple[int, int, int] | None = None,
        mock_nature: str | None = None,
    ) -> None:
        self.task_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.horizon_value.setText(str(horizon or "—"))
        self.set_selected_attribute(attribute or "振幅")
        mode = str(display_mode or "vd")
        self.mode_value.setText(mode)
        for act in self._mode_group.actions():
            if act.text() == mode:
                act.setChecked(True)
        if volume_shape is not None:
            self.shape_value.setText(" × ".join(str(v) for v in volume_shape) if volume_shape else "—")
        if mock_nature is not None:
            self.mock_value.setText(str(mock_nature))

    def set_inferring(self, busy: bool) -> None:
        """Enable/disable the run/demo actions for the duration of a run."""
        self._inferring = bool(busy)
        self.run_btn.setEnabled(not self._inferring)
        self.demo_btn.setEnabled(not self._inferring)
        if busy:
            self.status_value.setText("推断中…")

    def set_status(self, text: str) -> None:
        """Show an async run outcome in-page (no modal dialogs, #897)."""
        self.status_value.setText(str(text or "—"))
