# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""A dependency-free observer primitive.

The document model must stay usable (and testable) without Qt, so it cannot use
``QtCore.Signal``.  :class:`Event` is the minimal replacement: connect callables,
emit positional arguments, and never let one broken listener break the others.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable, Iterator, MutableSequence
from typing import Any

log = logging.getLogger(__name__)

Listener = Callable[..., Any]


class Event:
    """A tiny multicast callback holder.

    Bound methods are held weakly so a listener that is garbage collected (a
    closed panel, a discarded item) does not keep its owner alive, and does not
    need to remember to disconnect.
    """

    __slots__ = ("_name", "_strong", "_weak")

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._strong: MutableSequence[Listener] = []
        self._weak: MutableSequence[weakref.WeakMethod] = []

    # -- subscription ----------------------------------------------------
    def connect(self, listener: Listener) -> Listener:
        """Register *listener*.  Returns it, so it can be used as a decorator."""
        ref = _weak_method(listener)
        if ref is not None:
            self._weak.append(ref)
        else:
            self._strong.append(listener)
        return listener

    def disconnect(self, listener: Listener) -> None:
        ref = _weak_method(listener)
        if ref is not None:
            self._weak = [r for r in self._weak if r() is not None and r() != listener]
        else:
            self._strong = [f for f in self._strong if f is not listener]

    def clear(self) -> None:
        self._strong.clear()
        self._weak.clear()

    # -- emission --------------------------------------------------------
    def emit(self, *args: Any, **kwargs: Any) -> None:
        for listener in self._live():
            try:
                listener(*args, **kwargs)
            except Exception:  # a listener must never break the model
                log.exception("Error in listener of event %r", self._name)

    __call__ = emit

    def _live(self) -> Iterator[Listener]:
        alive: list[weakref.WeakMethod] = []
        for ref in self._weak:
            method = ref()
            if method is not None:
                alive.append(ref)
        self._weak = alive
        yield from list(self._strong)
        for ref in alive:
            method = ref()
            if method is not None:
                yield method

    def __len__(self) -> int:
        return len(self._strong) + len(self._weak)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Event {self._name!r} listeners={len(self)}>"


def _weak_method(listener: Listener) -> weakref.WeakMethod | None:
    if hasattr(listener, "__self__") and hasattr(listener, "__func__"):
        try:
            return weakref.WeakMethod(listener)  # type: ignore[arg-type]
        except TypeError:
            return None
    return None


class Blocker:
    """Context manager that suppresses re-entrant updates.

    Used by panels that write to the model and also listen to it, to avoid a
    feedback loop between "user edited a spin box" and "model changed".
    """

    __slots__ = ("_depth",)

    def __init__(self) -> None:
        self._depth = 0

    def __bool__(self) -> bool:
        return self._depth > 0

    def __enter__(self) -> Blocker:
        self._depth += 1
        return self

    def __exit__(self, *exc: object) -> bool:
        self._depth -= 1
        return False
