"""Parquet tables are divided over tasks by rows, not files (``linecaster.blocks.readers.tables``): equal shards over
all files and row groups in order, so one file works with any number of tasks; the readers suggest a task count from
their input (``auto_tasks``); ``linecaster.runtime.run.allocate`` chooses ``--tasks`` and ``--workers`` where the
command line leaves them open, and divides ``--rate-limit`` over the tasks running at once."""
import argparse

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from datatrove.io import get_datafolder

from linecaster.blocks.base.page import page_of
from linecaster.blocks.readers.images import ImageParquetReader
from linecaster.blocks.readers.tables import PAGES_PER_TASK, row_slices, table_rows, tasks_for
from linecaster.testing import sample_png


def write_pages(folder, files: list[int], row_group_size: int):
    """Page tables with image bytes: file ``i`` holds ``files[i]`` pages of book ``f<i>``."""
    folder.mkdir()
    png = sample_png()
    for i, n in enumerate(files):
        pq.write_table(pa.table({"book": [f"f{i}"] * n, "page": list(range(1, n + 1)), "image": [png] * n}),
                       folder / f"part-{i}.parquet", row_group_size=row_group_size)
    return str(folder)


def test_row_slices_are_equal_runs_over_files_and_row_groups():
    layout = [("a.parquet", (4, 4, 2)), ("b.parquet", (3,))]          # 13 rows
    runs = [row_slices(layout, r, 3) for r in range(3)]
    assert runs[0] == [("a.parquet", 0, 0, 4)]
    assert runs[1] == [("a.parquet", 1, 0, 4)]
    assert runs[2] == [("a.parquet", 2, 0, 2), ("b.parquet", 0, 0, 3)]
    runs = [row_slices(layout, r, 4) for r in range(4)]                  # rows 0-3, 3-6, 6-9, 9-13
    assert runs[1] == [("a.parquet", 0, 3, 4), ("a.parquet", 1, 0, 2)]
    assert runs[3] == [("a.parquet", 2, 1, 2), ("b.parquet", 0, 0, 3)]
    assert row_slices(layout, 0, 1) == [("a.parquet", 0, 0, 4), ("a.parquet", 1, 0, 4), ("a.parquet", 2, 0, 2),
                                        ("b.parquet", 0, 0, 3)]
    assert [row_slices(layout, r, 20) for r in range(20)].count([]) == 7     # more tasks than rows: some get none


def test_tasks_for_rounds_up_and_gives_at_least_one():
    assert (tasks_for(0, 1000), tasks_for(1000, 1000), tasks_for(1001, 1000)) == (1, 1, 2)


@pytest.mark.parametrize("world_size", [1, 2, 3, 7])
def test_one_file_feeds_any_number_of_tasks_with_every_page_once_in_order(tmp_path, world_size):
    data = write_pages(tmp_path / "data", [10], row_group_size=4)
    ids = []
    for rank in range(world_size):
        reader = ImageParquetReader(data, item_key="book", sequence_key="page")
        got = [page_of(d).page_id for d in reader.run(rank=rank, world_size=world_size)]
        assert len(got) in (10 // world_size, -(-10 // world_size))      # equal shards
        ids += got
    assert ids == [f"f0_{i:04d}" for i in range(1, 11)]


def test_limit_and_skip_count_pages_per_task_across_files(tmp_path):
    data = write_pages(tmp_path / "data", [3, 3], row_group_size=2)
    reader = ImageParquetReader(data, item_key="book", sequence_key="page", skip=2, limit=3)
    assert [page_of(d).page_id for d in reader.run()] == ["f0_0003", "f1_0001", "f1_0002"]


def test_auto_tasks_are_runs_of_about_pages_per_task(tmp_path):
    data = write_pages(tmp_path / "data", [PAGES_PER_TASK, PAGES_PER_TASK // 2], row_group_size=500)
    reader = ImageParquetReader(data, item_key="book", sequence_key="page")
    assert reader.auto_tasks() == 2
    assert table_rows(get_datafolder(data), ["part-1.parquet"]) == [("part-1.parquet", (500,))]


def test_read_file_still_reads_one_whole_file(tmp_path):
    data = write_pages(tmp_path / "data", [5, 2], row_group_size=2)
    reader = ImageParquetReader(data, item_key="book", sequence_key="page")
    assert [page_of(d).page_id for d in reader.read_file("part-1.parquet")] == ["f1_0001", "f1_0002"]


# ---------------------------------------------------------------- allocate and the rate limits


def options(argv, has_engines):
    from linecaster.runtime import run

    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(argv))
    a.has_engines = has_engines
    return a


def test_a_pipeline_without_engines_gets_its_readers_task_count_and_one_worker_with_rate_limits(tmp_path):
    from linecaster.runtime import run

    data = write_pages(tmp_path / "data", [2500], row_group_size=1000)
    a = options(["--parquet", data, "OUT", "--item-key", "book", "--sequence-key", "page",
                 "--rate-limit", "150/60", "--rate-limit", "3/1"], has_engines=False)
    reader = run.reader(a)
    assert reader._opener.http["rate_limits"] == [(150, 60.0), (3, 1.0)]        # one task at a time: all of it
    run.allocate(a, [reader])
    assert (a.tasks, a.workers) == (3, 1)


def test_without_rate_limits_a_pipeline_without_engines_runs_a_worker_per_cpu(tmp_path, monkeypatch):
    from linecaster.runtime import run

    monkeypatch.setattr(run.os, "cpu_count", lambda: 2)
    data = write_pages(tmp_path / "data", [2500], row_group_size=1000)
    a = options(["--parquet", data, "OUT", "--item-key", "book", "--sequence-key", "page"], has_engines=False)
    run.allocate(a, [run.reader(a)])
    assert (a.tasks, a.workers) == (3, 2)


def test_a_pipeline_with_engines_keeps_one_task_and_every_task_at_once(tmp_path):
    from linecaster.runtime import run

    data = write_pages(tmp_path / "data", [2500], row_group_size=1000)
    a = options(["--parquet", data, "OUT", "--rate-limit", "10/1"], has_engines=True)
    run.allocate(a, [run.reader(a)])
    assert (a.tasks, a.workers) == (1, 1)
    a = options(["--parquet", data, "OUT", "--tasks", "4", "--rate-limit", "10/1"], has_engines=True)
    assert run.reader(a)._opener.http["rate_limits"] == [(2, 0.8)]       # 4 tasks at once share 10/s
    run.allocate(a, [run.reader(a)])
    assert (a.tasks, a.workers) == (4, 4)


def test_given_tasks_and_workers_stay_and_divide_the_rate_limits(tmp_path):
    from linecaster.runtime import run

    data = write_pages(tmp_path / "data", [10], row_group_size=10)
    a = options(["--parquet", data, "OUT", "--tasks", "8", "--workers", "2", "--rate-limit", "150/60"],
                has_engines=False)
    assert run.reader(a)._opener.http["rate_limits"] == [(75, 60.0)]
    run.allocate(a, [run.reader(a)])
    assert (a.tasks, a.workers) == (8, 2)


def test_tasks_and_workers_must_be_positive():
    from linecaster.runtime import run

    ap = run.parser(None)
    for flag in ("--tasks", "--workers"):
        with pytest.raises(SystemExit):
            run.check(ap, ap.parse_args(["IMAGES", "OUT", flag, "0"]))


def test_page_mode_is_one_task():
    from linecaster.runtime import run

    a = argparse.Namespace(page="x.png", tasks=None, workers=None)
    run.allocate(a, [])
    assert (a.tasks, a.workers) == (1, 1)


def test_parquet_may_name_one_file(tmp_path):
    from linecaster.runtime import run

    data = write_pages(tmp_path / "data", [3, 2], row_group_size=2)
    a = options(["--parquet", f"{data}/part-1.parquet", "OUT", "--item-key", "book", "--sequence-key", "page"],
                has_engines=False)
    assert [page_of(d).page_id for d in run.reader(a).run()] == ["f1_0001", "f1_0002"]


# ---------------------------------------------------------------- --max-pages: the first N pages of the whole run


def test_first_rows_cuts_the_layout_as_if_the_input_ended_there():
    from linecaster.blocks.readers.tables import first_rows

    layout = [("a.parquet", (4, 4, 2)), ("b.parquet", (3,))]
    assert first_rows(layout, 6) == [("a.parquet", (4, 2))]
    assert first_rows(layout, 11) == [("a.parquet", (4, 4, 2)), ("b.parquet", (1,))]
    assert first_rows(layout, 99) == layout


def test_max_pages_runs_the_first_pages_in_automatic_tasks(tmp_path):
    from linecaster.runtime import run

    data = write_pages(tmp_path / "data", [1500, 1500], row_group_size=700)
    a = options(["--parquet", data, "OUT", "--item-key", "book", "--sequence-key", "page", "--max-pages", "2500",
                 "--rate-limit", "150/60"], has_engines=False)
    reader = run.reader(a)
    run.allocate(a, [reader])
    assert (a.tasks, a.workers) == (3, 1)                    # 2,500 pages in tasks of about 1,000
    ids = [page_of(d).page_id for r in range(3) for d in run.reader(a).run(rank=r, world_size=3)]
    assert ids == [f"f0_{i:04d}" for i in range(1, 1501)] + [f"f1_{i:04d}" for i in range(1, 1001)]


def test_max_pages_takes_the_first_image_files(tmp_path):
    from linecaster.blocks.readers.images import ImageFolderReader

    (tmp_path / "scans").mkdir()
    for i in range(1, 6):
        (tmp_path / "scans" / f"p{i}.png").write_bytes(sample_png())
    ids = [page_of(d).page_id for r in range(2)
           for d in ImageFolderReader(str(tmp_path / "scans"), max_pages=3).run(rank=r, world_size=2)]
    assert sorted(ids) == ["p1", "p2", "p3"]


def test_max_pages_is_for_inputs_whose_pages_are_known_before_reading():
    from linecaster.runtime import run

    ap = run.parser(None)
    for argv in (["--manifests", "m.txt", "OUT", "--max-pages", "5"], ["--parquet", "d", "OUT", "--max-pages", "0"]):
        with pytest.raises(SystemExit):
            run.check(ap, ap.parse_args(argv))
