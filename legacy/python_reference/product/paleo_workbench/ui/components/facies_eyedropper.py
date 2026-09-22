"""相带吸色管（M2）——点击地图既有相带，一键吸取属性/颜色/花纹。

数据路径双栈一致（00-decisions D10）：拾取一律走 Python 权威
（``CompositeEditController.identify_all`` 或等价 identify 回调），按
返回序取第一个携带相带属性的命中（identify_all 已按图层栈序返回，
顶层优先）；未命中如实返回 None——不猜、不弹窗。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, Signal

from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy


def pick_facies_at(
    point: tuple[float, float],
    identify: Callable[[tuple[float, float]], Iterable[dict]],
) -> dict | None:
    """地图点 → 相带拾取结果（无相带命中返回 None）。

    返回 dict：facies/sub_facies/micro_facies/level + 来源（layer_id/
    feature_id）+ 分类渲颜色 color + 花纹 pattern（无映射为 None）。
    """
    from paleo_workbench.ui.components.facies_palette_widget import facies_color
    from paleo_workbench.mapping.facies_patterns import pattern_id_for_facies

    for hit in identify(point) or ():
        attributes = dict(hit.get("attributes") or {})
        facies = str(attributes.get("facies") or "").strip()
        if not facies:
            continue  # 非相带要素/图层：跳过取下一命中
        selection = {
            "facies": facies,
            "sub_facies": str(attributes.get("sub_facies") or ""),
            "micro_facies": str(attributes.get("micro_facies") or ""),
        }
        return {
            **selection,
            "level": FaciesTaxonomy.selection_level(selection),
            "layer_id": str(hit.get("layer_id") or ""),
            "feature_id": str(hit.get("feature_id") or ""),
            "layer_name": str(hit.get("layer_name") or ""),
            "color": facies_color(facies),
            "pattern": pattern_id_for_facies(facies),
        }
    return None


class FaciesEyedropper(QObject):
    """吸色管会话状态（激活/点击/装备转发）。

    纯协调器：不拥有画布或工具状态；点击事件由宿主（CompositeDocument）
    在激活期路由到 :meth:`handle_click`。``identify`` 注入返回
    identify_all 形状的结果列表。
    """

    picked = Signal(dict)
    pick_missed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._identify: Callable[[tuple[float, float]], list[dict]] | None = None

    @property
    def active(self) -> bool:
        return self._active

    def bind(self, identify: Callable[[tuple[float, float]], list[dict]]) -> None:
        self._identify = identify

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

    def handle_click(self, point: tuple[float, float]) -> bool:
        """处理一次地图点击；命中装备（picked），空击保持原装备（missed）。"""
        if not self._active or self._identify is None:
            return False
        result = pick_facies_at(point, self._identify)
        if result is None:
            self.pick_missed.emit()
            return False
        self.picked.emit(result)
        return True
