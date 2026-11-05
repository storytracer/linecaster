"""``Block``: what every linecaster block has besides its contract.

* ``warm_up()``: load what the block needs before its first unit (an engine, a server, a client's credentials).
  Idempotent; a block without anything to load leaves the default no-op. A block's ``__call__`` (what datatrove's
  executors call) warms it up before its ``run`` starts, timed as its own stat (``warm_up_seconds``, per task) and
  reported to the observers (``on_warm_up(block, seconds)``); an error there fails the task.
"""
from __future__ import annotations

import time

from loguru import logger


class Block:
    """The base of every linecaster block (through ``Contracted``)."""

    #: the observers the builder installed (``linecaster.runtime.observers.Observers``); None: none
    _observers = None

    def warm_up(self) -> None:
        """Load what the block needs before its first unit. Idempotent: a second call does nothing."""

    def __call__(self, data=None, rank: int = 0, world_size: int = 1):
        return _warmed(self, data, rank, world_size)


def warm(block) -> float | None:
    """Warm ``block`` up (``warm_up()``), timed: the seconds as the block's ``warm_up_seconds`` stat and to its
    observers. A block that does not override ``warm_up`` is skipped (``None``). An error is logged and raised: it
    fails the task."""
    fn = getattr(type(block), "warm_up", None)
    if fn is None or fn is Block.warm_up:
        return None
    start = time.perf_counter()
    try:
        block.warm_up()
    except Exception as e:
        logger.error("warm-up of {block} failed: {error_type}: {error}", block=_label(block),
                     error_type=type(e).__name__, error=str(e))
        raise
    seconds = round(time.perf_counter() - start, 4)
    if hasattr(block, "stat_update"):
        block.stat_update("warm_up_seconds", value=seconds, unit="task")
    if block._observers is not None:
        block._observers.on_warm_up(block, seconds)
    return seconds


def _warmed(block, data, rank: int, world_size: int):
    warm(block)
    yield from block.run(data, rank, world_size)


def _label(block) -> str:
    name, cls = getattr(block, "name", None), type(block).__name__
    return cls if not name or name == cls else f"{cls} ({name})"
