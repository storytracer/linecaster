"""Observers: callbacks at block boundaries, for taps (``--tap-after``), and later tracing, sampling, progress.

An ``Observer`` gets, per task:

* ``on_task_start(rank, world_size)`` before the first page;
* ``on_warm_up(block, seconds)`` when a block that loads something (an engine, a server) is warmed up, before its
  first page (``linecaster.blocks.base.block.warm``; blocks warm up as the stream reaches them, the last one first);
* ``on_enter(block, doc)`` when a page goes into a block, ``on_exit(block, doc, error=None)`` when it comes out
  (``error``: what the block recorded in ``doc.metadata["errors"]`` on the way, if anything);
* ``on_unit(block, doc, event, **attributes)`` from inside a stream block (``PageBlock.notify``): ``prepare`` when
  it starts building its request for the page and ``request`` when the request is built (both in one of saturate's
  prepare threads, so observers must be thread-safe there; ``request`` carries a ``carrier`` dict an observer may
  put a ``traceparent`` into, which the block sends with the request), ``done`` when its result came back (with
  ``error``, and the tokens and ``finish_reason`` when there are any); a block that sends one request per region
  adds ``region``;
* ``on_task_event(block, event, start_ns, end_ns, **attributes)`` for work of the task that is no page's
  (``Block.report``): ``file`` when a reader is through a file (``file``, ``pages``, ``seconds_own``: the time spent
  reading it, without the time its pages spent downstream), ``flush`` when a writer closed its files;
* ``on_leave(doc)`` when a page comes out of the stage's last block;
* ``on_task_end(error=None)`` after the last page, also when the task fails (``error``: the exception).

``environment()`` gives the variables a server started in the task gets (``ModelServer``, ``ChatModelServer``):
the tracing observer names the file the server writes its spans to.

The builder (``linecaster.runtime.builder``) installs them: one ``Observers`` hub per stage, shared by the
``Boundary`` steps it puts after every block. The boundary after block *i* calls ``on_exit(i)`` and ``on_enter(i +
1)`` for each page, so a block's time per page includes the time a page waits in a served window. Boundary steps
are plain callables, not datatrove steps: they add no stats. A pipeline without observers gets no boundaries.
"""
from __future__ import annotations


class Observer:
    """The hooks, all no-ops; observers override what they need."""

    def on_task_start(self, rank: int, world_size: int) -> None:
        pass

    def on_warm_up(self, block, seconds: float) -> None:
        pass

    def on_enter(self, block, doc) -> None:
        pass

    def on_exit(self, block, doc, error=None) -> None:
        pass

    def on_unit(self, block, doc, event: str, **attributes) -> None:
        pass

    def on_task_event(self, block, event: str, start_ns: int, end_ns: int, **attributes) -> None:
        pass

    def on_leave(self, doc) -> None:
        pass

    def on_task_end(self, error: BaseException | None = None) -> None:
        pass

    def environment(self) -> dict[str, str]:
        return {}


class Observers(Observer):
    """The observers of one stage, called in order. Started once per task (whichever boundary runs first), ended
    by the last boundary."""

    def __init__(self, observers: list[Observer]):
        self.observers = list(observers)
        self._started = False
        self._errors: dict[int, int] = {}       # id(doc) -> errors recorded when it entered the current block

    def __bool__(self) -> bool:
        return bool(self.observers)

    def on_task_start(self, rank: int, world_size: int) -> None:
        if self._started:
            return
        self._started = True
        for o in self.observers:
            o.on_task_start(rank, world_size)

    def on_warm_up(self, block, seconds: float) -> None:
        for o in self.observers:
            o.on_warm_up(block, seconds)

    def on_enter(self, block, doc) -> None:
        self._errors[id(doc)] = len(doc.metadata.get("errors") or ())
        for o in self.observers:
            o.on_enter(block, doc)

    def on_exit(self, block, doc, error=None) -> None:
        if error is None:
            errors = doc.metadata.get("errors") or ()
            if len(errors) > self._errors.pop(id(doc), 0):
                error = errors[-1]
        for o in self.observers:
            o.on_exit(block, doc, error)

    def on_unit(self, block, doc, event: str, **attributes) -> None:
        for o in self.observers:
            o.on_unit(block, doc, event, **attributes)

    def on_task_event(self, block, event: str, start_ns: int, end_ns: int, **attributes) -> None:
        for o in self.observers:
            o.on_task_event(block, event, start_ns, end_ns, **attributes)

    def on_leave(self, doc) -> None:
        for o in self.observers:
            o.on_leave(doc)

    def on_task_end(self, error: BaseException | None = None) -> None:
        if not self._started:
            return
        self._started = False
        self._errors.clear()
        for o in self.observers:
            o.on_task_end(error)

    def environment(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for o in self.observers:
            out.update(o.environment())
        return out


class Boundary:
    """The step after ``block`` in a pipeline: for every document ``on_exit(block)``, then ``on_enter(after)``
    (``after`` is the next block; after the last, ``on_leave``). ``last`` ends the task's observers when the stream is
    through, or when it fails (with the error). A callable with datatrove's step signature, without stats."""

    def __init__(self, hub: Observers, block, after=None, last: bool = False):
        self.hub, self.block, self.after, self.last = hub, block, after, last

    def __call__(self, data, rank: int = 0, world_size: int = 1):
        self.hub.on_task_start(rank, world_size)
        error = None
        try:
            for doc in data:
                self.hub.on_exit(self.block, doc)
                if self.after is not None:
                    self.hub.on_enter(self.after, doc)
                else:
                    self.hub.on_leave(doc)
                yield doc
        except GeneratorExit:
            raise
        except BaseException as e:
            error = e
            raise
        finally:
            if self.last:
                self.hub.on_task_end(error)

    def __repr__(self) -> str:
        return f"boundary after {getattr(self.block, 'name', None) or type(self.block).__name__}"


class PageTiming(Observer):
    """Puts each page's time in the run into its page record (``Page.measurements``): ``seconds``, the wall time from
    when ``start`` (the stage's first block, its reader) handed the page over to when it reaches ``stop`` (the first
    block that writes pages, binds them or serves), waiting in served windows and queues included; ``datetime``, when
    it was handed over. The steps' own times are on their step records. A record read from an earlier run (``--after``,
    ``--pages``) adds this run's time to the one it carries and keeps its ``datetime``: the page's time over the runs
    that worked on it. The builder installs it on every page stage that writes pages."""

    def __init__(self, start, stop):
        self.start, self.stop = start, stop
        self._began: dict[int, tuple[float, str]] = {}

    def on_exit(self, block, doc, error=None) -> None:
        if block is self.start:
            import time
            from datetime import datetime, timezone

            self._began[id(doc)] = (time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def on_enter(self, block, doc) -> None:
        if block is self.stop:
            self._stamp(doc)

    def _stamp(self, doc) -> None:
        import time

        from ..data.page import PAGE_KEY

        began = self._began.pop(id(doc), None)
        page = doc.metadata.get(PAGE_KEY)
        if began is None or not isinstance(page, dict):
            return
        earlier = page.get("measurements") or {}
        seconds = time.perf_counter() - began[0] + float(earlier.get("seconds") or 0)
        page["measurements"] = {**earlier, "seconds": round(seconds, 4), "datetime": earlier.get("datetime") or began[1]}

    def on_task_end(self, error=None) -> None:
        self._began.clear()                       # pages a block dropped


class Tap(Observer):
    """Writes the page record of every page that comes out of ``block`` to ``folder`` (``PageJsonlWriter``'s
    format, ``<folder>/<rank>.jsonl.gz``), as it is at that point; later blocks do not change what was written."""

    def __init__(self, block, folder: str):
        self.block, self.folder = block, folder
        self._writer, self._rank = None, 0

    def on_task_start(self, rank: int, world_size: int) -> None:
        from ..blocks.writers.records import PageJsonlWriter

        self._writer, self._rank = PageJsonlWriter(self.folder), rank

    def on_exit(self, block, doc, error=None) -> None:
        if block is self.block and self._writer is not None:
            self._writer.write(doc, self._rank)

    def on_task_end(self, error=None) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def __getstate__(self):           # never pickle an open file
        return {**self.__dict__, "_writer": None}
