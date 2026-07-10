"""Undo/redo command stack for the mapping editor."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol


class EditCommand(Protocol):
    def do(self) -> None: ...

    def undo(self) -> None: ...


class MoveCommand:
    """Translate one or more features by (dx, dy)."""

    def __init__(
        self,
        feature_ids: Sequence[str],
        dx: float,
        dy: float,
        apply_move: Callable[[str, float, float], None],
    ):
        self.feature_ids = list(feature_ids)
        self.dx = float(dx)
        self.dy = float(dy)
        self.apply_move = apply_move

    def do(self) -> None:
        for fid in self.feature_ids:
            self.apply_move(fid, self.dx, self.dy)

    def undo(self) -> None:
        for fid in self.feature_ids:
            self.apply_move(fid, -self.dx, -self.dy)


class VertexEditCommand:
    """Replace a feature's coordinate ring (set / insert / delete vertex)."""

    def __init__(
        self,
        feature_id: str,
        old_coordinates: Sequence[Sequence[float]],
        new_coordinates: Sequence[Sequence[float]],
        apply_coordinates: Callable[[str, list[list[float]]], None],
    ):
        self.feature_id = str(feature_id)
        self.old_coordinates = [[float(p[0]), float(p[1])] for p in old_coordinates]
        self.new_coordinates = [[float(p[0]), float(p[1])] for p in new_coordinates]
        self.apply_coordinates = apply_coordinates

    def do(self) -> None:
        self.apply_coordinates(
            self.feature_id,
            [list(p) for p in self.new_coordinates],
        )

    def undo(self) -> None:
        self.apply_coordinates(
            self.feature_id,
            [list(p) for p in self.old_coordinates],
        )


class CreateFeatureCommand:
    """Add a feature from a normalized record; undo removes it by id."""

    def __init__(
        self,
        record: dict,
        add_feature: Callable[[dict], None],
        remove_feature: Callable[[str], None],
    ):
        self.record = dict(record)
        self.feature_id = str(record.get("id") or "")
        self.add_feature = add_feature
        self.remove_feature = remove_feature

    def do(self) -> None:
        self.add_feature(self.record)

    def undo(self) -> None:
        self.remove_feature(self.feature_id)


class PropertyChangeCommand:
    """Change a scalar property (name/text) on a feature."""

    def __init__(
        self,
        feature_id: str,
        key: str,
        old_value: object,
        new_value: object,
        apply_property: Callable[[str, str, object], None],
    ):
        self.feature_id = str(feature_id)
        self.key = str(key)
        self.old_value = old_value
        self.new_value = new_value
        self.apply_property = apply_property

    def do(self) -> None:
        self.apply_property(self.feature_id, self.key, self.new_value)

    def undo(self) -> None:
        self.apply_property(self.feature_id, self.key, self.old_value)


class EditCommandStack:
    """Linear undo/redo stack with a maximum depth."""

    def __init__(self, max_depth: int = 50):
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        self.max_depth = int(max_depth)
        self._undo: list[EditCommand] = []
        self._redo: list[EditCommand] = []

    def push(self, command: EditCommand) -> None:
        command.do()
        self._undo.append(command)
        if len(self._undo) > self.max_depth:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.do()
        self._undo.append(command)
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
