from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_helpers import field_value


class SequenceTargetPanel(QFrame):
    """Left-hand panel for active target horizon and sequence scope."""

    target_changed = Signal(str)
    scheme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceTargetPanel")
        self.setFixedWidth(240)
        self._suppress = False

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

        target_label = QLabel("目标层位")
        target_label.setObjectName("WorkFieldLabel")
        layout.addWidget(target_label)
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.target_combo.setObjectName("SequenceTargetCombo")
        self.target_combo.setStyleSheet(
            f"QComboBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        self.target_combo.lineEdit().setPlaceholderText("未设置")
        # For an editable combo, ``currentTextChanged`` fires on every keystroke
        # and cascades apply_stratigraphy_scheme (writes partial horizons into
        # the project + a full refresh per keystroke). Fire only on commit:
        # dropdown selection (``activated``) and Enter/return (``returnPressed``).
        line_edit = self.target_combo.lineEdit()
        line_edit.returnPressed.connect(self._on_target_committed)
        self.target_combo.activated.connect(lambda _i: self._on_target_committed())
        layout.addWidget(self.target_combo)
        # Alias: prefer currentText() / target_horizon_text() over .text().
        self.target_value = self.target_combo

        self.version_value = self._add_value(layout, "解释版本", "v1")

        scheme_label = QLabel("体系域方案")
        scheme_label.setObjectName("WorkFieldLabel")
        layout.addWidget(scheme_label)
        self.scheme_combo = QComboBox()
        self.scheme_combo.addItem("LST/TST/HST")
        self.scheme_combo.addItems(tokens.SEQUENCE_SCHEMES)
        self.scheme_combo.setStyleSheet(
            f"QComboBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        self.scheme_combo.currentTextChanged.connect(self._on_scheme_text)
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

    def current_target(self) -> str:
        return self.target_combo.currentText().strip()

    def target_horizon_text(self) -> str:
        """Display text for the active target (empty → 未设置)."""
        text = self.current_target()
        return text if text else "未设置"

    def current_scheme(self) -> str:
        return self.scheme_combo.currentText().strip()

    def _on_target_text(self, text: str) -> None:
        if not self._suppress:
            self.target_changed.emit(text.strip())

    def _on_target_committed(self) -> None:
        """Emit target change only on a committed edit (Enter / selection).

        Both ``returnPressed`` and ``activated`` can fire for the same Enter
        press on an editable combo, so dedupe on the committed text.
        """
        if self._suppress:
            return
        text = self.current_target()
        if text == getattr(self, "_last_committed_target", None):
            return
        self._last_committed_target = text
        self.target_changed.emit(text)

    def _on_scheme_text(self, text: str) -> None:
        if not self._suppress:
            self.scheme_changed.emit(text.strip())

    def update_state(self, stratigraphy) -> None:
        target = field_value(stratigraphy, "target_horizon", "") or ""
        version = field_value(stratigraphy, "interpretation_version", "") or "v1"
        scheme = field_value(stratigraphy, "systems_tract_scheme", "") or "LST/TST/HST"
        wells = field_value(stratigraphy, "applicable_wells", []) or []
        seismic_ranges = field_value(stratigraphy, "applicable_seismic_ranges", []) or []
        boundaries = list(field_value(stratigraphy, "sequence_boundaries", []) or [])

        self._suppress = True
        self.target_combo.clear()
        options: list[str] = []
        for name in boundaries:
            text = str(name).strip()
            if text and text not in options:
                options.append(text)
        if target and target not in options:
            options.insert(0, target)
        if not options:
            options = [""]
        self.target_combo.addItems(options)
        if target:
            idx = self.target_combo.findText(target)
            if idx >= 0:
                self.target_combo.setCurrentIndex(idx)
            else:
                self.target_combo.setEditText(target)
        else:
            self.target_combo.setCurrentIndex(0)
            self.target_combo.setEditText("")

        self.version_value.setText(version)
        if self.scheme_combo.findText(scheme) < 0:
            self.scheme_combo.addItem(scheme)
        self.scheme_combo.setCurrentText(scheme)
        self.scope_value.setText(f"{len(wells)} 口井 / {len(seismic_ranges)} 条测线")
        self._suppress = False
