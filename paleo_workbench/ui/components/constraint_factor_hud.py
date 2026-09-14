"""单因素约束悬浮 HUD（M3）——光标处单因素读值 + 连井剖面联动发布。

预算契约（00-decisions D7）：
- 值计算 O(1)：网格双线性采样 + 局部梯度 + 线性最近井（井 ≤ 数千）；
- 刷新 60ms 合并节流（QTimer 单实例，只保留最新光标点——高频抖动不放大）；
- HUD 是画布的 **子控件**（非 topLevel）、鼠标穿透、行控件一次性创建
  （长时高频移动零控件分配）；
- 缺数据字段显示 `—`（诚实降级，不猜值）。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Sequence

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

#: 光标→HUD 刷新合并窗口（ms）。
REFRESH_INTERVAL_MS = 60
#: 离开井位容差后的延迟清除（ms，防闪烁）。
CLEAR_DELAY_MS = 300
#: HUD 行定义（key, 显示名）。
HUD_ROWS: tuple[tuple[str, str], ...] = (
    ("sand_ratio", "砂地比"),
    ("slope", "坡度"),
    ("nearest_well", "最近井"),
    ("confidence", "预测置信度"),
)

_MISSING = "—"


# ---------------------------------------------------------------------------
# O(1) 采样纯函数（Qt-free；网格对象鸭子类型 FactorGridResult）
# ---------------------------------------------------------------------------

def _axis_locate(axis: np.ndarray, value: float) -> int | None:
    """单调查中一维轴 → 左侧索引；越界/空轴返回 None。支持升/降序。"""
    if axis is None or axis.size < 2:
        return None
    ascending = bool(axis[-1] > axis[0])
    probe = axis if ascending else axis[::-1]
    target = value if ascending else value
    if target < probe[0] or target > probe[-1]:
        return None
    index = int(np.searchsorted(probe, target, side="right")) - 1
    index = max(0, min(index, probe.size - 2))
    return index if ascending else probe.size - 2 - index


def bilinear_sample(grid: Any, x: float, y: float) -> float | None:
    """网格双线性采样；最近单元无数据（NaN）或出界返回 None（不外推）。"""
    if grid is None:
        return None
    try:
        col = _axis_locate(np.asarray(grid.grid_x), float(x))
        row = _axis_locate(np.asarray(grid.grid_y), float(y))
        if col is None or row is None:
            return None
        z = np.asarray(grid.grid_z)
        x0, x1 = float(grid.grid_x[col]), float(grid.grid_x[col + 1])
        y0, y1 = float(grid.grid_y[row]), float(grid.grid_y[row + 1])
        tx = 0.0 if x1 == x0 else (float(x) - x0) / (x1 - x0)
        ty = 0.0 if y1 == y0 else (float(y) - y0) / (y1 - y0)
        # 点所落的最近单元为 NaN → 无数据（半 NaN 邻域的插值见下方权重回退）。
        nearest = z[int(row + (1 if ty > 0.5 else 0)),
                    int(col + (1 if tx > 0.5 else 0))]
        if bool(np.isnan(nearest)):
            return None
        z00, z10 = z[row, col], z[row, col + 1]
        z01, z11 = z[row + 1, col], z[row + 1, col + 1]
        top = z00 if np.isnan(z10) else (z10 if np.isnan(z00)
                                         else z00 * (1 - tx) + z10 * tx)
        bottom = z01 if np.isnan(z11) else (z11 if np.isnan(z01)
                                            else z01 * (1 - tx) + z11 * tx)
        if np.isnan(top) and np.isnan(bottom):
            return None
        value = top if np.isnan(bottom) else (bottom if np.isnan(top)
                                              else top * (1 - ty) + bottom * ty)
        return None if np.isnan(value) else float(value)
    except (IndexError, ValueError, TypeError):
        return None


def local_slope_degrees(grid: Any, x: float, y: float) -> float | None:
    """局部坡度（度）：中心差分梯度的模 → atan。任一方向无数据返回 None。"""
    if grid is None:
        return None
    grid_x = np.asarray(grid.grid_x)
    grid_y = np.asarray(grid.grid_y)
    if grid_x.size < 2 or grid_y.size < 2:
        return None
    dx = abs(float(grid_x[1]) - float(grid_x[0]))
    dy = abs(float(grid_y[1]) - float(grid_y[0]))
    if dx <= 0 or dy <= 0:
        return None
    # 步长向网格范围内钳制（边缘/角点用变间距中心差分，不越界外推）。
    east_x = min(float(x) + dx, float(grid_x[-1]))
    west_x = max(float(x) - dx, float(grid_x[0]))
    north_y = min(float(y) + dy, float(grid_y[-1]))
    south_y = max(float(y) - dy, float(grid_y[0]))
    east = bilinear_sample(grid, east_x, y)
    west = bilinear_sample(grid, west_x, y)
    north = bilinear_sample(grid, x, north_y)
    south = bilinear_sample(grid, x, south_y)
    if any(v is None for v in (east, west, north, south)):
        return None
    dz_dx = (east - west) / max(east_x - west_x, 1e-12)
    dz_dy = (north - south) / max(north_y - south_y, 1e-12)
    return math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))


def confidence_from_variance(grid: Any, x: float, y: float) -> float | None:
    """克里金方差 → 置信度：``1 / (1 + σ/σ_z)``（σ_z=网格值标准差，尺度无关）。

    无方差网格（如 IDW 结果）返回 None——不虚构置信度。
    """
    if grid is None or getattr(grid, "variance_grid", None) is None:
        return None
    try:
        col = _axis_locate(np.asarray(grid.grid_x), float(x))
        row = _axis_locate(np.asarray(grid.grid_y), float(y))
        if col is None or row is None:
            return None
        variance = float(np.asarray(grid.variance_grid)[row, col])
        if math.isnan(variance):
            return None
        sigma_ref = float(np.nanstd(np.asarray(grid.grid_z)))
        if sigma_ref <= 0:
            return None
        sigma = math.sqrt(max(variance, 0.0))
        return 1.0 / (1.0 + sigma / sigma_ref)
    except (IndexError, ValueError, TypeError):
        return None


def nearest_well(
    wells: Sequence[Any], x: float, y: float, max_distance: float
) -> tuple[str, float] | None:
    """线性最近井（D7：井 ≤ 数千 O(n) 可接受）；超容差返回 None。"""
    best: tuple[str, float] | None = None
    for well in wells or ():
        wx = getattr(well, "project_x", None)
        wy = getattr(well, "project_y", None)
        if wx is None or wy is None:
            wx, wy = getattr(well, "surface_x", None), getattr(well, "surface_y", None)
        if wx is None or wy is None:
            wx, wy = getattr(well, "x", None), getattr(well, "y", None)
        if wx is None or wy is None:
            continue
        distance = math.hypot(float(wx) - float(x), float(wy) - float(y))
        if distance > float(max_distance):
            continue
        if best is None or distance < best[1]:
            best = (str(getattr(well, "name", "")), distance)
    return best


# ---------------------------------------------------------------------------
# HUD 部件（画布子控件，鼠标穿透，行控件一次性创建）
# ---------------------------------------------------------------------------

class ConstraintFactorHud(QWidget):
    """右上角浮动只读条：砂地比 / 坡度 / 最近井 / 预测置信度。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConstraintFactorHud")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        self._value_labels: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(HUD_ROWS):
            name_label = QLabel(label, self)
            name_label.setObjectName(f"ConstraintHudRow_{key}")
            value_label = QLabel(_MISSING, self)
            value_label.setObjectName(f"ConstraintHudValue_{key}")
            layout.addWidget(name_label, row, 0)
            layout.addWidget(value_label, row, 1)
            self._value_labels[key] = value_label
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return super().eventFilter(obj, event)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        self.move(max(8, parent.width() - self.width() - 12), 12)

    def apply_values(self, values: dict[str, Any]) -> None:
        """批量更新读值；缺项/None/空串一律显示 `—`（诚实降级）。"""
        for key, label in self._value_labels.items():
            value = values.get(key)
            text = _MISSING if value in (None, "") else str(value)
            if label.text() != text:
                label.setText(text)

    def value_of(self, key: str) -> str:
        return self._value_labels[key].text()


# ---------------------------------------------------------------------------
# 控制器：60ms 合并节流 + 连井联动发布（echo 断路 / 延迟清除）
# ---------------------------------------------------------------------------

class HudController(QObject):
    """光标→HUD 值计算与剖面联动发布（纯协调器；数据经注入 provider）。"""

    SOURCE_TAG = "mapping_cursor"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hud: ConstraintFactorHud | None = None
        self._factor_grid_provider: Callable[[], Any] | None = None
        self._wells_provider: Callable[[], Sequence[Any]] | None = None
        self._view_coordination: Any = None
        self._section_well_radius = 50.0
        self._pending: tuple[float, float] | None = None
        self._last_well = ""
        self._clear_scheduled = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(CLEAR_DELAY_MS)
        self._clear_timer.timeout.connect(self._publish_clear)

    def bind(
        self,
        *,
        hud: ConstraintFactorHud,
        factor_grid_provider: Callable[[], Any],
        wells_provider: Callable[[], Sequence[Any]],
        view_coordination: Any = None,
        section_well_radius: float = 50.0,
    ) -> None:
        self._hud = hud
        self._factor_grid_provider = factor_grid_provider
        self._wells_provider = wells_provider
        self._view_coordination = view_coordination
        self._section_well_radius = float(section_well_radius)

    def set_view_coordination(self, view_coordination: Any) -> None:
        self._view_coordination = view_coordination

    def handle_position(self, x: float, y: float) -> None:
        """高频光标入口：只保留最新点；定时器活跃期不重启（合并节流）。"""
        self._pending = (float(x), float(y))
        if not self._timer.isActive():
            self._timer.start()

    # -- 刷新 -----------------------------------------------------------------

    def _refresh(self) -> None:
        point = self._pending
        if point is None or self._hud is None:
            return
        x, y = point
        values: dict[str, Any] = {}
        grid = (
            self._factor_grid_provider() if self._factor_grid_provider else None
        )
        if grid is not None:
            unit = str(getattr(grid, "unit", "") or "")
            sand = bilinear_sample(grid, x, y)
            if sand is not None:
                values["sand_ratio"] = (
                    f"{sand:.1f}%" if unit == "%" else f"{sand:.2f}")
            slope = local_slope_degrees(grid, x, y)
            if slope is not None:
                values["slope"] = f"{slope:.2f}°"
            confidence = confidence_from_variance(grid, x, y)
            if confidence is not None:
                values["confidence"] = f"{confidence:.2f}"
        wells = self._wells_provider() if self._wells_provider else []
        nearest = nearest_well(wells, x, y, self._section_well_radius)
        if nearest is not None:
            # 相别分歧需井-层位解释数据在场；缺省诚实显示 —（D7/04 #10）。
            values["nearest_well"] = f"{nearest[0]}（相别 —）"
        self._hud.apply_values(values)
        self._route_section_link(nearest[0] if nearest is not None else "")

    def _route_section_link(self, well_name: str) -> None:
        if well_name:
            if self._clear_scheduled:
                self._clear_timer.stop()  # 回到容差内：撤销挂起的清除
                self._clear_scheduled = False
            if well_name != self._last_well:
                self._publish(well_name)
                self._last_well = well_name
            return
        if self._last_well and not self._clear_scheduled:
            self._clear_timer.start()
            self._clear_scheduled = True

    def _publish_clear(self) -> None:
        self._clear_scheduled = False
        if self._last_well:
            self._publish("")
            self._last_well = ""

    def _publish(self, well_name: str) -> None:
        publisher = getattr(self._view_coordination, "publish_section_cursor",
                            None)
        if callable(publisher):
            publisher(well_name, source=self.SOURCE_TAG)
