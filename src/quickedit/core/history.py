"""Стек операций с отменой и повтором."""

from quickedit.core.operations import Operation


class History:
    def __init__(self) -> None:
        self._done: list[Operation] = []
        self._undone: list[Operation] = []

    @property
    def operations(self) -> tuple[Operation, ...]:
        return tuple(self._done)

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    def push(self, op: Operation) -> None:
        self._done.append(op)
        self._undone.clear()  # новая операция обнуляет стек повтора

    def undo(self) -> Operation | None:
        if not self._done:
            return None
        op = self._done.pop()
        self._undone.append(op)
        return op

    def redo(self) -> Operation | None:
        if not self._undone:
            return None
        op = self._undone.pop()
        self._done.append(op)
        return op

    def __len__(self) -> int:
        return len(self._done)
