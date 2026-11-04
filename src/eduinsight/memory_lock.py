"""Process-wide serialization of Lite-Mem access.

Lite-Mem shares one SQLite connection per ``Memory``. FastAPI runs sync
handlers in a thread pool, so concurrent requests race on that connection's
cursor (intermittent IndexError / "recursive cursor" errors → 500). Every
Lite-Mem call therefore goes through ``MEMORY_LOCK``.

``LockedMemory`` wraps the application ``Memory`` so each method call — and
each call on its internal ``_store`` — runs under the lock. Only the Lite-Mem
call itself is locked; callers keep LLM requests outside of these calls.
"""

from __future__ import annotations

import functools
import threading
from typing import Any

MEMORY_LOCK = threading.RLock()

# Attributes whose values are themselves stateful objects sharing the connection.
_PROXIED_ATTRS = frozenset({"_store"})


def serialized(func):
    """Run ``func`` while holding ``MEMORY_LOCK`` (reentrant)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with MEMORY_LOCK:
            return func(*args, **kwargs)

    return wrapper


class LockedMemory:
    """Transparent proxy that serializes every call on a Lite-Mem object."""

    __slots__ = ("_target",)

    def __init__(self, target: Any) -> None:
        if isinstance(target, LockedMemory):
            target = target._target
        object.__setattr__(self, "_target", target)

    @property
    def unwrapped(self) -> Any:
        return self._target

    def __getattr__(self, name: str) -> Any:
        with MEMORY_LOCK:
            value = getattr(self._target, name)
        if name in _PROXIED_ATTRS:
            return LockedMemory(value)
        if callable(value):
            return serialized(value)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        with MEMORY_LOCK:
            setattr(self._target, name, value)

    def __repr__(self) -> str:
        return f"LockedMemory({self._target!r})"


def locked(memory: Any) -> LockedMemory:
    return LockedMemory(memory)
