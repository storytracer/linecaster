"""``Block``: what every linecaster block has besides its contract.

* ``warm_up()``: load what the block needs before its first unit (an engine, a server, a client's credentials).
  Idempotent; a block without anything to load leaves the default no-op. A block's ``__call__`` (what datatrove's
  executors call) warms it up before its ``run`` starts, timed as its own stat (``warm_up_seconds``, per task) and
  reported to the observers (``on_warm_up(block, seconds)``); an error there fails the task.
* ``to_dict()``: the block as it was built, ``{"block", "class", "params"}``: the constructor's parameters with
  their values (given or default; ``**kwargs`` flattened), JSON-compatible (``plain``): nested blocks and backends as
  their own dicts, secrets as ``{"env": NAME}``, folders as paths, callables as ``module:name``. The arguments are
  kept when the block is constructed; ``live_params`` names parameters read from the same-named attribute instead,
  for blocks the builder adjusts after construction (a reader's ``provides``).
* ``operational``: the parameters that change only where things are or how the work is run, not what a run writes
  (``OPERATIONAL`` plus a class's own); the run record's ``pipeline_sha256`` leaves them out
  (``linecaster.runtime.provenance``, ``docs/reference/pipelines.md``).
"""
from __future__ import annotations

import functools
import inspect
import time
from pathlib import PurePath
from typing import Any

from loguru import logger

#: parameters that change where things are read and written, how the work is spread and paced, or how a server is
#: reached, never what a run writes for a page or an item; ``pipeline_sha256`` leaves them out
OPERATIONAL = frozenset({
    # where: folders, files, names
    "name", "data_folder", "output_folder", "output_filename", "folder", "image_folder", "manifest_folder",
    "ocr_folder", "suffix", "bucket_by_item", "prefix",
    # which input files a task reads, and how (the pages themselves are recorded per page)
    "paths_file", "glob_pattern", "recursive", "limit", "skip", "shuffle_files", "file_progress", "doc_progress",
    "batch_size", "prefetch", "http", "uri_map",
    # servers and clients: how they are started and reached
    "port", "host", "python", "boot_timeout", "max_queue", "script", "vllm", "outside_venv", "prepare_workers",
    "gpu_memory_utilization", "extra_args",
    # writers' file handling
    "compression", "max_file_size",
})


def _qualified(obj) -> str:
    return f"{obj.__module__}:{obj.__qualname__}"


def plain(value: Any) -> Any:
    """``value`` as JSON-compatible data for ``to_dict()``: objects with a ``to_dict()`` (blocks, backends, chat
    adapters, secrets) as their dict, folders as their path, parts as ``transcription:name``, sets sorted, callables
    and classes as ``module:name``, anything else as text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict) and not isinstance(value, type):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(v) for v in value), key=str)
    if isinstance(value, PurePath):
        return value.as_posix()
    from .contract import Part

    if isinstance(value, Part):
        return str(value)
    if hasattr(value, "fs") and hasattr(value, "path"):         # a datatrove DataFolder
        protocol = value.fs.protocol if isinstance(value.fs.protocol, str) else value.fs.protocol[0]
        return value.path if protocol in ("file", "local") else value.fs.unstrip_protocol(value.path)
    if inspect.isfunction(value) or inspect.isclass(value) or inspect.isbuiltin(value):
        return _qualified(value)
    return str(value)


def _capturing(init):
    """``init`` that keeps its call's arguments (with defaults) as ``self._init_args``: only the outermost call
    of a construction, so a subclass's parameters win over those it passes to its base."""
    sig = inspect.signature(init)

    @functools.wraps(init)
    def wrapped(self, *args, **kwargs):
        if "_init_args" not in self.__dict__:
            try:
                bound = sig.bind(self, *args, **kwargs)
            except TypeError:           # the call itself is wrong: let ``init`` say so
                return init(self, *args, **kwargs)
            bound.apply_defaults()
            given: dict[str, Any] = {}
            for name, value in list(bound.arguments.items())[1:]:
                kind = sig.parameters[name].kind
                if kind is inspect.Parameter.VAR_KEYWORD:
                    given.update(value)
                elif kind is inspect.Parameter.VAR_POSITIONAL:
                    given[name] = list(value)
                else:
                    given[name] = value
            self.__dict__["_init_args"] = given
        return init(self, *args, **kwargs)

    wrapped._captures = True
    return wrapped


class Block:
    """The base of every linecaster block (through ``Contracted``) and of composites."""

    #: the observers the builder installed (``linecaster.runtime.observers.Observers``); None: none
    _observers = None
    #: parameters ``to_dict()`` reads from the same-named attribute (the builder may change them after construction)
    live_params: tuple[str, ...] = ()
    #: this class's operational parameters besides ``OPERATIONAL``
    operational: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        init = cls.__dict__.get("__init__")
        if init is not None and not getattr(init, "_captures", False):
            cls.__init__ = _capturing(init)

    def warm_up(self) -> None:
        """Load what the block needs before its first unit. Idempotent: a second call does nothing."""

    def __call__(self, data=None, rank: int = 0, world_size: int = 1):
        return _warmed(self, data, rank, world_size)

    def init_params(self) -> dict[str, Any]:
        """The constructor's parameters with the values this block was built with (``live_params`` as they are
        now)."""
        out = dict(self.__dict__.get("_init_args") or {})
        for name in self.live_params:
            if hasattr(self, name):
                out[name] = getattr(self, name)
        return out

    def to_dict(self) -> dict[str, Any]:
        """``{"block": class name, "class": "module:Class", "params": {...}}``, JSON-compatible."""
        return {"block": type(self).__name__, "class": _qualified(type(self)), "params": plain(self.init_params())}

    @classmethod
    def operational_params(cls) -> frozenset[str]:
        """``OPERATIONAL`` and the ``operational`` of this class and its bases."""
        own = {p for c in cls.__mro__ for p in getattr(c, "operational", ())}
        return OPERATIONAL | own


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
