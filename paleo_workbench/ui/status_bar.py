from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.ui import tokens


class StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self._project_name = "未命名工程"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        layout.setSpacing(tokens.SPACE_2)
        self.status_label = QLabel(f"就绪 · {self._project_name}")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.coord_label = QLabel("")
        self.coord_label.setObjectName("StatusCoordLabel")
        self.coord_label.hide()
        layout.addWidget(self.coord_label)

    def set_project_name(self, name: str) -> None:
        self._project_name = name
        self.status_label.setText(f"就绪 · {name}")

    def update_context(self, *, coords: str = "", horizon: str = "", crs: str = "", scale: str = "") -> None:
        """Update contextual status segments. Empty values hide the segment.

        ``coords``/``crs`` are inserted verbatim; ``horizon`` is prefixed with
        ``层位: `` and ``scale`` with ``1:``. Segments join with ``·``.
        """
        parts: list[str] = []
        if coords:
            parts.append(coords)
        if horizon:
            parts.append(f"层位: {horizon}")
        if crs:
            parts.append(crs)
        if scale:
            parts.append(f"1:{scale}")
        if parts:
            self.coord_label.setText("  ·  ".join(parts))
            self.coord_label.show()
        else:
            self.coord_label.setText("")
            self.coord_label.hide()
