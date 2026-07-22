from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.native_backend import native_backend
from paleo_workbench.ui import tokens


def get_engine_status_info() -> tuple[str, str]:
    """Return (badge_text, style_class) for current engine acceleration state."""
    has_cpp = native_backend.has_cpp("seismic_3d") or native_backend.has_cpp("well_log")
    try:
        from PySide6.QtGui import QOpenGLContext
        has_gl = True
    except Exception:
        has_gl = False

    if has_gl and has_cpp:
        return "⚡ GPU: OpenGL + C++", "background-color: #059669; color: #ffffff; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
    elif has_cpp:
        return "💻 CPU: Native C++", "background-color: #2563eb; color: #ffffff; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
    else:
        return "🟡 CPU: Python", "background-color: #d97706; color: #ffffff; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"


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

        # GPU / CPU Engine Backend Badge Indicator
        badge_text, style_sheet = get_engine_status_info()
        self.engine_label = QLabel(badge_text)
        self.engine_label.setStyleSheet(style_sheet)
        self.engine_label.setToolTip("可视化与数据计算引擎状态")
        layout.addWidget(self.engine_label)

    def update_engine_status(self, engine_name: str | None = None) -> None:
        """Update displayed engine acceleration badge."""
        if engine_name:
            self.engine_label.setText(engine_name)
        else:
            badge_text, style_sheet = get_engine_status_info()
            self.engine_label.setText(badge_text)
            self.engine_label.setStyleSheet(style_sheet)

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
