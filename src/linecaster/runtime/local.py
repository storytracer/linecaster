"""``LocalExecutor``: datatrove's ``LocalPipelineExecutor`` with linecaster's console (``linecaster.runtime.console``).

On the terminal a run shows one line naming the pipeline (its blocks, without the builder's boundaries), a live
progress line, a line per finished task and a summary. datatrove's task logs (``OUT/logs/logs/task_<rank>.log``:
its task start, pipeline listing and stats block, in its full line format) and stats files stay as they are; its
console output is replaced (its task logger swapped for ``task_logger`` while a task runs, as
``linecaster.runtime.jobs.JobsExecutor`` swaps it for JSON logs). The completion markers are listed once per launch,
not looked up task by task.

A task that fails (a ``PageError`` of an error budget, a storage error) is logged and the others go on, as they would
not with datatrove alone (its pool stops at the first exception): without a completion marker it runs again on the
next launch, and the summary counts it. An error that is not the pages' (``NOT_THE_PAGES``: the configuration, the
catalog, a server) and ``FAILED_IN_A_ROW`` failed tasks in a row in one worker still stop the run. With
``retry_failed``, finished tasks that left rejects run again (their rejects file removed first; with a reader's
``reuse_folder`` their pages that are there are read back, only the failed ones fetched). ``kill -USR1 <pid>`` writes
every thread's stack to the terminal (``faulthandler``), for a run that seems stuck. Each task tells the broker its
worker index (datatrove's local rank, distinct among the tasks running at once; ``linecaster.broker.set_worker_index``),
so worker processes that start together claim different worker slots at once.
"""
from __future__ import annotations

import faulthandler
import signal
import sys

from datatrove.executor import LocalPipelineExecutor
from loguru import logger

from .console import Console, block_label, console_sink, count

#: datatrove's task log line format, kept for the task log files
TASK_LOG_FORMAT = ("{time:YYYY-MM-DD HH:mm:ss.SSS} | <level>{level: <8}</level> | {name}:{function}:{line} - "
                   "<level>{message}</level>")


def task_logger(logging_dir, rank: int, local_rank: int = 0, node_rank: int = -1):
    """datatrove's ``add_task_logger`` with linecaster's console: the task log file as datatrove writes it, and the
    console handler (``console_sink``, every worker's). Returns the log file."""
    from datatrove.utils.logging import DATATROVE_COLORIZE_LOG_FILES

    from .logs import add_task_logger, json_logs

    if json_logs():
        return add_task_logger(logging_dir, rank, local_rank, node_rank)
    logger.remove()
    logfile = logging_dir.open(f"logs/task_{rank:05d}.log", "w")
    console_sink()
    logger.add(logfile, colorize=DATATROVE_COLORIZE_LOG_FILES, level="DEBUG", format=TASK_LOG_FORMAT)
    logger.bind(console=False).info(f"Launching pipeline for {rank=}")
    return logfile


def log_pipeline(pipeline) -> None:
    """datatrove's pipeline listing, into the task log only."""
    steps = "\n".join(repr(step) if callable(step) else "Iterable" for step in pipeline)
    logger.bind(console=False).info(f"\n--- 🛠️ PIPELINE 🛠\n{steps}")


def close_task_logger(logfile) -> None:
    """The task is over: its log file closed, the console handler alone again."""
    from .logs import json_logs

    logger.complete()
    if not json_logs():
        logger.remove()
        console_sink()
    logfile.close()


#: failed tasks in a row, in one worker, that stop the run (something is wrong with every task, not with some)
FAILED_IN_A_ROW = 20
#: the failed tasks in a row of this worker process
_FAILED = [0]


def stack_dumps() -> None:
    """``kill -USR1 <pid>`` writes every thread's stack to stderr (the terminal), in this process."""
    if not hasattr(signal, "SIGUSR1"):
        return
    try:
        faulthandler.register(signal.SIGUSR1, file=sys.__stderr__, all_threads=True)
    except (AttributeError, OSError, ValueError):    # no real stderr (e.g. captured): no dumps, nothing else changes
        pass


#: stats files read at once for the size before (``size_before``)
STATS_BATCH = 1000


def size_before(logging_dir, ranks) -> int:
    """The bytes of the images the finished tasks ``ranks`` read (their readers' ``media_size``: downloaded and
    reused), from datatrove's stats files (``logging_dir/stats/<rank>.json``), read in batches through fsspec."""
    import json

    from datatrove.io import get_datafolder

    folder, total = get_datafolder(logging_dir), 0
    ranks = sorted(ranks)
    for i in range(0, len(ranks), STATS_BATCH):
        paths = [f"stats/{r:05d}.json" for r in ranks[i:i + STATS_BATCH]]
        for raw in folder.cat(paths, on_error="omit").values():
            try:
                steps = json.loads(raw)
            except ValueError:
                continue
            for step in steps:
                media = (step.get("stats") or {}).get("media_size")
                if isinstance(media, dict):
                    total += int(media.get("total") or 0)
                    break                            # the reader's; later blocks do not read images again
    return total


def blocks(pipeline) -> list[str]:
    """The pipeline's blocks by name, without the builder's boundaries."""
    from .observers import Boundary

    return [block_label(getattr(step, "block", step)) for step in pipeline if not isinstance(step, Boundary)]


class LocalExecutor(LocalPipelineExecutor):
    """``LocalPipelineExecutor`` whose console is linecaster's: ``title`` names the run on it, ``out`` is the run
    folder the summary points at, and ``reader`` (a block with ``task_pages(rank, world_size)``, optional) gives the
    pages of each task, so the progress line has a total and a time left; ``note`` is shown after the pipeline line,
    a line or a list of lines (``linecaster.runtime.run.run_notes``: why it has the workers it has, what a server
    sees)."""

    def __init__(self, pipeline, *, title: str = "run", out: str = "", reader=None, note: str | list[str] | None = None,
                 retry_failed: bool = False, **kwargs):
        super().__init__(pipeline, **kwargs)
        self.title, self.out, self.reader, self.note = title, out, reader, note
        self.retry_failed = retry_failed
        self._retry: set[int] = set()
        self._completed: set[int] | None = None

    def get_incomplete_ranks(self, ranks=None, skip_completed=None) -> list[int]:
        """datatrove's, plus the finished tasks that run again (``retry_failed``): their markers are still there."""
        incomplete = super().get_incomplete_ranks(ranks, skip_completed)
        if not self._retry:
            return incomplete
        wanted = set(ranks if ranks is not None else range(self.world_size))
        return sorted(set(incomplete) | (self._retry & wanted))

    def is_rank_completed(self, rank: int) -> bool:
        if self._completed is not None:
            return self.skip_completed and rank in self._completed
        return super().is_rank_completed(rank)

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        import datatrove.executor.base as base
        from datatrove.utils.stats import PipelineStats

        from ..blocks.base.page import NOT_THE_PAGES

        stack_dumps()
        from ..broker import set_worker_index

        set_worker_index(local_rank, self.workers)   # the pool's worker index: the broker's slot search starts there
        if rank in self._retry:                  # a fresh rejects file, or none if no page fails this time
            self._remove_rejects(rank)
        saved = base.add_task_logger, base.log_pipeline, base.close_task_logger
        base.add_task_logger, base.log_pipeline, base.close_task_logger = task_logger, log_pipeline, close_task_logger
        try:
            stats = super()._run_for_rank(rank, local_rank, node_rank)
            _FAILED[0] = 0
            return stats
        except NOT_THE_PAGES:
            raise
        except Exception as e:  # noqa: BLE001 - one task's failure; the others go on
            _FAILED[0] += 1
            logger.error("task {task} failed: {error_type}: {error}; it runs again on the next launch",
                         task=f"{rank + 1:,}/{self.world_size:,}", error_type=type(e).__name__,
                         error=str(e).splitlines()[0] if str(e) else "")
            if _FAILED[0] >= FAILED_IN_A_ROW:
                raise RuntimeError(f"{_FAILED[0]} tasks in a row failed in this worker, the last with "
                                   f"{type(e).__name__}: something is wrong with every task; the run stops") from e
            return PipelineStats()
        finally:
            base.add_task_logger, base.log_pipeline, base.close_task_logger = saved

    def _rejects(self):
        from datatrove.io import get_datafolder

        return get_datafolder(f"{self.out.rstrip('/')}/rejects")

    def _remove_rejects(self, rank: int) -> None:
        folder = self._rejects()
        for name in (f"{rank:05d}.jsonl", f"{rank:05d}.jsonl.gz"):
            if folder.exists(name):
                folder.rm(name)

    def _ranks_with_rejects(self) -> set[int]:
        """The ranks whose tasks left a rejects file (``rejects/<rank>.jsonl``), from one listing."""
        try:
            names = self._rejects().list_files()
        except FileNotFoundError:
            return set()
        ranks = set()
        for name in names:
            stem = name.rsplit("/", 1)[-1].split(".", 1)[0]
            if stem.isdigit():
                ranks.add(int(stem))
        return ranks

    def _report_unfinished(self, ranks) -> None:
        """The tasks of this launch that did not finish (failed or stopped), from one listing of the markers."""
        try:
            left = len(self.get_incomplete_ranks(ranks))
        except Exception:  # noqa: BLE001 - only a count for the summary
            return
        if left:
            logger.warning("{left} task{s} not finished: they run again on the next launch", left=f"{left:,}",
                           s="s" if left != 1 else "")

    def run(self):
        from .logs import json_logs

        if self.depends is not None and not self.depends._launched:
            self.depends.run()
        ranks = range(self.local_rank_offset, self.local_rank_offset + self.local_tasks)
        todo = set(self.get_incomplete_ranks(ranks))
        self._completed = {r for r in ranks if r not in todo} if self.skip_completed else set()
        if self.retry_failed:                    # finished tasks that left rejects run again
            self._retry = self._ranks_with_rejects() & self._completed
            self._completed -= self._retry
            todo |= self._retry
        stack_dumps()
        if json_logs():
            return super().run()
        logger.remove()
        console_sink()
        pages = self.reader.task_pages if self.reader is not None and hasattr(self.reader, "task_pages") else None
        total = sum(pages(r, self.tasks) for r in ranks) if pages else None
        done_pages = sum(pages(r, self.tasks) for r in self._completed) if pages else 0
        workers = min(self.workers, max(1, len(todo)))
        unit = getattr(self.reader, "unit_label", "pages")
        what = f"{count(total)} {unit} in " if total is not None else ""
        line = (f"{self.title} → {self.out}: {' → '.join(blocks(self.pipeline))} · {what}{count(self.local_tasks)} "
                f"task{'s' if self.local_tasks != 1 else ''}, {workers} worker{'s' if workers != 1 else ''}")
        if self._completed:
            line += f"; {count(len(self._completed))} done before ({count(done_pages)} {unit})" if pages else \
                    f"; {count(len(self._completed))} done before"
        logger.info(line)
        for note in [self.note] if isinstance(self.note, str) else self.note or []:
            logger.info(note)
        if self._retry:
            logger.info("{n} finished tasks with failed pages run again (--retry-failed)", n=f"{len(self._retry):,}")
        if not todo:
            return super().run()
        manager = shared = None
        if self.workers > 1:                     # the worker processes report their counts to this one
            import multiprocess

            from .console import Progress
            from .observers import Boundary

            manager = multiprocess.Manager()
            shared = manager.dict()
            for step in self.pipeline:
                if isinstance(step, Boundary):
                    for o in step.hub.observers:
                        if isinstance(o, Progress):
                            o.report = shared
        console = Console(self.title, self.local_tasks, total, done_pages, len(self._completed),
                          live=sys.stderr.isatty(), shared=shared, unit=unit).open()
        if self._completed:                      # their size, read while the run starts
            import threading

            def read_size() -> None:
                try:
                    console.add_before(size_before(self.logging_dir, self._completed))
                except Exception as e:  # noqa: BLE001 - the size is shown without what came before
                    logger.warning("the size of the {n} finished tasks could not be read: {error}",
                                   n=len(self._completed), error=str(e))
                    console.add_before(0)

            threading.Thread(target=read_size, name="linecaster-size-before", daemon=True).start()
        error = None
        try:
            return super().run()
        except BaseException as e:
            error = e
            raise
        finally:
            console.close()
            logger.info(console.summary(self.out, error))
            self._retry = set()                  # a retried task that failed again keeps its old marker
            self._report_unfinished(ranks)
            if manager is not None:
                try:
                    manager.shutdown()
                except Exception:  # noqa: BLE001 - the counts' manager is gone already; nothing to keep
                    pass
