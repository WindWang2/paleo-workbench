"""Compact status readout for the unified GIS canvas.

V10（Goal §14–§17）：状态条是空间上下文与编辑会话的**持久**呈现面——
编辑目标/dirty、捕捉/拓扑（含错误计数）、CRS（含不一致警示）、比例尺、
选择计数一眼可读；细节（容差/模式/推荐）进 tooltip。全部事实经
``apply_context`` 由宿主从 canonical ``ToolContext`` 投影，本组件零业务
判断（呈现词表在此，判词不在此）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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


def _format_scale(denominator: float) -> str:
    """比例尺读数：1:N（千分位分隔）；0/未知 → 诚实未知，不伪造精度。"""
    if denominator and denominator > 0.0:
        return f"1:{int(round(denominator)):,}"
    return "1:—"


def _chip_style(*, emphasis: bool = False, warning: bool = False) -> str:
    """状态 chip 的双信号样式（形状/文字 + 颜色；不只靠颜色传达）。"""
    if warning:
        return (
            f"color: {tokens.TEXT_PRIMARY}; background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.WARNING}; border-radius: 4px;"
            " padding: 1px 8px; font-weight: 600;"
        )
    if emphasis:
        return (
            f"color: {'#ffffff'}; background: {tokens.PRIMARY};"
            f" border: 1px solid {tokens.PRIMARY}; border-radius: 4px;"
            " padding: 1px 8px;"
        )
    return (
        f"color: {tokens.TEXT_SECONDARY}; background: {tokens.BG_SEARCH};"
        f" border: 1px solid {tokens.BORDER_LIGHT}; border-radius: 4px;"
        " padding: 1px 8px;"
    )


class MapStatusBar(QFrame):
    """地图状态条：坐标 / 比例尺 / CRS / 选择 / 捕捉 / 拓扑 / 编辑 chip。

    ``topology_activated`` — 拓扑问题 chip 的点击信号（宿主接验证/定位
    路径）；无问题时不显示 chip，无假可点目标。
    """

    topology_activated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapStatusBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_3)
        self.coordinate = QLabel("X: —  Y: —", self)
        self.scale = QLabel("1:—", self)
        self.crs = QLabel("CRS: —", self)
        self.render = QLabel("Renderer: —", self)
        self.selection = QLabel("已选 0", self)
        self.snapping = QLabel("", self)
        self.topology = QLabel("", self)
        self.measure = QLabel("", self)
        for label in (
            self.coordinate, self.scale, self.crs, self.render,
            self.selection, self.snapping, self.topology, self.measure,
        ):
            label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; border: none; background: transparent; padding: 0 2px;"
            )
            layout.addWidget(label)
        # 拓扑问题 chip（V10 §15）：错误计数 > 0 才出现；点击进验证/定位。
        self.topology_issue = QLabel("", self)
        self.topology_issue.setObjectName("MapStatusBarTopologyIssue")
        self.topology_issue.setStyleSheet(_chip_style(warning=True))
        self.topology_issue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topology_issue.hide()
        layout.addWidget(self.topology_issue)
        # 编辑会话 chip：[Edit] LayerName ● modified / RAW · 只读 / 已冻结。
        self.edit = QLabel("查看", self)
        self.edit.setStyleSheet(_chip_style())
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

    def set_measure(self, text: str) -> None:
        """V7 原生测距显示（空串清除）。独立于 update_state：测距事件以指针
        频率到达，不与状态刷新耦合。"""
        _elide_label(self.measure, text)
        self.measure.setToolTip(text)

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
        """V10 兼容入口：legacy 页面仍用关键字子集；新事实经 ``apply_context``。"""
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
            _elide_label(self.scale, f"Width: {width:.6g}")
        # 描述式 CRS（"EPSG:4326 / WGS84"）取权威代码显示，全名进 tooltip。
        display_crs = str(crs or "unspecified").split("/")[0].strip() or crs
        _elide_label(self.crs, f"CRS: {display_crs}")
        _elide_label(self.render, f"Renderer: {renderer or '—'}")
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
            editable_unknown=False,
        )

    # -- V10：编辑 chip（§14 会话状态一眼可读，不只靠颜色） -------------------

    def _apply_edit_chip(
        self,
        *,
        editing: bool,
        editing_label: str,
        dirty: bool,
        raw_locked: bool,
        frozen: bool,
        editable_unknown: bool,
    ) -> None:
        """编辑 chip 词表（V10 §14）：Viewing / Editing / Dirty / RAW / Frozen。"""
        if editing:
            # dirty 以文字符号「● 未保存」传达（不只靠颜色——无障碍）。
            text = "Edit"
            tip = "编辑会话进行中"
            if editing_label:
                text = f"Edit {editing_label}"
                tip = f"正在编辑：{editing_label}"
            if dirty:
                text = f"{text} ● 未保存"
                tip += "（有未保存修改）"
            self.edit.setText(text)
            self.edit.setToolTip(tip)
            self.edit.setStyleSheet(_chip_style(emphasis=True))
        elif raw_locked:
            self.edit.setText("RAW · 只读")
            self.edit.setToolTip("RAW/模型结果图层——不可直接编辑；复制为草稿后编辑")
            self.edit.setStyleSheet(_chip_style())
        elif frozen:
            self.edit.setText("已冻结")
            self.edit.setToolTip("当前结果已冻结/发布——不可编辑；另存草稿或解除冻结")
            self.edit.setStyleSheet(_chip_style())
        elif editable_unknown:
            self.edit.setText("可编辑性未知")
            self.edit.setToolTip("当前图层可编辑性未知（阶段/门禁状态未就绪）")
            self.edit.setStyleSheet(_chip_style())
        elif editing_label:
            self.edit.setText(f"{editing_label} · 可编辑")
            self.edit.setToolTip(f"{editing_label}：可编辑（未开启会话）")
            self.edit.setStyleSheet(_chip_style())
        else:
            self.edit.setText("查看")
            self.edit.setToolTip("未开启编辑会话")
            self.edit.setStyleSheet(_chip_style())

    # -- V10：canonical 事实投影（宿主从 ToolContext 派生） -------------------

    def apply_context(self, facts: dict) -> None:
        """以 canonical ToolContext 投影更新全部读数（V10 主入口）。

        ``facts`` 键（全部可选，缺省保持现状）：``point`` / ``crs`` /
        ``renderer`` / ``scale_denominator`` / ``selection_count`` /
        ``snapping_enabled`` / ``snapping_tolerance_px`` / ``snapping_modes`` /
        ``snapping_reference_count`` / ``snapping_role_recommended`` /
        ``snapping_available`` / ``topology_enabled`` /
        ``topology_error_count`` / ``crs_mismatch`` / ``layer_crs`` /
        ``editing`` / ``dirty`` / ``layer_name`` / ``raw_locked`` /
        ``layer_frozen`` / ``edit_gate_open`` / ``edit_gate_reason``。
        本组件只呈现，不判定。
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
        if mismatch and layer_crs:
            crs_text = f"⚠ {crs_text}"
            crs_tip = (
                f"{crs_text}\n图层 CRS（{layer_crs}）与工程 CRS 不一致——"
                "数字化几何将按工程 CRS 落地，注意坐标单位")
            self.crs.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; border: none;"
                " background: transparent; padding: 0 2px; font-weight: 600;"
            )
        else:
            crs_tip = crs_text if not crs else f"{crs_text}\n工程坐标系（声明值）"
            self.crs.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; border: none;"
                " background: transparent; padding: 0 2px;"
            )
        _elide_label(self.crs, crs_text)
        self.crs.setToolTip(crs_tip)
        _elide_label(self.scale, _format_scale(float(facts.get("scale_denominator") or 0.0)))
        _elide_label(self.render, f"Renderer: {facts.get('renderer') or '—'}")
        self.selection.setText(f"已选 {int(facts.get('selection_count') or 0)}")

        # 捕捉读数（§15）：ON/OFF + tooltip 详情（容差/模式/参与引用/推荐）。
        snapping_enabled = facts.get("snapping_enabled")
        if snapping_enabled is None:
            self.snapping.setText("")
            self.snapping.setToolTip("")
        else:
            self.snapping.setText(f"捕捉: {'开' if snapping_enabled else '关'}")
            tip_lines = []
            if snapping_enabled:
                tolerance = float(facts.get("snapping_tolerance_px") or 0.0)
                if tolerance > 0.0:
                    tip_lines.append(f"容差 {tolerance:g} px")
                modes = tuple(facts.get("snapping_modes") or ())
                if modes:
                    tip_lines.append("模式：" + "、".join(modes))
                references = int(facts.get("snapping_reference_count") or 0)
                if references > 0:
                    tip_lines.append(f"参与捕捉引用层 {references} 个")
                recommended = facts.get("snapping_role_recommended")
                if recommended is True:
                    tip_lines.append("当前配置 = 角色推荐")
                elif recommended is False:
                    tip_lines.append("当前配置为用户自定义（与角色推荐不同）")
            if not facts.get("snapping_available", True):
                tip_lines.append("当前环境的捕捉引擎不可用")
            self.snapping.setToolTip("捕捉设置\n" + "\n".join(tip_lines) if tip_lines else "捕捉设置")

        # 拓扑读数（§15）：开关态；错误计数 > 0 → 问题 chip（可点击）。
        topology_enabled = facts.get("topology_enabled")
        if topology_enabled is None:
            self.topology.setText("")
            self.topology.setToolTip("")
        else:
            self.topology.setText(f"拓扑: {'开' if topology_enabled else '关'}")
            self.topology.setToolTip("拓扑编辑（保存编辑时执行拓扑校验）")
        errors = int(facts.get("topology_error_count") or 0)
        if errors > 0:
            self.topology_issue.setText(f"⚠ 拓扑: {errors} 个问题")
            self.topology_issue.setToolTip(
                f"当前编辑会话存在 {errors} 个拓扑错误\n点击查看/定位问题（合并等操作被阻断）")
            self.topology_issue.show()
        else:
            self.topology_issue.hide()

        self._apply_edit_chip(
            editing=bool(facts.get("editing")),
            editing_label=str(facts.get("layer_name") or ""),
            dirty=bool(facts.get("dirty")),
            raw_locked=bool(facts.get("raw_locked")),
            frozen=bool(facts.get("layer_frozen")),
            editable_unknown=facts.get("edit_gate_open") is None,
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        """拓扑问题 chip 的点击区域（QLabel 无 clicked；chip 命中才发信号）。"""
        if self.topology_issue.isVisible() and (
            self.topology_issue.geometry().contains(event.position().toPoint())
        ):
            self.topology_activated.emit()
            return
        super().mouseReleaseEvent(event)
