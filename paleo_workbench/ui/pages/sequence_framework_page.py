from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QSplitter, QToolButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.dock_manager import dock_manager
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.panel_float_controller import FloatController
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel
from paleo_workbench.workflow.stratigraphy import (
    apply_stratigraphy_scheme,
    set_target_from_boundary,
)

# QWIDGETSIZE_MAX: lifts a side panel's setFixedWidth upper bound (the
# designed width stays as the minimum) so the splitter handle can resize it.
_PANEL_MAX_WIDTH = 16_777_215

#: Delay before a splitter drag is persisted (avoid a QSettings sync per tick).
_DOCKED_SIZES_DELAY_MS = 400


class PanelFloatButton(QToolButton):
    """Corner button floating one side panel via a FloatController.

    Docked side of the FloatingPanel ⇲ dock-back chrome: pinned to the
    panel's top-right corner through an event filter and hidden while the
    panel is afloat (the floating window carries its own dock-back button).
    """

    def __init__(self, key: str, panel: QWidget, controller: FloatController):
        super().__init__(panel)
        self._key = key
        self._panel = panel
        self._controller = controller
        self.setObjectName("PanelFloatButton")
        self.setText("⇱")
        self.setToolTip("浮动面板 (Float panel)")
        self.setFixedSize(18, 18)
        self.clicked.connect(lambda: self._controller.toggle(self._key))
        panel.installEventFilter(self)
        controller.float_changed.connect(self._on_float_changed)
        self._reposition()

    def _reposition(self) -> None:
        self.move(self._panel.width() - self.width() - 4, 2)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if obj is self._panel and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _on_float_changed(self, key: str, floating: bool) -> None:
        if key == self._key:
            self.setVisible(not floating)


class SequenceFrameworkPage(QWidget):
    """层序格架 page: edit scheme, persist stratigraphy, bind target_horizon downstream."""

    stratigraphy_updated = Signal()

    def __init__(self, parent=None, *, persistence: LayoutPersistence | None = None):
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

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("SequenceFrameworkSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.target_panel = SequenceTargetPanel()
        # 目标 | 层序界面表 | 方案: the boundary table stays the stretchy
        # center; target + summary are resizable side panels.
        self.target_panel.setMaximumWidth(_PANEL_MAX_WIDTH)
        self.content_splitter.addWidget(self.target_panel)

        self.boundary_table = SequenceBoundaryTable()
        self.content_splitter.addWidget(self.boundary_table)

        self.scheme_summary = SequenceSchemeSummary()
        self.scheme_summary.setMaximumWidth(_PANEL_MAX_WIDTH)
        self.content_splitter.addWidget(self.scheme_summary)

        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 0)
        self.content_splitter.setSizes([280, 900, 260])

        outer.addWidget(self.content_splitter, 1)

        # M6: target/scheme side panels float through the shared
        # FloatController; the boundary table stays the docked center.
        self._float_persistence = (
            persistence if persistence is not None else LayoutPersistence()
        )
        self._floatable: dict[str, QWidget] = {}
        self.float_controller = FloatController(
            resolver=self._floatable.get,
            persistence=self._float_persistence,
            parent=self,
        )
        self._make_floatable("sequence:target", self.target_panel, "层序目标")
        self._make_floatable("sequence:scheme", self.scheme_summary, "层序方案")
        self._float_sizes_timer = QTimer(self)
        self._float_sizes_timer.setSingleShot(True)
        self._float_sizes_timer.setInterval(_DOCKED_SIZES_DELAY_MS)
        self._float_sizes_timer.timeout.connect(self._persist_docked_sizes)
        self.content_splitter.splitterMoved.connect(self._on_splitter_moved)
        for key in self._floatable:
            self.float_controller.restore_saved(key)

        self.target_panel.target_changed.connect(self._on_target_changed)
        self.target_panel.scheme_changed.connect(self._on_scheme_changed)
        self.boundary_table.boundary_activated.connect(self._on_boundary_activated)
        self.scheme_summary.save_requested.connect(self.save_scheme)

    def _make_floatable(self, key: str, panel: QWidget, title: str) -> None:
        """Register a side panel for float/dock and give it a float button."""
        dock_manager.register_panel(key, title)
        self._floatable[key] = panel
        PanelFloatButton(key, panel, self.float_controller)

    def _on_splitter_moved(self, *_pos: int) -> None:
        self._float_sizes_timer.start()

    def _persist_docked_sizes(self) -> None:
        """Persist the splitter distribution for every docked side panel."""
        sizes = list(self.content_splitter.sizes())
        for key, panel in self._floatable.items():
            if panel.parentWidget() is self.content_splitter:
                self._float_persistence.save_docked_sizes(key, sizes)

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
        set_target_from_boundary(self._project, boundary, bind_downstream=True)
        self.update_state(self._project.stratigraphy)
        self.scheme_summary.set_bind_status(f"已绑定 · 目标 {boundary}")
        self.stratigraphy_updated.emit()
