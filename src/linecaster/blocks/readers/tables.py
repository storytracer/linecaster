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


def first_rows(layout: list[tuple[str, tuple[int, ...]]], rows: int) -> list[tuple[str, tuple[int, ...]]]:
    """``layout`` cut after its first ``rows`` rows (the last row group shortened), as if the input ended there."""
    out, left = [], rows
    for path, groups in layout:
        kept = []
        for n in groups:
            if left <= 0:
                break
            kept.append(min(n, left))
            left -= kept[-1]
        if kept:
            out.append((path, tuple(kept)))
        if left <= 0:
            break
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
    return rows_between(layout, rank * total // world_size, (rank + 1) * total // world_size)


def item_runs(folder, layout: list[tuple[str, tuple[int, ...]]], item_key: str) -> tuple:
    """The items of ``layout``'s rows by their ``item_key`` value, in the order they first appear, as three ``array``s:
    ``starts`` (where each run of rows with one item begins, the total row count last), ``order`` (the runs, item by
    item) and ``offsets`` (where each item's runs begin in ``order``, the run count last). An item whose rows are not
    together (an unsorted table) is still one item. Arrays, not lists: the pipeline is copied for every task."""
    import array

    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    starts, values, pos, last = array.array("q"), [], 0, object()
    for path, groups in layout:
        with folder.open(path, "rb") as f, pq.ParquetFile(f) as pqf:
            for i, n in enumerate(groups):
                if n == 0:
                    continue
                column = pqf.read_row_group(i, columns=[item_key]).column(0).slice(0, n).combine_chunks()
                cuts = [0]
                if n > 1:
                    changed = pc.not_equal(column.slice(1), column.slice(0, n - 1))
                    cuts += [int(j) + 1 for j in pc.indices_nonzero(changed).to_pylist()]
                for c in cuts:
                    value = column[c].as_py()
                    if c > 0 or value != last:
                        starts.append(pos + c)
                        values.append(value)
                last = column[n - 1].as_py()
                pos += n
    starts.append(pos)
    by_item: dict = {}
    for run, value in enumerate(values):
        by_item.setdefault(value, []).append(run)
    order, offsets = array.array("q"), array.array("q", [0])
    for runs in by_item.values():
        order.extend(runs)
        offsets.append(len(order))
    return starts, order, offsets


def item_ranges(items: tuple, rank: int, world_size: int) -> list[tuple[int, int]]:
    """The row ranges (from, to) of task ``rank``'s items when ``world_size`` tasks divide the items of ``items``
    (``item_runs``) in equal shards: one item each when there are as many tasks as items."""
    starts, order, offsets = items
    count = len(offsets) - 1
    first, end = rank * count // world_size, (rank + 1) * count // world_size
    return [(starts[r], starts[r + 1]) for r in order[offsets[first]:offsets[end]]]


def rows_between(layout: list[tuple[str, tuple[int, ...]]], lo: int, hi: int) -> list[tuple[str, int, int, int]]:
    """The rows ``lo`` to ``hi`` of ``layout``, as ``row_slices`` gives them."""
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


def position_slices(layout: list[tuple[str, tuple[int, ...]]], positions) -> list[tuple[str, int, int, int]]:
    """The rows at ``positions`` (sorted, of all files in order) of ``layout``, as ``row_slices`` gives them: one
    slice per run of consecutive rows within a row group."""
    out: list = []
    starts, pos = [], 0
    for path, groups in layout:
        for i, n in enumerate(groups):
            starts.append((pos, path, i))
            pos += n
    g = 0
    for p in positions:
        while g + 1 < len(starts) and starts[g + 1][0] <= p:
            g += 1
        first, path, group = starts[g]
        row = p - first
        if out and out[-1][0] == path and out[-1][1] == group and out[-1][3] == row:
            out[-1] = (path, group, out[-1][2], row + 1)
        else:
            out.append((path, group, row, row + 1))
    return out


def slice_batches(pqf, slices: list[tuple[str, int, int, int]], columns: list[str] | None,
                  batch_size: int) -> Iterator:
    """The record batches of ``slices`` (one file's, from ``row_slices``) of the open ``pyarrow.parquet.ParquetFile``
    ``pqf``, at most ``batch_size`` rows each. Slices of one row group that follow each other read it once."""
    import itertools

    for group, parts in itertools.groupby(slices, key=lambda s: s[1]):
        parts = list(parts)
        table = pqf.read_row_group(group, columns=columns)
        if len(parts) == 1:
            table = table.slice(parts[0][2], parts[0][3] - parts[0][2])
        else:
            table = table.take([i for _, _, start, stop in parts for i in range(start, stop)])
        yield from table.to_batches(max_chunksize=batch_size)


def whole_file(pqf, path: str) -> list[tuple[str, int, int, int]]:
    """The slices of every row of ``pqf`` (for reading one file whole)."""
    meta = pqf.metadata
    return [(path, i, 0, meta.row_group(i).num_rows) for i in range(meta.num_row_groups)]
