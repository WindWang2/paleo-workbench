"""Compact status readout for the unified GIS canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.ui import tokens

__all__ = ["MapStatusBar"]

# 单个读数被布局压缩时的省略宽度上限（完整内容进 tooltip）。
_MAX_LABEL_WIDTH = 168

# 坐标读数的固定小数位数：地理坐标系（度）取 6 位（≈0.1 m），
# 投影坐标系（米等线性单位）取 2 位。pyproj 不可用 / CRS 无法解析时
# 按坐标量级猜测（度域 |v|≤360 取 6 位），保证读数始终定长不漂移。
_GEO_DECIMALS = 6
_PROJECTED_DECIMALS = 2


def _coordinate_decimals(crs: str, point: tuple[float, float] | None) -> int:
    text = str(crs or "").split("/")[0].strip()
    if text:
        try:
            from pyproj import CRS

            if CRS(text).is_geographic:
                return _GEO_DECIMALS
            return _PROJECTED_DECIMALS
        except Exception:
            pass
    if point is not None and abs(point[0]) <= 360.0 and abs(point[1]) <= 90.0:
        return _GEO_DECIMALS
    return _PROJECTED_DECIMALS


def _elide_label(label: QLabel, text: str) -> None:
    """Set ``text`` on ``label``, eliding to the available width.

    状态栏总宽不足以容纳全部读数时 QLabel 只是被裁剪（"CRS: EPS…"），
    这里主动按最大宽度省略并保留完整内容的 tooltip。
    """
    label.setText(text)
    label.setToolTip(text)
    metrics = QFontMetrics(label.font())
    if metrics.horizontalAdvance(text) > _MAX_LABEL_WIDTH:
        label.setText(
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, _MAX_LABEL_WIDTH)
        )


class MapStatusBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapStatusBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_3)
        self.coordinate = QLabel("X: —  Y: —", self)
        self.scale = QLabel("Scale: —", self)
        self.crs = QLabel("CRS: —", self)
        self.render = QLabel("Renderer: —", self)
        self.selection = QLabel("Selection: 0", self)
        self.snapping = QLabel("", self)
        self.edit = QLabel("Read-only", self)
        for label in (self.coordinate, self.scale, self.crs, self.render, self.selection, self.snapping):
            label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; border: none; background: transparent; padding: 0 2px;"
            )
            layout.addWidget(label)
        # Read-only/Editing reads as a compact pill at the row end.
        self.edit.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER_LIGHT}; border-radius: 4px; padding: 1px 8px;"
        )
        layout.addWidget(self.edit)
        layout.addStretch(1)
        self._crs_decimals_key: str | None = None
        self._coord_decimals: int = _PROJECTED_DECIMALS

    def _decimals_for(self, crs: str, point: tuple[float, float] | None) -> int:
        """按 CRS 缓存小数位（鼠标移动每帧调用，避免重复解析 pyproj）。"""
        if crs != self._crs_decimals_key:
            self._coord_decimals = _coordinate_decimals(crs, point)
            self._crs_decimals_key = crs
        return self._coord_decimals

    def update_state(
        self,
        *,
        point: tuple[float, float] | None = None,
        extent: tuple[float, float, float, float] | None = None,
        crs: str = "",
        renderer: str = "",
        selection_count: int = 0,
        editing: bool = False,
        editing_label: str = "",
        snapping: bool | None = None,
    ) -> None:
        if point is not None:
            decimals = self._decimals_for(crs, point)
            _elide_label(
                self.coordinate,
                f"X: {point[0]:.{decimals}f}  Y: {point[1]:.{decimals}f}",
            )
        if extent is not None:
            width = max(0.0, extent[2] - extent[0])
            _elide_label(self.scale, f"Width: {width:.6g}")
        # 描述式 CRS（"EPSG:4326 / WGS84"）取权威代码显示，全名进 tooltip。
        display_crs = str(crs or "unspecified").split("/")[0].strip() or crs
        _elide_label(self.crs, f"CRS: {display_crs}")
        _elide_label(self.render, f"Renderer: {renderer or '—'}")
        self.selection.setText(f"Selection: {int(selection_count)}")
        if snapping is None:
            self.snapping.setText("")
        else:
            self.snapping.setText(f"Snapping: {'ON' if snapping else 'OFF'}")
        self.edit.setText(f"Editing: {editing_label}" if editing and editing_label else ("Editing" if editing else "Read-only"))
        self.edit.setToolTip(
            f"Editing: {editing_label}" if editing and editing_label else ("Editing" if editing else "Read-only")
        )
        self.edit.setStyleSheet(
            f"color: {'#ffffff' if editing else tokens.TEXT_SECONDARY};"
            f" background: {tokens.PRIMARY if editing else tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.PRIMARY if editing else tokens.BORDER_LIGHT};"
            " border-radius: 4px; padding: 1px 8px;"
        )
