from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from paleo_workbench.ui import style, tokens
from paleo_workbench.workflow.service import REQUIRED_RESOURCE_TYPES

RESOURCE_TYPES = REQUIRED_RESOURCE_TYPES


def _name_qss() -> str:
    pal = style.palette()
    return f"color: {pal['TEXT_SECONDARY']}; font-size: 12px;"


def _count_qss() -> str:
    pal = style.palette()
    return f"color: {pal['TEXT_PRIMARY']}; font-size: 12px; font-weight: 500;"


class ResourceSummaryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QHBoxLayout(self)
        # Compact single-line strip (UI v2): the two-row card cost a full
        # toolbar's worth of vertical space on the data page.
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_1, tokens.SPACE_3, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_3)
        self.name_labels: dict[str, QLabel] = {}
        self.count_labels: dict[str, QLabel] = {}
        self.type_labels = self.count_labels
        for rtype in RESOURCE_TYPES:
            group = QWidget()
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(tokens.SPACE_1)

            name_label = QLabel(tokens.RESOURCE_LABELS[rtype])
            style.bind(name_label, _name_qss)
            group_layout.addWidget(name_label)

            count_label = QLabel(f"0{tokens.RESOURCE_UNITS.get(rtype, '')}")
            style.bind(count_label, _count_qss)
            group_layout.addWidget(count_label)

            self.name_labels[rtype] = name_label
            self.count_labels[rtype] = count_label
            layout.addWidget(group)
        layout.addStretch()
        self.status_label = QLabel("—")
        self._ready: bool | None = None
        style.bind(self.status_label, self._status_qss)
        layout.addWidget(self.status_label)

    def _status_qss(self) -> str:
        pal = style.palette()
        if self._ready is None:
            return f"color: {pal['TEXT_SECONDARY']}; font-size: 12px;"
        token = "SUCCESS" if self._ready else "ERROR_RED"
        return f"color: {pal[token]}; font-size: 12px; font-weight: 500;"

    def update_state(self, state: dict) -> None:
        readiness = state.get("resource_readiness", {})
        available = readiness.get("available_counts", {})
        missing = readiness.get("missing_types", [])
        ready = readiness.get("ready", False)
        for rtype in RESOURCE_TYPES:
            count = available.get(rtype, 0)
            unit = tokens.RESOURCE_UNITS.get(rtype, "")
            self.count_labels[rtype].setText(f"{count}{unit}")
        if ready:
            self.status_label.setText("数据完整")
        else:
            missing_labels = [tokens.RESOURCE_LABELS.get(m, m) for m in missing]
            self.status_label.setText(f"缺少: {'、'.join(missing_labels)}")
        # 数据态变化只重渲染（R1 P2-8：重复 bind 会累积 destroyed 连接；
        # 注册一次，_ready 变化经 registry 重跑同一渲染器）。
        self._ready = bool(ready)
        style.refresh(self.status_label)
