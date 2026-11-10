"""What a local run shows on the terminal: one line naming the pipeline, a live progress line for the whole run
(pages done of the total, rate, size, failed pages, the task, the time left), one line per finished task and a
summary at the end, with human-readable units. On a terminal the progress line is pinned to the top row and
everything else scrolls below it (a scroll region, ``Pinned``), so log lines, worker processes and libraries
writing to the terminal never break it.

datatrove's own console output (its pipeline listing and stats block per task, the merged stats at the end) goes
only to the task logs (``OUT/logs/logs/task_<rank>.log``) and the stats files (``OUT/logs/stats/``), which keep it
whole; ``linecaster.runtime.local.LocalExecutor`` routes it. Off a terminal (a file, a pipe) the progress line is a
log line every ``EVERY_SECONDS`` instead.

``Progress`` is the observer that counts the pages leaving the pipeline (the builder puts it on every stage): in the
process that launched the run (one worker) it feeds the ``Console`` directly; in a worker process (several workers)
it reports its process's counts about every second to a dict the ``Console`` reads (``report``, a ``multiprocess``
manager's, which ``LocalExecutor`` hands out); without either (another executor) it logs its task's progress every
``EVERY_SECONDS``. Every task ends with its line.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from collections import deque

from loguru import logger

from .observers import Observer

#: how often a progress log line is written where there is no live progress line
EVERY_SECONDS = 30
#: the window the rate (and so the time left) is measured over
RATE_WINDOW_SECONDS = 300
#: the console's log line format (task logs keep datatrove's full one)
CONSOLE_FORMAT = "<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> {message}"


# ---------------------------------------------------------------------------- human-readable units

def count(n: int) -> str:
    """``1234567`` -> ``1,234,567``."""
    return f"{n:,}"


def size(n: float) -> str:
    """Bytes in decimal units: ``371 MB``, ``8.6 TB``."""
    for unit in ("B", "kB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000 or unit == "PB":
            return f"{n:.0f} {unit}" if unit == "B" or abs(n) >= 100 else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} PB"


def duration(seconds: float) -> str:
    """``308`` -> ``5m 08s``; ``7380`` -> ``2h 03m``; ``277200`` -> ``3d 05h``."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 86400}d {s % 86400 // 3600:02d}h"


def per_minute(pages: float, seconds: float) -> str:
    return f"{pages / seconds * 60:,.0f}/min" if seconds > 0 else "-/min"


def block_label(step) -> str:
    """A block's name for people: its datatrove ``name`` without the leading emoji, else its class name."""
    name = getattr(step, "name", None) or type(step).__name__
    return re.sub(r"^[^\w(]+", "", str(name)).strip() or type(step).__name__


# ---------------------------------------------------------------------------- the console log sink

def _quiet(record) -> bool:
    """datatrove's chatter that the console replaces: its task start and pipeline listing, its per-task stats and
    'done' lines, the merged stats at the end. Its warnings and errors stay."""
    if record["extra"].get("console") is False:
        return True
    if record["level"].no >= 30:                                # WARNING and up
        return False
    name, function = record["name"], record["function"]
    if name == "datatrove.executor.base" and function == "_run_for_rank":
        return True
    if name == "datatrove.executor.local" and function == "run" and record["level"].name == "SUCCESS":
        return True
    return name == "datatrove.utils.logging"


def console_sink(level: str = "INFO") -> int:
    """Add the console's handler to loguru (on stderr, through the progress line when there is one); returns its
    id. The caller removes datatrove's handlers first."""
    def write(message) -> None:
        if _CONSOLE[0] is not None:
            _CONSOLE[0].write(str(message))
        else:
            sys.stderr.write(str(message))

    return logger.add(write, level=level, format=CONSOLE_FORMAT, colorize=sys.stderr.isatty(),
                      filter=lambda record: not _quiet(record))


class Pinned:
    """A line pinned to the terminal's first row: the rows below it are the terminal's scroll region (DECSTBM), so
    whatever is written to the terminal, by this process or another, scrolls under it. ``size`` gives (rows, columns)
    (default the terminal's); a resized terminal gets its region set again. ``close`` gives the whole terminal back,
    the cursor on its last row."""

    def __init__(self, stream=None, size=None):
        self.stream = stream if stream is not None else sys.stderr
        self._size = size or (lambda: tuple(reversed(shutil.get_terminal_size())))
        self.rows = self.cols = 0
        self._setup()

    def _setup(self) -> None:
        self.rows, self.cols = self._size()
        # a new line keeps what is on the last row; the region is rows 2..last; setting it homes the cursor
        self.stream.write(f"\n\x1b[2;{self.rows}r\x1b[{self.rows};1H")
        self.stream.flush()

    def draw(self, text: str) -> None:
        if self._size() != (self.rows, self.cols):
            self._setup()
        # one write: save the cursor, draw row 1, restore the cursor (where the scrolling output goes on)
        self.stream.write(f"\x1b7\x1b[1;1H\x1b[2K{text[:self.cols]}\x1b8")
        self.stream.flush()

    def close(self) -> None:
        self.stream.write(f"\x1b7\x1b[1;1H\x1b[2K\x1b8\x1b[r\x1b[{self.rows};1H")
        self.stream.flush()


def bar(fraction: float, width: int = 20) -> str:
    """``████████░░░░`` for ``fraction`` (0 to 1) in ``width`` cells."""
    filled = max(0, min(width, int(fraction * width)))
    return "█" * filled + "░" * (width - filled)


#: the console of a run launched in this process (process, Console), set by ``Console.open``
_CONSOLE: list = [None]
#: what the tasks of this worker process have done so far, for the run's console (``Progress.report``)
_WORKER = {"pages": 0, "failed": 0, "bytes": 0, "tasks": 0, "reused": 0, "reused_bytes": 0, "reported": 0.0}


def active() -> Console | None:
    """The console of the run launched in this process, if this is that process."""
    c = _CONSOLE[0]
    return c if c is not None and c.pid == os.getpid() else None


# ---------------------------------------------------------------------------- the run's console

class Console:
    """The live view of one local run (one stage): ``total`` pages (None: unknown, then tasks are counted), of which
    ``done_pages`` were done before (a resume; ``done_tasks`` of ``tasks``). ``shared``: the dict the worker processes
    report their counts to (several workers); without it the counts come from ``Progress`` in this process."""

    def __init__(self, title: str, tasks: int, total: int | None = None, done_pages: int = 0, done_tasks: int = 0,
                 live: bool | None = None, shared=None, unit: str = "pages"):
        self.title, self.tasks, self.total, self.unit = title, tasks, total, unit
        self.done_pages, self.done_tasks = done_pages, done_tasks
        self.shared, self._done_before = shared, done_tasks
        self.pages = self.failed = self.bytes = self.reused = self.reused_bytes = 0
        #: the size of what was done before this launch (``add_before``); None while it is being read
        self.done_bytes: int | None = 0 if not done_tasks else None
        self.task: int | None = None
        self.live = sys.stderr.isatty() if live is None else live
        self.pid = os.getpid()
        self.start = time.monotonic()
        self._samples: deque = deque([(self.start, 0)])
        self._bar = None
        self._shown = 0.0
        self._lock = threading.RLock()
        self._stop = threading.Event()

    # -- lifecycle

    def open(self) -> Console:
        _CONSOLE[0] = self
        if self.live and shutil.get_terminal_size().lines >= 4:     # a terminal with room for a region
            self._bar = Pinned()
            self._render(force=True)
        # refreshed while no page arrives too (a stall is when the time left matters)
        threading.Thread(target=self._tick, name="linecaster-console", daemon=True).start()
        return self

    def _tick(self) -> None:
        while not self._stop.wait(1.0):
            self._render()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            if self._bar is not None:
                self._bar.close()
                self._bar = None
        if _CONSOLE[0] is self:
            _CONSOLE[0] = None

    def write(self, text: str) -> None:
        """A log line, above the progress line."""
        with self._lock:
            sys.stderr.write(text)                  # under a pinned line: the region scrolls it
            sys.stderr.flush()

    # -- counting (from ``Progress`` in this process)

    def start_task(self, rank: int) -> None:
        self.task = rank
        self._render(force=True)

    def add_before(self, nbytes: int) -> None:
        """The size of what was done before this launch, once read (``linecaster.runtime.local.size_before``)."""
        with self._lock:
            self.done_bytes = nbytes
        self._render(force=True)

    def page(self, nbytes: int, failed: bool, reused: bool = False) -> None:
        with self._lock:
            if reused:                              # done before, not fetched now: not in the rate
                self.reused += 1
                self.reused_bytes += nbytes
                return
            self.pages += 1
            self.bytes += nbytes
            self.failed += failed
        self._render()

    def task_done(self) -> None:
        with self._lock:
            self.done_tasks += 1
        self._render(force=True)

    def _sync(self) -> None:
        """The worker processes' counts (several workers), into this console. Reads the manager without holding
        ``_lock`` (a manager that does not answer must not block the log lines that need the lock)."""
        if self.shared is None:
            return
        try:
            reports = list(self.shared.values())
        except Exception:  # noqa: BLE001 - the manager is gone (the run is ending): keep the last counts
            return
        with self._lock:
            self._apply(reports)

    def _apply(self, reports: list) -> None:
        self.pages = sum(r[0] for r in reports)
        self.failed = sum(r[1] for r in reports)
        self.bytes = sum(r[2] for r in reports)
        self.done_tasks = self._done_before + sum(r[3] for r in reports)
        self.reused = sum(r[4] for r in reports)
        self.reused_bytes = sum(r[5] for r in reports)

    # -- what is shown

    def rate(self) -> float:
        """Pages per second over the last ``RATE_WINDOW_SECONDS``."""
        now = time.monotonic()
        if now - self._samples[-1][0] >= 1:
            self._samples.append((now, self.pages))
        while len(self._samples) > 2 and now - self._samples[1][0] > RATE_WINDOW_SECONDS:
            self._samples.popleft()
        t0, p0 = self._samples[0]
        return (self.pages - p0) / (now - t0) if now > t0 else 0.0

    def status(self) -> str:
        done = self.done_pages + self.reused + self.pages
        rate = self.rate()
        parts = []
        if self.total:
            parts.append(f"{count(done)} / {count(self.total)} {self.unit}  {100 * done / self.total:.0f}%")
        else:
            parts.append(f"{count(done)} {self.unit}")
        parts.append(f"{rate * 60:,.0f}/min")
        stored = self.bytes + self.reused_bytes + (self.done_bytes or 0)
        if self.done_bytes is None:
            parts.append(f"{size(stored)} + size before …" if stored else "size …")
        elif stored:
            parts.append(size(stored))
        if self.failed:
            parts.append(f"{count(self.failed)} failed")
        if self.reused:
            parts.append(f"{count(self.reused)} reused")
        from ..net.http import pause_left, paused, proxy_counts

        if (wait := paused()) is not None:
            parts.append("paused: server errors, " + (f"next try in {duration(wait)}" if wait else "trying"))
        if (pause := pause_left()) is not None:
            parts.append(f"paused: {pause[1]}, requests go on in {duration(pause[0])}")
        if (proxies := proxy_counts()) is not None:
            parts.append(f"proxies {count(proxies[0])} held, {count(proxies[1])} blocked, {count(proxies[2])} free")
        if self.shared is not None:
            parts.append(f"{count(self.done_tasks)}/{count(self.tasks)} tasks done")
        else:
            parts.append(f"task {count((self.task if self.task is not None else self.done_tasks) + 1)}/"
                         f"{count(self.tasks)}")
        if self.total and rate > 0:
            parts.append(f"ETA {duration((self.total - done) / rate)}")
        elif not self.total and self.done_tasks > 0:
            left = (self.tasks - self.done_tasks) * (time.monotonic() - self.start) / max(1, self.done_tasks)
            parts.append(f"ETA {duration(left)}")
        return "  ·  ".join(parts)

    def _render(self, force: bool = False) -> None:
        self._sync()
        with self._lock:
            now = time.monotonic()
            if self._bar is not None:
                if force or now - self._shown >= 0.5:
                    done = (self.done_pages + self.pages) / self.total if self.total else self.done_tasks / self.tasks
                    self._bar.draw(f"{self.title} {bar(done)} {self.status()}")
                    self._shown = now
                return
            if now - self._shown < EVERY_SECONDS:               # off a terminal: a line now and then
                return
            self._shown = now
            status = self.status()
        logger.info("{title}: {status}", title=self.title, status=status)

    def summary(self, out: str, error: BaseException | None = None) -> str:
        reader = threading.Thread(target=self._sync, daemon=True)   # at most a few seconds for the last counts
        reader.start()
        reader.join(5)
        seconds = time.monotonic() - self.start
        what = f"{count(self.pages)} {self.unit}"
        if self.failed:
            what += f" ({count(self.failed)} failed)"
        if self.bytes:
            what += f", {size(self.bytes)}"
        if self.reused:
            what += f"; {count(self.reused)} reused (already there)"
        head = "stopped" if error is not None else "done"
        resumed = f"; {count(self.done_pages)} {self.unit} from before" if self.done_pages else ""
        return (f"{self.title} {head}: {what} in {duration(seconds)} ({per_minute(self.pages, seconds)}){resumed}, "
                f"{count(self.done_tasks)}/{count(self.tasks)} tasks · {out}")


# ---------------------------------------------------------------------------- the observer

def _nbytes(doc) -> int:
    return sum(len(m.media_bytes) for m in getattr(doc, "media", ()) or () if getattr(m, "media_bytes", None))


class Progress(Observer):
    """Counts the pages that leave the pipeline, with their bytes and the failed ones, and reports them: to the
    ``Console`` of the run when the task runs in the process that launched it; to ``report`` (a dict shared with that
    process, set by ``LocalExecutor`` for several workers) from a worker process; else as a progress log line every
    ``EVERY_SECONDS``. A line when the task ends."""

    def __init__(self):
        self.report = None
        self._reset(0, 1)

    def _reset(self, rank: int, world_size: int) -> None:
        self.rank, self.world_size = rank, world_size
        self.pages = self.failed = self.bytes = self.reused = 0
        self.unit = "pages"                         # "files" once a resource leaves
        self.start = self._logged = time.monotonic()

    def __getstate__(self):                     # its counts stay where they are; the shared dict travels
        return {"report": self.report}

    def __setstate__(self, state):
        self.report = state.get("report")
        self._reset(0, 1)

    def _report(self, force: bool = False) -> None:
        """This process's counts to ``report``, about once a second (``force``: now)."""
        now = time.monotonic()
        if self.report is None or not force and now - _WORKER["reported"] < 1:
            return
        _WORKER["reported"] = now
        try:
            self.report[os.getpid()] = (_WORKER["pages"], _WORKER["failed"], _WORKER["bytes"], _WORKER["tasks"],
                                        _WORKER["reused"], _WORKER["reused_bytes"])
        except Exception:  # noqa: BLE001 - the run's console is gone; the pages go on
            self.report = None

    def on_task_start(self, rank: int, world_size: int) -> None:
        self._reset(rank, world_size)
        if (c := active()) is not None:
            c.start_task(rank)

    def on_leave(self, doc) -> None:
        from ..blocks.base.page import failed
        from ..blocks.readers.existing import is_reused

        reused = is_reused(doc)
        nbytes, bad = _nbytes(doc), failed(doc)
        if "resource" in doc.metadata:
            self.unit = "files"
        if reused:
            self.reused += 1
        else:
            self.pages += 1
            self.bytes += nbytes
            self.failed += bad
        if (c := active()) is not None:
            c.page(nbytes, bad, reused)
        elif self.report is not None:
            if reused:
                _WORKER["reused"] += 1
                _WORKER["reused_bytes"] += nbytes
            else:
                _WORKER["pages"] += 1
                _WORKER["failed"] += bad
                _WORKER["bytes"] += nbytes
            self._report()
        elif time.monotonic() - self._logged >= EVERY_SECONDS:
            self._logged = time.monotonic()
            logger.info("task {task}: {status}", task=self._task(), status=self._status())

    def on_task_end(self, error: BaseException | None = None) -> None:
        if error is None:
            logger.info("task {task} done: {status}", task=self._task(), status=self._status(final=True))
            if (c := active()) is not None:
                c.task_done()
            elif self.report is not None:
                _WORKER["tasks"] += 1
        self._report(force=True)

    def _task(self) -> str:
        return f"{count(self.rank + 1)}/{count(self.world_size)}"

    def _status(self, final: bool = False) -> str:
        seconds = time.monotonic() - self.start
        out = f"{count(self.pages)} {self.unit}"
        if self.failed:
            out += f", {count(self.failed)} failed"
        if self.bytes:
            out += f", {size(self.bytes)}"
        if self.reused:
            out += f", {count(self.reused)} reused"
        return out + (f" in {duration(seconds)}" if final else "") + f" ({per_minute(self.pages, seconds)})"
