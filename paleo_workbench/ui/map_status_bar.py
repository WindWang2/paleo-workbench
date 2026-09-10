"""Compact status readout for the unified GIS canvas.

V10（Goal §14–§17）：状态条是空间上下文与编辑会话的**持久**呈现面——
编辑目标/dirty、捕捉/拓扑（含错误计数）、CRS（含不一致警示）、比例尺、
选择计数一眼可读；细节（容差/模式/推荐）进 tooltip。全部事实经
``apply_context`` 由宿主从 canonical ``ToolContext`` 投影，本组件零业务
判断（呈现词表在此，判词不在此）。

V10 review 修正（R3/R4/R5）：

* **轻路径**：``update_coordinate``/``update_scale`` 只动单个读数（指针/
  extent 高频事件不重建全量事实、不重解析样式）；
* **chip 状态完备**：编辑 chip 覆盖 gate-closed（锁定+原因，判词来自
  宿主门禁）与保存受阻（dirty+拓扑错误）；样式只在状态迁移时重设；
* **主题响应**：chip 样式经 ``style.bind`` 重取 token（深色/高对比不再
  残留浅色 chip）；
* **溢出收敛**：窄宽下按优先级隐藏低价值读数（渲染器→测距→拓扑→捕捉），
  编辑 chip 永不隐藏；
* **可达性**：拓扑问题 chip 与捕捉读数可点击（左键），信号进宿主；
  双信号（文字/glyph + 颜色）不只靠颜色。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.ui import style, tokens

__all__ = ["MapStatusBar"]

# 单个读数被布局压缩时的省略宽度上限（完整内容进 tooltip）。
_MAX_LABEL_WIDTH = 168

# 坐标读数的固定小数位数：地理坐标系（度）取 6 位（≈0.1 m），
# 投影坐标系（米等线性单位）取 2 位。pyproj 不可用 / CRS 无法解析时
# 按坐标量级猜测（度域 |v|≤360 取 6 位），保证读数始终定长不漂移。
_GEO_DECIMALS = 6
_PROJECTED_DECIMALS = 2

# 窄宽溢出的隐藏优先序（先隐藏低价值读数；编辑 chip 与坐标/比例尺/CRS
# 永不隐藏）。
_COLLAPSE_PRIORITY = ("render", "measure", "topology", "snapping")


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


def _format_scale(denominator: float) -> str:
    """比例尺读数：1:N（千分位分隔）；0/未知/<1 → 诚实未知，不伪造精度。"""
    if denominator and denominator >= 1.0:
        return f"1:{int(round(denominator)):,}"
    return "1:—"


def _chip_qss(*, emphasis: bool = False, warning: bool = False) -> str:
    """状态 chip 的 QSS（读当前主题 token——经 style.bind 每次重求值）。"""
    palette = style.palette()
    if warning:
        return (
            f"color: {palette['TEXT_PRIMARY']}; background: {palette['BG_SEARCH']};"
            f" border: 1px solid {palette['WARNING']}; border-radius: 4px;"
            " padding: 1px 8px; font-weight: 600;"
        )
    if emphasis:
        return (
            f"color: {palette['ON_PRIMARY']}; background: {palette['PRIMARY']};"
            f" border: 1px solid {palette['PRIMARY']}; border-radius: 4px;"
            " padding: 1px 8px;"
        )
    return (
        f"color: {palette['TEXT_SECONDARY']}; background: {palette['BG_SEARCH']};"
        f" border: 1px solid {palette['BORDER_LIGHT']}; border-radius: 4px;"
        " padding: 1px 8px;"
    )


# chip 呈现模式（状态迁移时才重设样式，避免逐事件重解析 QSS）。
_CHIP_EMPHASIS = "emphasis"
_CHIP_WARNING = "warning"
_CHIP_NEUTRAL = "neutral"


class MapStatusBar(QFrame):
    """地图状态条：坐标 / 比例尺 / CRS / 选择 / 捕捉 / 拓扑 / 编辑 chip。

    信号（宿主接配置/验证路径）：

    * ``topology_activated`` — 拓扑问题 chip 的点击（进入验证/定位）；
    * ``snapping_activated`` — 捕捉读数的点击（打开捕捉设置）。
    """

    topology_activated = Signal()
    snapping_activated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapStatusBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_3)
        self.coordinate = QLabel("X: —  Y: —", self)
        self.scale = QLabel("1:—", self)
        self.crs = QLabel("CRS: —", self)
        self.render = QLabel("渲染器: —", self)
        self.selection = QLabel("已选 0", self)
        self.snapping = QLabel("", self)
        self.topology = QLabel("", self)
        self.measure = QLabel("", self)
        self._labels = {
            "render": self.render,
            "measure": self.measure,
            "topology": self.topology,
            "snapping": self.snapping,
        }
        for label in (
            self.coordinate, self.scale, self.crs, self.render,
            self.selection, self.snapping, self.topology, self.measure,
        ):
            label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; border: none; background: transparent; padding: 0 2px;"
            )
            layout.addWidget(label)
        # 捕捉读数可点击（QGIS 状态条磁铁惯例；工具提示注明）。
        self.snapping.setCursor(Qt.CursorShape.PointingHandCursor)
        # 拓扑问题 chip（V10 §15）：错误计数 > 0 才出现；点击进验证/定位。
        self.topology_issue = QLabel("", self)
        self.topology_issue.setObjectName("MapStatusBarTopologyIssue")
        self.topology_issue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topology_issue.hide()
        layout.addWidget(self.topology_issue)
        # 编辑会话 chip：编辑 层名 ● 未保存 / RAW · 只读 / 已冻结 / 锁定。
        self.edit = QLabel("查看", self)
        layout.addWidget(self.edit)
        layout.addStretch(1)
        self._crs_decimals_key: str | None = None
        self._coord_decimals: int = _PROJECTED_DECIMALS
        # 样式迁移缓存（避免逐事件重解析 QSS）。
        self._edit_chip_mode: str | None = None
        self._issue_visible = False
        self._crs_warning = False
        self._collapsed: set[str] = set()
        # 主题响应：chip 样式经 bind 在 theme_changed 时重取 token。
        style.bind(self.edit, lambda: self._render_edit_chip())
        style.bind(self.topology_issue, lambda: self._render_issue_chip())
        # 可点击读数命中缓存（mouseReleaseEvent 用）。
        self._press_inside: str | None = None

    def _decimals_for(self, crs: str, point: tuple[float, float] | None) -> int:
        """按 CRS 缓存小数位（鼠标移动每帧调用，避免重复解析 pyproj）。"""
        if crs != self._crs_decimals_key:
            self._coord_decimals = _coordinate_decimals(crs, point)
            self._crs_decimals_key = crs
        return self._coord_decimals

    # -- 高频轻路径（R5：指针/extent 事件不重建全量事实） -----------------------

    def update_coordinate(self, point: tuple[float, float], crs: str = "") -> None:
        """指针移动：只更新坐标读数（样式/其他读数不动）。"""
        decimals = self._decimals_for(crs, point)
        _elide_label(
            self.coordinate,
            f"X: {point[0]:.{decimals}f}  Y: {point[1]:.{decimals}f}",
        )

    def update_scale(self, denominator: float) -> None:
        """视野变化：只更新比例尺读数。"""
        _elide_label(self.scale, _format_scale(float(denominator or 0.0)))

    def set_measure(self, text: str) -> None:
        """V7 原生测距显示（空串清除）。独立于 update_state：测距事件以指针
        频率到达，不与状态刷新耦合。"""
        _elide_label(self.measure, text)
        self.measure.setToolTip(text)

    # -- V10 兼容入口（legacy 编图页） ------------------------------------------

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
        scale_denominator: float = 0.0,
    ) -> None:
        """legacy 页面关键字子集入口；工作站主路径 = ``apply_context``。"""
        if point is not None:
            decimals = self._decimals_for(crs, point)
            _elide_label(
                self.coordinate,
                f"X: {point[0]:.{decimals}f}  Y: {point[1]:.{decimals}f}",
            )
        if scale_denominator and scale_denominator > 0.0:
            _elide_label(self.scale, _format_scale(scale_denominator))
        elif extent is not None:
            width = max(0.0, extent[2] - extent[0])
            _elide_label(self.scale, f"宽: {width:.6g}")
        display_crs = str(crs or "unspecified").split("/")[0].strip() or crs
        _elide_label(self.crs, f"CRS: {display_crs}")
        _elide_label(self.render, f"渲染器: {renderer or '—'}")
        self.selection.setText(f"已选 {int(selection_count)}")
        if snapping is None:
            self.snapping.setText("")
        else:
            self.snapping.setText(f"捕捉: {'开' if snapping else '关'}")
        self._apply_edit_chip(
            editing=editing,
            editing_label=editing_label,
            dirty=False,
            raw_locked=False,
            frozen=False,
            gate_closed=False,
            gate_reason="",
            editable_unknown=False,
            save_blocked=False,
        )

    # -- 编辑 chip（§14 会话状态一眼可读，不只靠颜色） ---------------------------

    def _apply_edit_chip(
        self,
        *,
        editing: bool,
        editing_label: str,
        dirty: bool,
        raw_locked: bool,
        frozen: bool,
        gate_closed: bool,
        gate_reason: str,
        editable_unknown: bool,
        save_blocked: bool,
    ) -> None:
        """编辑 chip 词表（V10 §14）：查看/编辑/dirty/RAW/冻结/锁定。"""
        if editing:
            # dirty/保存受阻以文字符号「●」传达（不只靠颜色——无障碍）。
            text = "编辑"
            tip = "编辑会话进行中"
            if editing_label:
                text = f"编辑 {editing_label}"
                tip = f"正在编辑：{editing_label}"
            if dirty:
                text = f"{text} ● 未保存"
                tip += "（有未保存修改）"
            if save_blocked:
                text = f"{text}（保存受阻）"
                tip += "；存在拓扑错误，保存将被校验阻断"
            mode = _CHIP_EMPHASIS
        elif raw_locked:
            text = "RAW · 只读"
            tip = "RAW/模型结果图层——不可直接编辑；复制为草稿后编辑"
            mode = _CHIP_NEUTRAL
        elif frozen:
            text = "已冻结"
            tip = "当前结果已冻结/发布——不可编辑；另存草稿或解除冻结"
            mode = _CHIP_NEUTRAL
        elif gate_closed:
            text = "锁定"
            tip = f"图层被编辑门禁锁定：{gate_reason}" if gate_reason else "图层被编辑门禁锁定"
            mode = _CHIP_NEUTRAL
        elif editable_unknown:
            text = "可编辑性未知"
            tip = "当前图层可编辑性未知（阶段/门禁状态未就绪）"
            mode = _CHIP_NEUTRAL
        elif editing_label:
            text = f"{editing_label} · 可编辑"
            tip = f"{editing_label}：可编辑（未开启会话）"
            mode = _CHIP_NEUTRAL
        else:
            text = "查看"
            tip = "未开启编辑会话"
            mode = _CHIP_NEUTRAL
        self.edit.setText(text)
        self.edit.setToolTip(tip)
        if mode != self._edit_chip_mode:
            self._edit_chip_mode = mode
            style.refresh(self.edit)

    def _render_edit_chip(self) -> str:
        mode = self._edit_chip_mode or _CHIP_NEUTRAL
        return _chip_qss(
            emphasis=mode == _CHIP_EMPHASIS,
            warning=mode == _CHIP_WARNING,
        )

    def _render_issue_chip(self) -> str:
        return _chip_qss(warning=True)

    # -- V10：canonical 事实投影（宿主从 ToolContext 派生） -------------------

    def apply_context(self, facts: dict) -> None:
        """以 canonical ToolContext 投影更新全部读数（V10 主入口）。

        ``facts`` 键（全部可选，缺省保持现状）：``point`` / ``crs`` /
        ``renderer`` / ``scale_denominator`` / ``selection_count`` /
        ``snapping_enabled`` / ``snapping_tolerance_px``（有效容差——
        per-layer 覆盖优先） / ``snapping_modes`` /
        ``snapping_reference_count`` / ``snapping_role_recommended`` /
        ``snapping_available`` / ``topology_enabled`` /
        ``topology_error_count`` / ``crs_mismatch`` / ``layer_crs`` /
        ``editing`` / ``dirty`` / ``layer_name`` / ``raw_locked`` /
        ``layer_frozen`` / ``edit_gate_open`` / ``edit_gate_reason`` /
        ``save_blocked``。本组件只呈现，不判定。
        """
        point = facts.get("point")
        crs = str(facts.get("crs") or "")
        if point is not None:
            decimals = self._decimals_for(crs, point)
            _elide_label(
                self.coordinate,
                f"X: {point[0]:.{decimals}f}  Y: {point[1]:.{decimals}f}",
            )
        # CRS 读数（§16）：声明 auth id / 「未声明」；不一致时加 ⚠ 文字
        # 警示（非仅颜色）并提示图层 CRS。
        display_crs = crs.split("/")[0].strip() if crs else ""
        crs_text = f"CRS: {display_crs}" if display_crs else "CRS: 未声明"
        mismatch = facts.get("crs_mismatch")
        layer_crs = str(facts.get("layer_crs") or "").split("/")[0].strip()
        warning = bool(mismatch and layer_crs)
        if warning:
            crs_text = f"⚠ {crs_text}"
            crs_tip = (
                f"{crs_text}\n图层 CRS（{layer_crs}）与工程 CRS 不一致——"
                "数字化几何将按工程 CRS 落地，注意坐标单位")
        else:
            crs_tip = crs_text if not crs else f"{crs_text}\n工程坐标系（声明值）"
        _elide_label(self.crs, crs_text)
        self.crs.setToolTip(crs_tip)
        if warning != self._crs_warning:
            self._crs_warning = warning
            self.crs.setStyleSheet(
                (f"color: {tokens.TEXT_PRIMARY}; border: none;"
                 " background: transparent; padding: 0 2px; font-weight: 600;")
                if warning else
                (f"color: {tokens.TEXT_SECONDARY}; border: none;"
                 " background: transparent; padding: 0 2px;")
            )
        _elide_label(self.scale, _format_scale(float(facts.get("scale_denominator") or 0.0)))
        _elide_label(self.render, f"渲染器: {facts.get('renderer') or '—'}")
        self.selection.setText(f"已选 {int(facts.get('selection_count') or 0)}")

        # 捕捉读数（§15）：ON/OFF + tooltip 详情（容差/模式/参与引用/推荐）。
        snapping_enabled = facts.get("snapping_enabled")
        if snapping_enabled is None:
            self.snapping.setText("")
            self.snapping.setToolTip("")
        else:
            self.snapping.setText(f"捕捉: {'开' if snapping_enabled else '关'}")
            tip_lines = ["点击打开捕捉设置"]
            if snapping_enabled:
                tolerance = float(facts.get("snapping_tolerance_px") or 0.0)
                if tolerance > 0.0:
                    tip_lines.append(f"有效容差 {tolerance:g} px（含图层覆盖）")
                modes = tuple(facts.get("snapping_modes") or ())
                if modes:
                    tip_lines.append("模式：" + "、".join(modes))
                references = int(facts.get("snapping_reference_count") or 0)
                if references > 0:
                    tip_lines.append(f"参与捕捉的引用图层 {references} 个（不含编辑层）")
                recommended = facts.get("snapping_role_recommended")
                if recommended is True:
                    tip_lines.append("当前配置 = 角色推荐")
                elif recommended is False:
                    tip_lines.append("用户自定义（与角色推荐不同）")
            if not facts.get("snapping_available", True):
                tip_lines.append("当前环境的捕捉引擎不可用")
            self.snapping.setToolTip("捕捉设置\n" + "\n".join(tip_lines))

        # 拓扑读数（§15）：开关态；错误计数 > 0 → 问题 chip（可点击）。
        topology_enabled = facts.get("topology_enabled")
        if topology_enabled is None:
            self.topology.setText("")
            self.topology.setToolTip("")
        else:
            self.topology.setText(f"拓扑: {'开' if topology_enabled else '关'}")
            self.topology.setToolTip("拓扑编辑：共享节点传播 + 保存编辑时执行拓扑校验")
        errors = int(facts.get("topology_error_count") or 0)
        visible = errors > 0
        if visible:
            self.topology_issue.setText(f"⚠ 拓扑: {errors} 个问题")
            self.topology_issue.setToolTip(
                f"当前编辑会话存在 {errors} 个拓扑错误\n点击查看/定位问题（合并等操作被阻断）")
        if visible != self._issue_visible:
            self._issue_visible = visible
            self.topology_issue.setVisible(visible)
            if visible:
                style.refresh(self.topology_issue)

        self._apply_edit_chip(
            editing=bool(facts.get("editing")),
            editing_label=str(facts.get("layer_name") or ""),
            dirty=bool(facts.get("dirty")),
            raw_locked=bool(facts.get("raw_locked")),
            frozen=bool(facts.get("layer_frozen")),
            gate_closed=facts.get("edit_gate_open") is False,
            gate_reason=str(facts.get("edit_gate_reason") or ""),
            editable_unknown=facts.get("edit_gate_open") is None,
            save_blocked=bool(facts.get("save_blocked")),
        )
        self._apply_collapse()

    # -- 窄宽收敛（R3-1：1366 不溢出；按优先级隐藏，编辑 chip 永存） ------------

    def _apply_collapse(self) -> None:
        """宽度不足时按优先序隐藏低价值读数（渲染器→测距→拓扑→捕捉）。"""
        available = self.width()
        if available <= 0:
            return
        fixed_hint = sum(
            max(label.sizeHint().width(), 24)
            for label in (self.coordinate, self.scale, self.crs,
                          self.selection, self.edit, self.topology_issue)
            if label.isVisible() or label is self.edit
        )
        budget = available - fixed_hint - 4 * tokens.SPACE_3
        collapsed: set[str] = set()
        flexible = [
            name for name in ("snapping", "topology", "measure", "render")
            if self._labels[name].text()
        ]
        # 低优先者先隐藏（_COLLAPSE_PRIORITY 序）。
        for name in _COLLAPSE_PRIORITY:
            if budget < 0 and name in flexible:
                collapsed.add(name)
                budget += max(self._labels[name].sizeHint().width(), 24)
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            for name, label in self._labels.items():
                label.setHidden(name in collapsed)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        super().resizeEvent(event)
        self._apply_collapse()

    # -- 可点击读数（左键 + 按下起点在内——拒绝拖过误触） -----------------------

    def _hit_clickable(self, pos) -> str | None:
        for name, label in (
            ("topology_issue", self.topology_issue),
            ("snapping", self.snapping),
        ):
            if label.isVisible() and label.geometry().contains(pos):
                return name
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        self._press_inside = self._hit_clickable(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        inside = self._hit_clickable(event.position().toPoint())
        pressed = self._press_inside
        self._press_inside = None
        if (
            inside is not None and inside == pressed
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if inside == "topology_issue":
                self.topology_activated.emit()
            elif inside == "snapping":
                self.snapping_activated.emit()
            return
        super().mouseReleaseEvent(event)
