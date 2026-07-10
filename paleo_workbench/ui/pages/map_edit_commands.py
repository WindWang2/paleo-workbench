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
