"""Well detail panel — the V11 per-well data view surface.

Rendered from :class:`~paleo_workbench.catalog.entity_views.WellDataView`
(the read facade over project domain + catalog). The panel owns no state
beyond the last view it was handed — every refresh re-assembles from the
authorities, so there is no second data store to drift.

Shows: identity header, per-role slots (primary badge, member count,
current version), missing roles (data-completeness at a glance), stale
downstream products, uncommitted edits, and missing sources.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens


class _SectionCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("WellDetailCard")
        palette = tokens.palette_for("light")
        self.setStyleSheet(
            f"QFrame#WellDetailCard {{ background: {palette['BG_SEARCH']};"
            f" border: 1px solid {palette['BORDER']};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.SPACE_4, tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_4
        )
        self._layout.setSpacing(tokens.SPACE_2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 600;")
        self._layout.addWidget(title_label)
        self.body = QVBoxLayout()
        self._layout.addLayout(self.body)


class WellDetailPanel(QWidget):
    """Center-stack page showing one well's full data view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellDetailPanel")
        self._view: Any = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_3)

        self._title = QLabel("井数据视图")
        self._title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet("color: #666;")
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)

        self._roles_table = QTableWidget(0, 5)
        self._roles_table.setHorizontalHeaderLabels(
            ["角色", "资产", "主用", "当前版本", "版本数"]
        )
        self._roles_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._roles_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._roles_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._roles_table.verticalHeader().setVisible(False)
        layout.addWidget(self._roles_table, 2)

        self._status_row = QHBoxLayout()
        self._stale_card = _SectionCard("过期成果")
        self._edits_card = _SectionCard("未提交编辑")
        self._missing_card = _SectionCard("缺失/异常")
        for card in (self._stale_card, self._edits_card, self._missing_card):
            self._status_row.addWidget(card, 1)
        layout.addLayout(self._status_row, 1)

    # ------------------------------------------------------------------

    def set_view(self, view: Any) -> None:
        """Render a WellDataView (pass None to reset)."""
        self._view = view
        if view is None:
            self._title.setText("井数据视图")
            self._subtitle.setText("")
            self._roles_table.setRowCount(0)
            for card in (self._stale_card, self._edits_card, self._missing_card):
                self._clear_layout(card.body)
            return
        well = getattr(view, "well", None) or getattr(view, "survey", None)
        if well is None:
            return
        uwi = getattr(well, "uwi", "") or ""
        self._title.setText(well.name)
        self._subtitle.setText(f"UWI: {uwi}" if uwi else "")

        from paleo_workbench.project.roles import role_definition

        slots = [
            (role, slot)
            for role, slot in view.slots.items()
            if slot.members or slot.unresolved
        ]
        # Empty roles shown at the end as "missing" rows (data completeness).
        empty = [
            (role, slot) for role, slot in view.slots.items() if not slot.members
        ]
        self._roles_table.setRowCount(len(slots))
        for row, (role, slot) in enumerate(slots):
            display = role_definition(role).display or role
            role_item = QTableWidgetItem(display)
            role_item.setData(Qt.ItemDataRole.UserRole, role)
            self._roles_table.setItem(row, 0, role_item)
            names = "、".join(m.name for m in slot.members[:4])
            if len(slot.members) > 4:
                names += f" …(+{len(slot.members) - 4})"
            self._roles_table.setItem(row, 1, QTableWidgetItem(names))
            primary = slot.primary
            self._roles_table.setItem(
                row, 2, QTableWidgetItem("✓" if primary and primary.is_primary else "")
            )
            self._roles_table.setItem(
                row, 3,
                QTableWidgetItem(
                    (primary.current_version_id or "—") if primary else "—"
                ),
            )
            version_sum = sum(m.version_count for m in slot.members)
            self._roles_table.setItem(row, 4, QTableWidgetItem(str(version_sum)))

        self._fill_list_card(
            self._stale_card.body,
            [
                (
                    f"{item.stage} · {item.version_id}"
                    + (" · pinned" if item.pinned else "")
                )
                for item in (view.stale_items or [])[:8]
            ] or ["无过期成果"],
        )
        self._fill_list_card(
            self._edits_card.body,
            [
                f"{edit.state} · {edit.source_version_id}"
                for edit in (view.uncommitted_edits or [])[:8]
            ] or ["无未提交编辑"],
        )
        missing_lines = [f"角色缺失: {role}" for role, _ in empty if role != "other"]
        missing_lines += [
            f"源文件缺失: {asset_id}"
            for asset_id in (view.missing_source_asset_ids or [])[:4]
        ]
        self._fill_list_card(self._missing_card.body, missing_lines or ["—"])

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_list_card(self, layout, lines: list[str]) -> None:
        self._clear_layout(layout)
        for line in lines:
            label = QLabel(line)
            label.setWordWrap(True)
            layout.addWidget(label)
