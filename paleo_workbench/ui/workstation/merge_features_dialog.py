"""无缝合并确认对话框（拓扑编辑迁移 M3 §4）。

预填面积最大要素属性（下拉可换源要素），相分类字段冲突高亮可改。
确认后由调用方把 ``result_payload()`` 交给桥 ``merge_mirror_features``。
轻量 QDialog（对照 ``ui/crs_guidance.py``）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from paleo_workbench.mapping.merge_attributes import plan_merge_attributes

__all__ = ["MergeFeaturesDialog"]


class MergeFeaturesDialog(QDialog):
    """合并确认：源要素下拉 + 可编辑属性（冲突高亮）。"""

    def __init__(self, records, *, facies_fields=("facies",), parent=None):
        super().__init__(parent)
        self.setObjectName("MergeFeaturesDialog")
        self.setWindowTitle("合并要素")
        self._records = [dict(record) for record in records]
        self.plan = plan_merge_attributes(self._records, facies_fields=facies_fields)
        self._attributes = dict(self.plan.get("attributes") or {})
        self._edits: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        intro = QLabel("合并后保留一块几何。属性默认取面积最大的要素，可改源或改值。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._source = QComboBox(self)
        for record in self._records:
            feature_id = str(record.get("id") or "")
            self._source.addItem(feature_id, feature_id)
        target = str(self.plan.get("target_id") or "")
        index = self._source.findData(target)
        if index >= 0:
            self._source.setCurrentIndex(index)
        self._source.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(QLabel("属性来源："))
        layout.addWidget(self._source)

        self._form = QFormLayout()
        layout.addLayout(self._form)
        self._rebuild_form()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _conflicts(self) -> set[str]:
        conflicts = self.plan.get("conflicts") or {}
        return {str(key) for key in conflicts}

    def _facies_fields(self) -> set[str]:
        return {str(name) for name in (self.plan.get("facies_fields") or ("facies",))}

    def _rebuild_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._edits.clear()
        keys: list[str] = []
        for key in self._attributes:
            if key not in keys:
                keys.append(str(key))
        for key in sorted(self._conflicts()):
            if key not in keys:
                keys.append(key)
        for key in keys:
            edit = QLineEdit(self)
            value = self._attributes.get(key)
            edit.setText("" if value is None else str(value))
            edit.textChanged.connect(
                lambda text, field=key: self._attributes.__setitem__(field, text))
            if key in self._conflicts():
                # 冲突高亮：相分类字段更醒目。
                color = "#fde8a0" if key in self._facies_fields() else "#fff3cd"
                edit.setStyleSheet(f"QLineEdit {{ background: {color}; }}")
                edit.setToolTip("所选要素该字段值不一致")
            self._form.addRow(key, edit)
            self._edits[key] = edit

    def _on_source_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._records):
            return
        record = self._records[index]
        self.plan["target_id"] = str(record.get("id") or "")
        properties = record.get("properties") if isinstance(record.get("properties"), dict) else {}
        self._attributes = dict(properties)
        self._rebuild_form()

    def set_field_value(self, field: str, value) -> None:
        """测试/调用方改值入口（同步到编辑框）。"""
        field = str(field)
        text = "" if value is None else str(value)
        self._attributes[field] = text
        edit = self._edits.get(field)
        if edit is not None:
            edit.setText(text)
        else:
            self._rebuild_form()

    def result_payload(self) -> dict[str, object]:
        """桥 merge_mirror_features 的 attrs_json 对象。"""
        return {
            "target_id": str(self.plan.get("target_id") or ""),
            "attributes": dict(self._attributes),
        }
