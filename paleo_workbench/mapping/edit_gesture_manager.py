"""编辑手势管理器（拓扑编辑迁移 M1 §2 不变式）。

两级撤销的手势级：宿主维护「手势 → 受影响层有序表」——整手势撤销 =
逆序逐层 ``undo()``，重做 = 正序逐层 ``redo()``（层内 = QGIS
undoStack 宏，每层每手势恰一条，由桥侧 begin/endEditCommand 保证）。
手势边界 = 鼠标释放/命令确认（桥侧 edit_gesture 回调）。

手势记录同时是审计源（§2：手势 id、受影响层序列、宏文本）。
纯逻辑模块（无 Qt、无桥）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["EditGestureManager", "GestureRecord"]


@dataclass(frozen=True)
class GestureRecord:
    gesture_id: str
    undo_text: str
    layer_ids: tuple[str, ...]
    undone: bool = False


class EditGestureManager:
    """手势历史与撤销/重做计划（M1 当前层档 = 单层手势；M2 跨层生长）。"""

    def __init__(self) -> None:
        self._gestures: list[GestureRecord] = []
        self._redo_queue: list[str] = []  # 已撤销手势 id，后撤销先重做

    def finish(
        self, gesture_id: str, *, undo_text: str, layer_ids
    ) -> GestureRecord:
        """记录一个完成的手势（层序列保序去重）。"""
        ordered: list[str] = []
        for layer_id in layer_ids:
            layer_id = str(layer_id)
            if layer_id not in ordered:
                ordered.append(layer_id)
        record = GestureRecord(
            str(gesture_id), str(undo_text or ""), tuple(ordered))
        self._gestures.append(record)
        return record

    def _find(self, gesture_id: str) -> GestureRecord | None:
        for record in reversed(self._gestures):
            if record.gesture_id == gesture_id:
                return record
        return None

    def _replace(self, record: GestureRecord) -> None:
        # frozen dataclass：以新记录替换原位（手势量小，线性可接受）。
        for index, existing in enumerate(self._gestures):
            if existing.gesture_id == record.gesture_id:
                self._gestures[index] = record
                return

    def undo_plan(self) -> list[str]:
        """最近未撤销手势的层序列**逆序**（整手势撤销 = 逆序逐层 undo）。"""
        for record in reversed(self._gestures):
            if not record.undone:
                return list(reversed(record.layer_ids))
        return []

    def mark_undone(self, gesture_id: str) -> None:
        record = self._find(gesture_id)
        if record is None or record.undone:
            return
        self._replace(GestureRecord(
            record.gesture_id, record.undo_text, record.layer_ids, undone=True))
        self._redo_queue.append(record.gesture_id)

    def redo_plan(self) -> list[str]:
        """最近已撤销手势的层序列**正序**（重做 = 正序逐层 redo）。"""
        while self._redo_queue:
            record = self._find(self._redo_queue[-1])
            if record is not None and record.undone:
                return list(record.layer_ids)
            self._redo_queue.pop()
        return []

    def mark_redone(self, gesture_id: str) -> None:
        record = self._find(gesture_id)
        if record is None or not record.undone:
            return
        self._replace(GestureRecord(
            record.gesture_id, record.undo_text, record.layer_ids,
            undone=False))
        if gesture_id in self._redo_queue:
            self._redo_queue.remove(gesture_id)

    def current_gesture_id(self) -> str:
        """当前应撤销/重做的手势 id（与 undo/redo_plan 同源；"" = 无）。"""
        for record in reversed(self._gestures):
            if not record.undone:
                return record.gesture_id
        while self._redo_queue:
            record = self._find(self._redo_queue[-1])
            if record is not None and record.undone:
                return record.gesture_id
            self._redo_queue.pop()
        return ""

    def clear(self) -> None:
        """提交/回滚后手势历史作废（QGIS commit 清 undo 栈的同语义）。"""
        self._gestures.clear()
        self._redo_queue.clear()

    def audit_records(self) -> list[dict[str, object]]:
        """手势审计流（§2：手势 id、受影响层序列、宏文本）。"""
        return [
            {
                "gesture_id": record.gesture_id,
                "undo_text": record.undo_text,
                "layer_ids": list(record.layer_ids),
            }
            for record in self._gestures
        ]
