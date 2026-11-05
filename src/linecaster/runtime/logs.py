"""linecaster's logging: loguru (datatrove's), with ``{placeholder}`` templates and the values as named arguments,
so each record carries them (``record["extra"]``) and logs can be filtered by them::

    logger.warning("page {page_id} failed in {block}: {error}", page_id=doc.id, block=name, error=str(e))

On HF Jobs (``LINECASTER_LOG_JSON=1``, which the pipeline scripts set for their Jobs) the records are JSON lines
(loguru's ``serialize=True``): on the Job's stderr and in the task's log file, where datatrove writes its own.
``linecaster serve`` started in such a task inherits the variable and logs the same way.

Log records carry ``trace_id`` and ``span_id`` (in ``extra``, hex) while a task is traced (``install_trace_ids``, by
``linecaster.tracing.Tracing``): the page the record names (``page_id``), else the span of the per-unit block
running in the thread, else the task's span; in ``linecaster serve`` the span of the request the thread works on."""
from __future__ import annotations

import os
import sys

from loguru import logger

#: set (to 1) in a Job's environment: JSON lines instead of text
JSON_ENV = "LINECASTER_LOG_JSON"


def json_logs() -> bool:
    """Whether this process logs JSON lines (``LINECASTER_LOG_JSON``)."""
    return os.environ.get(JSON_ENV, "").strip().lower() in ("1", "true", "yes")


def configure(level: str = "INFO") -> None:
    """One handler on stderr: JSON lines when ``json_logs()``, else loguru's text (``linecaster serve``)."""
    logger.remove()
    logger.add(sys.stderr, level=level, serialize=json_logs())


def add_task_logger(logging_dir, rank: int, local_rank: int = 0, node_rank: int = -1):
    """datatrove's task logger (``datatrove.utils.logging.add_task_logger``: stderr, and ``logs/task_<rank>.log``
    in the logging folder) with JSON lines when ``json_logs()``. Returns the log file."""
    from datatrove.utils.logging import add_task_logger as datatrove_task_logger

    if not json_logs():
        return datatrove_task_logger(logging_dir, rank, local_rank, node_rank=node_rank)
    logger.remove()
    logfile = logging_dir.open(f"logs/task_{rank:05d}.log", "w")
    logger.add(sys.stderr, level="INFO" if local_rank == 0 else "ERROR", serialize=True)
    logger.add(logfile, level="DEBUG", serialize=True)
    logger.info("Launching pipeline for rank={rank}", rank=rank, node_rank=node_rank)
    return logfile


#: the tracing observers of the tasks running in this process (datatrove runs a process's tasks one after another)
_SOURCES: list = []
_INSTALLED = [False]


def _trace_ids(record) -> None:
    ids = None
    for source in reversed(_SOURCES):
        ids = source.log_ids(record)
        if ids:
            break
    if not ids:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        ids = (ctx.trace_id, ctx.span_id) if ctx.is_valid else None
    if ids:
        record["extra"]["trace_id"], record["extra"]["span_id"] = f"{ids[0]:032x}", f"{ids[1]:016x}"


def install_trace_ids(source=None) -> None:
    """Put ``trace_id`` and ``span_id`` on every log record (a loguru patcher, installed once per process);
    ``source`` (a ``Tracing`` observer, for its task) says which span a record belongs to."""
    if source is not None and source not in _SOURCES:
        _SOURCES.append(source)
    if not _INSTALLED[0]:
        logger.configure(patcher=_trace_ids)
        _INSTALLED[0] = True


def remove_trace_ids(source) -> None:
    """The task of ``source`` is over: its spans are no longer looked up."""
    if source in _SOURCES:
        _SOURCES.remove(source)
