from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel


class SequenceFrameworkPage(QWidget):
    """层序格架 page: edit scheme, persist stratigraphy, bind target_horizon downstream."""

    stratigraphy_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceFrameworkPage")
        self._project = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        self.target_panel = SequenceTargetPanel()
        content.addWidget(self.target_panel, 0)

        self.boundary_table = SequenceBoundaryTable()
        content.addWidget(self.boundary_table, 1)

        self.scheme_summary = SequenceSchemeSummary()
        content.addWidget(self.scheme_summary, 0)

        outer.addLayout(content, 1)

        self.target_panel.target_changed.connect(self._on_target_changed)
        self.target_panel.scheme_changed.connect(self._on_scheme_changed)
        self.boundary_table.boundary_activated.connect(self._on_boundary_activated)
        self.scheme_summary.save_requested.connect(self.save_scheme)

    def set_project(self, project) -> None:
        self._project = project

    def update_state(self, stratigraphy) -> None:
        self.target_panel.update_state(stratigraphy)
        self.boundary_table.update_state(stratigraphy)
        self.scheme_summary.update_state(stratigraphy)

    def save_scheme(self) -> bool:
        """Persist current panel values into project.stratigraphy and bind downstream."""
        if self._project is None:
            QMessageBox.warning(self, "层序方案", "未绑定工程，无法保存")
            return False
        from paleo_workbench.workflow.stratigraphy import apply_stratigraphy_scheme

        target = self.target_panel.current_target()
        scheme = self.target_panel.current_scheme()
        if not target:
            QMessageBox.warning(self, "层序方案", "请先选择或输入目标层位")
            return False
        apply_stratigraphy_scheme(
            self._project,
            target_horizon=target,
            systems_tract_scheme=scheme,
            bind_downstream=True,
        )
        self.update_state(self._project.stratigraphy)
        self.scheme_summary.set_bind_status(f"已保存 · 目标 {target}")
        self.stratigraphy_updated.emit()
        return True

    def _on_target_changed(self, target: str) -> None:
        if self._project is None or not target:
            return
        from paleo_workbench.workflow.stratigraphy import apply_stratigraphy_scheme

        apply_stratigraphy_scheme(
            self._project,
            target_horizon=target,
            bind_downstream=True,
        )
        self.boundary_table.update_state(self._project.stratigraphy)
        self.scheme_summary.update_state(self._project.stratigraphy)
        self.scheme_summary.set_bind_status(f"已绑定 · 目标 {target}")
        self.stratigraphy_updated.emit()

    def _on_scheme_changed(self, scheme: str) -> None:
        if self._project is None or not scheme:
            return
        from paleo_workbench.workflow.stratigraphy import apply_stratigraphy_scheme

        apply_stratigraphy_scheme(
            self._project,
            systems_tract_scheme=scheme,
            bind_downstream=False,
        )
        self.scheme_summary.update_state(self._project.stratigraphy)
        self.stratigraphy_updated.emit()

    def _on_boundary_activated(self, boundary: str) -> None:
        if self._project is None:
            return
        from paleo_workbench.workflow.stratigraphy import set_target_from_boundary

        set_target_from_boundary(self._project, boundary, bind_downstream=True)
        self.update_state(self._project.stratigraphy)
        self.scheme_summary.set_bind_status(f"已绑定 · 目标 {boundary}")
        self.stratigraphy_updated.emit()
