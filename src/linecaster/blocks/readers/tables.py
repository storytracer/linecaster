"""Parquet tables divided over tasks by rows rather than by files: the rows of all files, in order, in equal shards
(task ``r`` of ``N``: rows ``r * total // N`` to ``(r + 1) * total // N``), read by row group. Any table then works
with any number of tasks, one file or thousands, and a task reads at most two row groups it does not use whole.
``table_rows`` reads the files' footers once (the readers keep the result, so it travels with the pickled pipeline);
``row_slices`` is a task's part of them.
"""
from __future__ import annotations

from collections.abc import Iterator

#: the pages a task holds when the reader chooses the task count (``ImageParquetReader.auto_tasks``): a task that
#: fails runs again whole (datatrove's resume is per task), so this is also the most a resume repeats per worker
PAGES_PER_TASK = 1000
#: the items a task holds when the reader chooses the task count (``ManifestReader.auto_tasks``)
ITEMS_PER_TASK = 5


def table_rows(folder, files: list[str]) -> list[tuple[str, tuple[int, ...]]]:
    """``(file, the rows of each of its row groups)`` for each of ``files`` in ``folder`` (a datatrove
    ``DataFolder``), from their footers."""
    import pyarrow.parquet as pq

    out = []
    for path in files:
        with folder.open(path, "rb") as f, pq.ParquetFile(f) as pqf:
            meta = pqf.metadata
            out.append((path, tuple(meta.row_group(i).num_rows for i in range(meta.num_row_groups))))
    return out


def total_rows(layout: list[tuple[str, tuple[int, ...]]]) -> int:
    return sum(sum(groups) for _, groups in layout)


def tasks_for(rows: int, per_task: int) -> int:
    """The task count for shards of about ``per_task`` rows (at least one task)."""
    return max(1, -(-rows // per_task))


def row_slices(layout: list[tuple[str, tuple[int, ...]]], rank: int, world_size: int) -> list[tuple[str, int, int, int]]:
    """Task ``rank``'s shard of the rows of ``layout`` (``table_rows``), as ``(file, row group, start, stop)`` with
    ``start``/``stop`` within the row group, in order."""
    total = total_rows(layout)
    lo, hi = rank * total // world_size, (rank + 1) * total // world_size
    out, pos = [], 0
    for path, groups in layout:
        for i, n in enumerate(groups):
            start, stop = max(lo, pos), min(hi, pos + n)
            if start < stop:
                out.append((path, i, start - pos, stop - pos))
            pos += n
            if pos >= hi:
                return out
    return out


def slice_batches(pqf, slices: list[tuple[str, int, int, int]], columns: list[str] | None,
                  batch_size: int) -> Iterator:
    """The record batches of ``slices`` (one file's, from ``row_slices``) of the open ``pyarrow.parquet.ParquetFile``
    ``pqf``, at most ``batch_size`` rows each."""
    for _, group, start, stop in slices:
        table = pqf.read_row_group(group, columns=columns).slice(start, stop - start)
        yield from table.to_batches(max_chunksize=batch_size)


def whole_file(pqf, path: str) -> list[tuple[str, int, int, int]]:
    """The slices of every row of ``pqf`` (for reading one file whole)."""
    meta = pqf.metadata
    return [(path, i, 0, meta.row_group(i).num_rows) for i in range(meta.num_row_groups)]
