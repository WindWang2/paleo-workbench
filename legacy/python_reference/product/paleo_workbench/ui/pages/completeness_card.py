from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from paleo_workbench.ui import style, tokens
from paleo_workbench.workflow.service import REQUIRED_RESOURCE_TYPES

RESOURCE_TYPES = REQUIRED_RESOURCE_TYPES


class DataCompletenessCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4)
        layout.setSpacing(tokens.SPACE_2)
        self.title_label = QLabel("数据完整度")
        style.bind(
            self.title_label,
            lambda: (
                f"color: {style.palette()['TEXT_PRIMARY']};"
                f" font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
            ),
        )
        layout.addWidget(self.title_label)
        self.rows: list[dict] = []
        for rtype in RESOURCE_TYPES:
            name_label = QLabel(tokens.RESOURCE_LABELS[rtype])
            style.bind(
                name_label,
                lambda: (
                    f"color: {style.palette()['TEXT_PRIMARY']};"
                    f" font-size: {tokens.FONT_SIZE_BASE};"
                ),
            )
            count_label = QLabel(f"0{tokens.RESOURCE_UNITS.get(rtype, '')}")
            style.bind(
                count_label,
                lambda: (
                    f"color: {style.palette()['TEXT_SECONDARY']};"
                    f" font-size: {tokens.FONT_SIZE_STATUS};"
                ),
            )
            status_label = QLabel("—")
            # 数据驱动色（就绪=SUCCESS / 缺失=ERROR_RED）：渲染时经 palette
            # 取当前主题值；update_state 改 tone 后重注册即重渲染。
            status_row: dict = {"ready": None}

            def _status_sheet(row=status_row) -> str:
                pal = style.palette()
                if row["ready"] is None:
                    return (
                        f"color: {pal['TEXT_SECONDARY']};"
                        f" font-size: {tokens.FONT_SIZE_TITLE};"
                    )
                token = "SUCCESS" if row["ready"] else "ERROR_RED"
                return (
                    f"color: {pal[token]};"
                    f" font-size: {tokens.FONT_SIZE_STATUS}; font-weight: 500;"
                )

            style.bind(status_label, _status_sheet)
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(tokens.SPACE_2)
            row_layout.addWidget(name_label, 1)
            row_layout.addWidget(count_label)
            row_layout.addWidget(status_label)
            row_widget = QFrame()
            row_widget.setLayout(row_layout)
            self.rows.append({
                "name": name_label, "count": count_label,
                "status": status_label, "widget": row_widget,
                "status_row": status_row, "status_sheet": _status_sheet,
            })
            layout.addWidget(row_widget)
        self.summary_label = QLabel("—")
        self._summary_tone: str | None = None
        style.bind(self.summary_label, self._summary_sheet)
        layout.addWidget(self.summary_label)
        layout.addStretch()

    def _summary_sheet(self) -> str:
        pal = style.palette()
        if self._summary_tone is None:
            return (
                f"color: {pal['TEXT_SECONDARY']};"
                f" font-size: {tokens.FONT_SIZE_STATUS};"
            )
        token = "SUCCESS" if self._summary_tone == "ok" else "ERROR_RED"
        return (
            f"color: {pal[token]};"
            f" font-size: {tokens.FONT_SIZE_STATUS}; font-weight: 500;"
        )

    def update_state(self, state: dict) -> None:
        readiness = state.get("resource_readiness", {})
        available = readiness.get("available_counts", {})
        missing = readiness.get("missing_types", [])
        ready = readiness.get("ready", False)
        for i, rtype in enumerate(RESOURCE_TYPES):
            count = available.get(rtype, 0)
            unit = tokens.RESOURCE_UNITS.get(rtype, "")
            self.rows[i]["count"].setText(f"{count}{unit}")
            self.rows[i]["status"].setText("已就绪" if count > 0 else "缺失")
            self.rows[i]["status_row"]["ready"] = count > 0
            # 重注册即重渲染（数据态变化立即生效，主题切换时由 style 注册表刷新）
            style.bind(self.rows[i]["status"], self.rows[i]["status_sheet"])
        if ready:
            self.summary_label.setText("数据完整")
            self._summary_tone = "ok"
        else:
            missing_labels = [tokens.RESOURCE_LABELS.get(m, m) for m in missing]
            self.summary_label.setText(f"缺少: {'、'.join(missing_labels)}")
            self._summary_tone = "missing"
        style.bind(self.summary_label, self._summary_sheet)
