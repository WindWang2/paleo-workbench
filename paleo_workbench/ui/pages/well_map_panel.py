"""数据页内嵌的井位地图折叠面板。

The standalone 井位地图 page was absorbed into the Data page: this panel
hosts :class:`ProjectWellMapPage` (unchanged) under the asset table, with
a checkable header that folds the map away when vertical space is needed.
The same points also persist into the project as a dedicated vector map
document — see ``paleo_workbench.project.well_location_map``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from paleo_workbench.ui.pages.project_well_map_page import ProjectWellMapPage

_ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"


def _icon(name: str) -> QIcon:
    path = _ICONS_DIR / name
    return QIcon(str(path)) if path.exists() else QIcon()


class WellMapPanel(QFrame):
    """Collapsible section: header strip + embedded well-location map."""

    def __init__(self, parent=None, *, map_page: ProjectWellMapPage | None = None):
        super().__init__(parent)
        self.setObjectName("WellMapPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("WellMapPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 2, 8, 2)
        header_layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("WellMapPanelToggle")
        self.toggle_button.setText("井位地图")
        self.toggle_button.setIcon(_icon("map/panel-bottom.svg"))
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setCheckable(True)
        self.toggle_button.toggled.connect(self._on_toggled)

        self.count_label = QLabel()
        self.count_label.setObjectName("WellMapPanelCount")

        header_layout.addWidget(self.toggle_button)
        header_layout.addStretch(1)
        header_layout.addWidget(self.count_label)

        self._header = header
        self.map_page = map_page or ProjectWellMapPage()

        layout.addWidget(header)
        layout.addWidget(self.map_page, 1)

        # setChecked(False) on an already-unchecked button emits nothing, so
        # sync the initial collapsed state explicitly.
        self.set_collapsed(True)
        self._on_toggled(self.toggle_button.isChecked())

    def _on_toggled(self, checked: bool) -> None:
        self.map_page.setVisible(checked)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def set_collapsed(self, collapsed: bool) -> None:
        self.toggle_button.setChecked(not collapsed)

    def is_collapsed(self) -> bool:
        return not self.toggle_button.isChecked()

    def set_header_visible(self, visible: bool) -> None:
        """Hide the fold header while the map is a page's main content."""
        self._header.setVisible(visible)

    def expand_and_focus(self, well_id: str) -> None:
        """Tree/table → map: unfold the panel and center on the well."""
        self.set_collapsed(False)
        self.map_page.focus_well(well_id)

    def refresh_domain(self, project: Any) -> None:
        """Push the current document into the map (signature-gated, cheap)."""
        try:
            self.map_page.refresh_domain(project)
        except Exception:
            pass
        wells = getattr(project, "wells", None) or []
        reference_count = sum(
            1 for well in wells if getattr(well, "spatial_scope", "workarea") == "reference"
        )
        workarea_count = len(wells) - reference_count
        if reference_count:
            self.count_label.setText(f"{workarea_count} 口测区井 · {reference_count} 口参考井")
        else:
            self.count_label.setText(f"{workarea_count} 口井" if workarea_count else "")
