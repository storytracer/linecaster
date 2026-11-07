"""What a local run shows on the terminal: one line naming the pipeline, a live progress line for the whole run
(pages done of the total, rate, size, failed pages, the task, the time left), one line per finished task and a
summary at the end, with human-readable units. Warnings and errors print above the progress line.

datatrove's own console output (its pipeline listing and stats block per task, the merged stats at the end) goes
only to the task logs (``OUT/logs/logs/task_<rank>.log``) and the stats files (``OUT/logs/stats/``), which keep it
whole; ``linecaster.runtime.local.LocalExecutor`` routes it. Off a terminal (a file, a pipe) the progress line is a
log line every ``EVERY_SECONDS`` instead.

``Progress`` is the observer that counts the pages leaving the pipeline (the builder puts it on every stage): in the
process that launched the run (one worker) it feeds the ``Console``; in another process (several workers) it logs
its task's progress every ``EVERY_SECONDS`` and its task line when the task ends.
"""
from __future__ import annotations

import os
import re
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


#: the console of a run launched in this process (process, Console), set by ``Console.open``
_CONSOLE: list = [None]


def active() -> Console | None:
    """The console of the run launched in this process, if this is that process."""
    c = _CONSOLE[0]
    return c if c is not None and c.pid == os.getpid() else None


# ---------------------------------------------------------------------------- the run's console

class Console:
    """The live view of one local run (one stage): ``total`` pages (None: unknown, then tasks are counted), of which
    ``done_pages`` were done before (a resume; ``done_tasks`` of ``tasks``)."""

    def __init__(self, title: str, tasks: int, total: int | None = None, done_pages: int = 0, done_tasks: int = 0,
                 live: bool | None = None):
        self.title, self.tasks, self.total = title, tasks, total
        self.done_pages, self.done_tasks = done_pages, done_tasks
        self.pages = self.failed = self.bytes = 0
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
        if self.live:
            from tqdm import tqdm

            self._bar = tqdm(total=self.total or self.tasks, initial=self.done_pages if self.total else self.done_tasks,
                             bar_format=self.title.replace("{", "{{").replace("}", "}}") + " {bar:20} {desc}",
                             file=sys.stderr,
                             dynamic_ncols=True, leave=False)
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
            if self._bar is not None:
                self._bar.write(text.rstrip("\n"), file=sys.stderr)
            else:
                sys.stderr.write(text)

    # -- counting (from ``Progress`` in this process)

    def start_task(self, rank: int) -> None:
        self.task = rank
        self._render(force=True)

    def page(self, nbytes: int, failed: bool) -> None:
        with self._lock:
            self.pages += 1
            self.bytes += nbytes
            self.failed += failed
            if self._bar is not None and self.total:
                self._bar.update(1)
        self._render()

    def task_done(self) -> None:
        with self._lock:
            self.done_tasks += 1
            if self._bar is not None and not self.total:
                self._bar.update(1)
        self._render(force=True)

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
        done = self.done_pages + self.pages
        rate = self.rate()
        parts = []
        if self.total:
            parts.append(f"{count(done)} / {count(self.total)} pages  {100 * done / self.total:.0f}%")
        else:
            parts.append(f"{count(done)} pages")
        parts.append(f"{rate * 60:,.0f}/min")
        if self.bytes:
            parts.append(size(self.bytes))
        if self.failed:
            parts.append(f"{count(self.failed)} failed")
        from ..net.http import proxy_rotation

        if (proxies := proxy_rotation()) is not None:
            parts.append(f"proxies {count(proxies[0])}/{count(proxies[1])}")
        parts.append(f"task {count((self.task if self.task is not None else self.done_tasks) + 1)}/{count(self.tasks)}")
        if self.total and rate > 0:
            parts.append(f"ETA {duration((self.total - done) / rate)}")
        elif not self.total and self.done_tasks > 0:
            left = (self.tasks - self.done_tasks) * (time.monotonic() - self.start) / max(1, self.done_tasks)
            parts.append(f"ETA {duration(left)}")
        return "  ·  ".join(parts)

    def _render(self, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if self._bar is not None:
                if force or now - self._shown >= 0.5:
                    self._bar.set_description_str(self.status(), refresh=True)
                    self._shown = now
                return
            if now - self._shown < EVERY_SECONDS:               # off a terminal: a line now and then
                return
            self._shown = now
            status = self.status()
        logger.info("{title}: {status}", title=self.title, status=status)

    def summary(self, out: str, error: BaseException | None = None) -> str:
        seconds = time.monotonic() - self.start
        what = f"{count(self.pages)} pages"
        if self.failed:
            what += f" ({count(self.failed)} failed)"
        if self.bytes:
            what += f", {size(self.bytes)}"
        head = "stopped" if error is not None else "done"
        resumed = f"; {count(self.done_pages)} pages from before" if self.done_pages else ""
        return (f"{self.title} {head}: {what} in {duration(seconds)} ({per_minute(self.pages, seconds)}){resumed}, "
                f"{count(self.done_tasks)}/{count(self.tasks)} tasks · {out}")


# ---------------------------------------------------------------------------- the observer

def _nbytes(doc) -> int:
    return sum(len(m.media_bytes) for m in getattr(doc, "media", ()) or () if getattr(m, "media_bytes", None))


class Progress(Observer):
    """Counts the pages that leave the pipeline, with their bytes and the failed ones, and reports each task: to the
    ``Console`` of the run when the task runs in the process that launched it, else a progress log line every
    ``EVERY_SECONDS``; a line when the task ends."""

    def __init__(self):
        self._reset(0, 1)

    def _reset(self, rank: int, world_size: int) -> None:
        self.rank, self.world_size = rank, world_size
        self.pages = self.failed = self.bytes = 0
        self.start = self._logged = time.monotonic()

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self._reset(0, 1)

    def on_task_start(self, rank: int, world_size: int) -> None:
        self._reset(rank, world_size)
        if (c := active()) is not None:
            c.start_task(rank)

    def on_leave(self, doc) -> None:
        from ..blocks.base.page import failed

        nbytes, bad = _nbytes(doc), failed(doc)
        self.pages += 1
        self.bytes += nbytes
        self.failed += bad
        if (c := active()) is not None:
            c.page(nbytes, bad)
        elif time.monotonic() - self._logged >= EVERY_SECONDS:
            self._logged = time.monotonic()
            logger.info("task {task}: {status}", task=self._task(), status=self._status())

    def on_task_end(self, error: BaseException | None = None) -> None:
        if error is None:
            logger.info("task {task} done: {status}", task=self._task(), status=self._status(final=True))
            if (c := active()) is not None:
                c.task_done()

    def _task(self) -> str:
        return f"{count(self.rank + 1)}/{count(self.world_size)}"

    def _status(self, final: bool = False) -> str:
        seconds = time.monotonic() - self.start
        out = f"{count(self.pages)} pages"
        if self.failed:
            out += f", {count(self.failed)} failed"
        if self.bytes:
            out += f", {size(self.bytes)}"
        return out + (f" in {duration(seconds)}" if final else "") + f" ({per_minute(self.pages, seconds)})"
