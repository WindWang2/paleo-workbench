from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_helpers import field_value


class SequenceTargetPanel(QFrame):
    """Left-hand panel for active target horizon and sequence scope."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceTargetPanel")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("层序格架设置")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.target_value = self._add_value(layout, "目标层位", "未设置")
        self.version_value = self._add_value(layout, "解释版本", "v1")

        scheme_label = QLabel("体系域方案")
        scheme_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(scheme_label)
        self.scheme_combo = QComboBox()
        self.scheme_combo.addItem("LST/TST/HST")
        self.scheme_combo.addItems(tokens.SEQUENCE_SCHEMES)
        self.scheme_combo.setStyleSheet(
            f"QComboBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        layout.addWidget(self.scheme_combo)

        self.scope_value = self._add_value(layout, "适用范围", "0 口井 / 0 条测线")
        layout.addStretch()

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def update_state(self, stratigraphy) -> None:
        target = field_value(stratigraphy, "target_horizon", "") or "未设置"
        version = field_value(stratigraphy, "interpretation_version", "") or "v1"
        scheme = field_value(stratigraphy, "systems_tract_scheme", "") or "LST/TST/HST"
        wells = field_value(stratigraphy, "applicable_wells", []) or []
        seismic_ranges = field_value(stratigraphy, "applicable_seismic_ranges", []) or []

        self.target_value.setText(target)
        self.version_value.setText(version)
        if self.scheme_combo.findText(scheme) < 0:
            self.scheme_combo.addItem(scheme)
        self.scheme_combo.setCurrentText(scheme)
        self.scope_value.setText(f"{len(wells)} 口井 / {len(seismic_ranges)} 条测线")
