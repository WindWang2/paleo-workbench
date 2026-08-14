"""GovernanceMetadataDialog — edit the standard governance fields of an asset.

Free-text fields (source/region/creator) + controlled-vocabulary combos
(discipline/confidence/review_status). The dialog only collects a patch;
validation and persistence live in ``DataCatalogService.update_asset_metadata``
(vocabulary errors surface as dialog messages, never partial writes).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from paleo_workbench.catalog.governance import GOVERNANCE_FIELDS
from paleo_workbench.ui import tokens


class GovernanceMetadataDialog(QDialog):
    """Edit governance metadata for one catalog asset."""

    def __init__(self, parent=None, *, asset_name: str = "", current: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑治理信息 — {asset_name}" if asset_name else "编辑治理信息")
        self.setMinimumWidth(420)
        current = dict(current or {})

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        form = QFormLayout()
        self.source_edit = QLineEdit(current.get("source", ""))
        self.source_edit.setPlaceholderText("数据来源说明（如: 甲方移交 / 野外采集）")
        form.addRow("来源 (source):", self.source_edit)

        self.region_edit = QLineEdit(current.get("region", ""))
        self.region_edit.setPlaceholderText("研究区域（如: 塔里木盆地）")
        form.addRow("区域 (region):", self.region_edit)

        self.creator_edit = QLineEdit(current.get("creator", ""))
        self.creator_edit.setPlaceholderText("负责人 / 解释工程师")
        form.addRow("负责人 (creator):", self.creator_edit)

        self.discipline_combo = _vocab_combo(
            "discipline", current.get("discipline", "")
        )
        form.addRow("学科方向 (discipline):", self.discipline_combo)

        self.confidence_combo = _vocab_combo(
            "confidence", current.get("confidence", "")
        )
        form.addRow("可信等级 (confidence):", self.confidence_combo)

        self.review_combo = _vocab_combo(
            "review_status", current.get("review_status", "")
        )
        form.addRow("审核状态 (review_status):", self.review_combo)

        layout.addLayout(form)

        hint = QLabel(
            "提示: 留空/选“未设置”表示清除该字段；受控字段将按词表归一化存储。"
            "版本数据保持不可变 — 治理信息仅记录在资产级别。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(hint)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {tokens.ERROR_RED}; font-size: 11px;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存", self)
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _on_save(self) -> None:
        try:
            self.patch()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.accept()

    def patch(self) -> dict[str, str]:
        """Validated governance patch (raises ValueError on a bad value)."""
        from paleo_workbench.catalog.governance import normalize_governance_value

        values = {
            "source": self.source_edit.text().strip(),
            "region": self.region_edit.text().strip(),
            "creator": self.creator_edit.text().strip(),
            "discipline": self.discipline_combo.currentData() or "",
            "confidence": self.confidence_combo.currentData() or "",
            "review_status": self.review_combo.currentData() or "",
        }
        return {
            key: normalize_governance_value(key, value)
            for key, value in values.items()
        }


def _vocab_combo(key: str, current: str) -> QComboBox:
    """Combo for a controlled-vocabulary governance field (empty = unset)."""
    spec = GOVERNANCE_FIELDS[key]
    combo = QComboBox()
    combo.addItem("未设置", "")
    for value in spec.vocabulary:
        combo.addItem(spec.display.get(value, value), value)
    if current:
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo
