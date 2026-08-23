from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QTabWidget

from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_factor_shelf import MapFactorShelf
from paleo_workbench.ui.pages.map_topology_issue_panel import MapTopologyIssuePanel

_ICONS_DIR = Path(__file__).parent.parent.parent / "ui" / "assets" / "icons" / "map"


def _panel_icon(name: str) -> QIcon:
    path = _ICONS_DIR / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


class MapWorkbenchBottom(QTabWidget):
    """Collapsible bottom work area for properties, topology, and factor maps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.attribute_table = MapAttributeTable()
        self.topology_panel = MapTopologyIssuePanel()
        self.factor_shelf = MapFactorShelf()
        self.addTab(self.attribute_table, _panel_icon("tab-attribute"), "属性")
        self.addTab(self.topology_panel, _panel_icon("tab-topology"), "拓扑问题")
        self.addTab(self.factor_shelf, _panel_icon("tab-factor"), "单因素参考图")

    def set_feature(self, feature: dict | None) -> None:
        self.attribute_table.set_feature(feature)

    def set_collapsed(self, collapsed: bool) -> None:
        self.setVisible(not collapsed)
