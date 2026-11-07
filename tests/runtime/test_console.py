"""The console of a local run (``linecaster.runtime.console``, ``linecaster.runtime.local.LocalExecutor``): human
units; one line naming the pipeline without the builder's boundaries; a line per finished task and a summary; a
progress line from ``Progress`` counting the pages that leave the pipeline; datatrove's pipeline listing and stats
blocks only in the task logs."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from linecaster.runtime import console
from linecaster.runtime.console import Console, Progress, block_label, count, duration, size
from linecaster.testing import sample_png


@pytest.mark.parametrize("seconds, text", [(0, "0s"), (59, "59s"), (308, "5m 08s"), (7380, "2h 03m"),
                                           (277200, "3d 05h")])
def test_duration(seconds, text):
    assert duration(seconds) == text


@pytest.mark.parametrize("n, text", [(512, "512 B"), (58_400, "58.4 kB"), (371_000_000, "371 MB"),
                                     (8_600_000_000_000, "8.6 TB")])
def test_size(n, text):
    assert size(n) == text


def test_count_and_block_labels():
    class Step:
        name = "🖼️ image parquet"

    assert count(28_699_997) == "28,699,997"
    assert block_label(Step()) == "image parquet" and block_label(object()) == "object"


def test_status_shows_progress_rate_size_failures_task_and_time_left(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(console.time, "monotonic", lambda: clock[0])
    c = Console("harvest", tasks=2, total=2000, live=False)
    c.start_task(0)
    for i in range(150):
        clock[0] += 0.4                                     # 150 pages a minute
        c.page(300_000, failed=i == 3)
    status = c.status()
    assert status.startswith("150 / 2,000 pages  8%") and "150/min" in status and "45.0 MB" in status
    assert "1 failed" in status and "task 1/2" in status and "ETA 12m 20s" in status


def test_a_resumed_run_counts_from_what_was_done():
    c = Console("harvest", tasks=4, total=4000, done_pages=2000, done_tasks=2, live=False)
    assert c.status().startswith("2,000 / 4,000 pages  50%") and "task 3/4" in c.status()


def page_table(tmp_path, n):
    (tmp_path / "data").mkdir()
    png = sample_png()
    pq.write_table(pa.table({"book": ["b"] * n, "page": list(range(1, n + 1)), "image": [png] * n}),
                   tmp_path / "data" / "part-0.parquet", row_group_size=4)
    return str(tmp_path / "data")


def test_a_local_run_shows_its_own_lines_and_keeps_datatroves_in_the_task_logs(tmp_path, capsys):
    from linecaster.blocks.readers.images import ImageParquetReader
    from linecaster.blocks.writers.records import PageJsonlWriter
    from linecaster.runtime.builder import build
    from linecaster.runtime.local import LocalExecutor

    out = tmp_path / "out"
    reader = ImageParquetReader(page_table(tmp_path, 10), item_key="book", sequence_key="page")
    plan = build([reader, PageJsonlWriter(str(out / "pages"), output_filename="${rank}.jsonl.gz")],
                 tasks=2, run_folder=str(out), observers=[Progress()])
    LocalExecutor(plan.stages[0].pipeline, tasks=2, workers=1, logging_dir=str(out / "logs"), out=str(out),
                  reader=reader, title="harvest").run()
    err = capsys.readouterr().err
    assert f"harvest → {out}: image parquet → rejects → page records (jsonl) · 10 pages in 2 tasks, 1 worker" in err
    assert "task 1/2 done: 5 pages" in err and "task 2/2 done: 5 pages" in err
    assert "harvest done: 10 pages" in err and "2/2 tasks" in err
    assert "boundary after" not in err and "📉" not in err and "PIPELINE" not in err
    log = (out / "logs" / "logs" / "task_00000.log").read_text()
    assert "PIPELINE" in log and "Stats: Task 0" in log                   # datatrove's, whole, in the task log

    LocalExecutor(plan.stages[0].pipeline, tasks=2, workers=1, logging_dir=str(out / "logs"), out=str(out),
                  reader=reader, title="harvest").run()
    assert "2 done before (10 pages)" in capsys.readouterr().err         # a rerun: listed once, nothing to do


def test_progress_survives_pickling_without_its_counts():
    import pickle

    p = Progress()
    p.on_task_start(3, 8)
    p.pages = 12
    q = pickle.loads(pickle.dumps(p))
    assert q.pages == 0 and q.rank == 0
