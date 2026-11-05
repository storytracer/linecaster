"""linecaster's logging: loguru (datatrove's), with ``{placeholder}`` templates and the values as named arguments,
so each record carries them (``record["extra"]``) and logs can be filtered by them::

    logger.warning("page {page_id} failed in {block}: {error}", page_id=doc.id, block=name, error=str(e))

On HF Jobs (``LINECASTER_LOG_JSON=1``, which the pipeline scripts set for their Jobs) the records are JSON lines
(loguru's ``serialize=True``): on the Job's stderr and in the task's log file, where datatrove writes its own.
``linecaster serve`` started in such a task inherits the variable and logs the same way."""
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
