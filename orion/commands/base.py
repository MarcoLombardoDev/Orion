"""The Command interface every reversible edit implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

__all__ = ["Command", "MacroCommand", "NullCommand"]


class Command(ABC):
    """A single reversible edit.

    ``execute`` must be idempotent in the sense that calling it after ``undo``
    reproduces exactly the same state — that is what makes redo correct.
    """

    #: Shown in the Undo/Redo menu items, e.g. "Undo Move Object".
    text: str = "Edit"

    @abstractmethod
    def execute(self) -> None:
        """Apply the change."""

    @abstractmethod
    def undo(self) -> None:
        """Reverse the change."""

    def redo(self) -> None:
        """Re-apply the change.  Defaults to :meth:`execute`."""
        self.execute()

    def merge_with(self, other: "Command") -> bool:
        """Absorb *other* if the two form one logical edit.

        Returning ``True`` means *other* has been folded into ``self`` and must
        not be pushed separately — this is what turns a drag of a hundred mouse
        moves into a single undo step.
        """
        return False

    @property
    def is_significant(self) -> bool:
        """``False`` for commands that should not mark the document modified."""
        return True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.text!r}>"


class NullCommand(Command):
    """A command that does nothing; useful as a neutral element."""

    text = "No change"

    def execute(self) -> None:
        return None

    def undo(self) -> None:
        return None

    @property
    def is_significant(self) -> bool:
        return False


class MacroCommand(Command):
    """Several commands treated as one undo step."""

    def __init__(self, commands: Sequence[Command], text: str = "Edit") -> None:
        self._commands = list(commands)
        self.text = text

    def execute(self) -> None:
        done: list[Command] = []
        try:
            for command in self._commands:
                command.execute()
                done.append(command)
        except Exception:
            # Roll back the part that succeeded so the model is never left
            # halfway through a compound edit.
            for command in reversed(done):
                try:
                    command.undo()
                except Exception:  # pragma: no cover - defensive
                    pass
            raise

    def undo(self) -> None:
        for command in reversed(self._commands):
            command.undo()

    def __len__(self) -> int:
        return len(self._commands)

    @property
    def is_significant(self) -> bool:
        return any(command.is_significant for command in self._commands)
