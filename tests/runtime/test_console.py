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


def test_with_several_workers_the_console_counts_the_pages_of_every_process(tmp_path, capsys):
    from linecaster.blocks.readers.images import ImageParquetReader
    from linecaster.blocks.writers.records import PageJsonlWriter
    from linecaster.runtime.builder import build
    from linecaster.runtime.local import LocalExecutor

    out = tmp_path / "out"
    reader = ImageParquetReader(page_table(tmp_path, 12), item_key="book", sequence_key="page")
    plan = build([reader, PageJsonlWriter(str(out / "pages"), output_filename="${rank}.jsonl.gz")],
                 tasks=4, run_folder=str(out), observers=[Progress()])
    LocalExecutor(plan.stages[0].pipeline, tasks=4, workers=2, logging_dir=str(out / "logs"), out=str(out),
                  reader=reader, title="harvest").run()
    err = capsys.readouterr().err
    assert "12 pages in 4 tasks, 2 workers" in err
    assert "harvest done: 12 pages" in err and "4/4 tasks" in err      # counted in the workers, summed here


def test_pinned_line_sits_on_the_first_row_above_a_scroll_region():
    import io

    from linecaster.runtime.console import Pinned, bar

    out, size = io.StringIO(), [(24, 40)]
    p = Pinned(out, size=lambda: size[0])
    assert out.getvalue() == "\n\x1b[2;24r\x1b[24;1H"                 # rows 2-24 scroll, the cursor at the bottom
    p.draw("harvest " + "x" * 60)
    assert out.getvalue().endswith("\x1b7\x1b[1;1H\x1b[2K" + ("harvest " + "x" * 60)[:40] + "\x1b8")
    size[0] = (30, 100)                                                # a resized terminal: the region again
    p.draw("harvest")
    assert "\x1b[2;30r" in out.getvalue()
    p.close()
    assert out.getvalue().endswith("\x1b[r\x1b[30;1H")                 # the whole terminal back
    assert bar(0.5, 10) == "█████░░░░░" and bar(2, 4) == "████"


def test_a_live_console_draws_on_the_pinned_line_and_logs_scroll_below(capsys, monkeypatch):
    import os

    from linecaster.runtime import console as module

    monkeypatch.setattr(module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 24)))
    c = Console("harvest", tasks=2, total=100, live=True).open()
    c.page(1000, False)
    c.write("12:00:00 WARNING something\n")
    c.close()
    err = capsys.readouterr().err
    assert "\x1b[2;24r" in err                                        # the region below row 1
    assert "\x1b[1;1H\x1b[2Kharvest ░" in err                       # drawn on row 1
    assert "12:00:00 WARNING something\n" in err                      # written plainly, into the region
    assert err.endswith("\x1b[r\x1b[24;1H")


def test_the_size_counts_what_was_there_before_and_what_is_reused():
    c = Console("harvest", tasks=4, total=40, done_pages=20, done_tasks=2, live=False)
    assert "size …" in c.status()                                   # the finished tasks' size is being read
    c.page(300_000, False, reused=True)
    c.page(200_000, False)
    assert "500 kB + size before …" in c.status()
    c.add_before(10_000_000)
    assert "10.5 MB" in c.status() and "1 reused" in c.status()


def test_size_before_sums_the_readers_media_size_of_finished_tasks(tmp_path):
    import json

    from linecaster.runtime.local import size_before

    stats = tmp_path / "logs" / "stats"
    stats.mkdir(parents=True)
    for rank, total in ((0, 1000), (1, 2500), (2, 7)):
        (stats / f"{rank:05d}.json").write_text(json.dumps([
            {"name": "📖 - READER: 🖼️ image parquet", "stats": {"pages": 3, "media_size": {"total": total, "n": 3}}},
            {"name": "💽 - WRITER: 🖼️ image files", "stats": {"images": 3}}]))
    assert size_before(str(tmp_path / "logs"), {0, 1}) == 3500
    assert size_before(str(tmp_path / "logs"), {0, 1, 9}) == 3500             # a missing file is left out


# ---------------------------------------------------------------- a failed task does not stop the run


def _failing(failing_ranks, error=RuntimeError):
    """A pipeline step that fails on ``failing_ranks``."""
    def step(data, rank=0, world_size=1):
        if rank in failing_ranks:
            raise error("boom")
        yield from ()
    return step


@pytest.mark.parametrize("workers", [1, 2])
def test_a_failed_task_is_logged_and_the_others_go_on(tmp_path, capfd, workers):
    from linecaster.runtime.local import LocalExecutor

    logs = tmp_path / "logs"
    LocalExecutor([_failing({1})], tasks=4, workers=workers, logging_dir=str(logs), out=str(tmp_path),
                  title="harvest").run()
    err = capfd.readouterr().err                                     # a worker process writes to the real stderr
    assert sorted(p.name for p in (logs / "completions").iterdir()) == ["00000", "00002", "00003"]
    if workers == 1:                         # a worker process's line goes to its own stderr (the forkserver's)
        assert "task 2/4 failed: RuntimeError: boom; it runs again on the next launch" in err
    assert "1 task not finished: they run again on the next launch" in err


def test_many_failed_tasks_in_a_row_stop_the_run(tmp_path, monkeypatch):
    from linecaster.runtime import local

    monkeypatch.setattr(local, "FAILED_IN_A_ROW", 2)
    monkeypatch.setattr(local, "_FAILED", [0])
    with pytest.raises(RuntimeError, match="2 tasks in a row failed"):
        local.LocalExecutor([_failing({0, 1, 2, 3})], tasks=4, workers=1, logging_dir=str(tmp_path / "logs"),
                            out=str(tmp_path)).run()


def test_an_error_that_is_not_the_pages_stops_the_run(tmp_path):
    from linecaster.errors import PipelineConfigError
    from linecaster.runtime.local import LocalExecutor

    with pytest.raises(PipelineConfigError):
        LocalExecutor([_failing({0}, PipelineConfigError)], tasks=2, workers=1, logging_dir=str(tmp_path / "logs"),
                      out=str(tmp_path)).run()


def test_retry_failed_runs_finished_tasks_with_rejects_again(tmp_path, capsys):
    from linecaster.runtime.local import LocalExecutor

    ran = tmp_path / "ran"
    ran.mkdir()

    def step(data, rank=0, world_size=1):
        (ran / str(rank)).touch()
        yield from ()

    logs, rejects = tmp_path / "logs", tmp_path / "rejects"
    (logs / "completions").mkdir(parents=True)
    rejects.mkdir()
    for r in range(3):
        (logs / "completions" / f"{r:05d}").touch()
    (rejects / "00001.jsonl").write_text('{"key": "b_0001"}\n')            # task 1 left a failed page
    LocalExecutor([step], tasks=3, workers=1, logging_dir=str(logs), out=str(tmp_path), retry_failed=True).run()
    assert sorted(p.name for p in ran.iterdir()) == ["1"]                    # only the task with rejects
    assert not (rejects / "00001.jsonl").exists()                            # no page failed this time
    assert "1 finished tasks with failed pages run again (--retry-failed)" in capsys.readouterr().err


def test_files_from_earlier_folders_are_counted_per_folder_and_named_in_the_summary():
    """``--reuse-from``: files read from earlier harvests' folders are done, not fetched now (not in the rate), and
    the summary says how many came from each folder, apart from the copies already in OUT."""
    c = Console("harvest", tasks=1, total=6, live=False, unit="files")
    for earlier in ("v1", "v1", "topup", None):
        c.page(100, False, earlier=earlier)
    c.page(100, False, reused=True)
    c.page(100, False)
    assert "6 / 6 files" in c.status() and "3 from earlier folders" in c.status()
    line = c.summary("OUT")
    assert line.startswith("harvest done: 2 files") and "1 reused (already there)" in line
    assert "from earlier folders: 1 from topup, 2 from v1" in line
