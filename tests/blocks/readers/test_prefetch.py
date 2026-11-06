"""Requests ahead: ``linecaster.net.http.prefetched`` keeps a window of submitted entries in order and cancels what
is left when the consumer stops; ``ImageParquetReader`` uses it for ``http(s)://`` images, so a task keeps up to
``prefetch`` requests in flight (1: one at a time) and its pages keep the rows' order; ``--prefetch`` reaches it.
An image that cannot be read is that page's error (no image, ``doc.metadata["errors"]``), the task goes on within
its error budget, and ``ImageFilesWriter`` passes such a page through without a file."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linecaster.blocks.base.page import failed, page_of
from linecaster.blocks.readers.images import ImageParquetReader
from linecaster.errors import PageError, PipelineConfigError
from linecaster.net.http import prefetched
from linecaster.testing import sample_png

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 1, "trust_env": False}  # no proxy from the environment


class Handle:
    def __init__(self, entry):
        self.entry, self.cancelled = entry, False


def test_prefetched_keeps_order_and_a_window_of_submitted_entries():
    submitted, taken = [], []

    def submit(entry):
        submitted.append(entry)
        return Handle(entry)

    for handle in prefetched(range(10), submit, 3, lambda h: None):
        taken.append(handle.entry)
        assert len(submitted) - len(taken) <= 2          # the one taken plus at most prefetch - 1 ahead
    assert taken == list(range(10))


def test_prefetch_one_submits_each_entry_after_the_one_before_is_taken():
    submitted = []

    def submit(entry):
        submitted.append(entry)
        return Handle(entry)

    for handle in prefetched(range(5), submit, 1, lambda h: None):
        assert submitted[-1] == handle.entry


def test_stopping_early_cancels_the_window_and_closes_the_entries():
    handles, closed = [], []

    def entries():
        try:
            yield from range(100)
        finally:
            closed.append(True)

    def submit(entry):
        handles.append(Handle(entry))
        return handles[-1]

    gen = prefetched(entries(), submit, 4, lambda h: setattr(h, "cancelled", True))
    assert next(gen).entry == 0
    gen.close()
    assert [h.entry for h in handles if h.cancelled] == [1, 2, 3] and closed == [True]


def test_prefetch_must_be_at_least_one():
    with pytest.raises(ValueError):
        list(prefetched([1], Handle, 0, lambda h: None))


# ---------------------------------------------------------------- ImageParquetReader over http(s)

pytest.importorskip("pybookget")


@pytest.fixture
def slow_server():
    """Images ``/<name>.png`` after ``state["delay"]`` seconds, counting the requests in flight; ``/missing.png`` is a
    404, ``/html.png`` an HTML page sent with 200."""
    state = {"in_flight": 0, "max_in_flight": 0, "requests": [], "lock": threading.Lock(), "delay": 0.15}
    body = sample_png()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            with state["lock"]:
                state["in_flight"] += 1
                state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
                state["requests"].append(self.path)
            try:
                time.sleep(state["delay"])
                if self.path == "/missing.png":
                    self.send_response(404)
                    self.end_headers()
                    return
                data, ctype = (b"<html>busy</html>", "text/html") if self.path == "/html.png" else (body, "image/png")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                with state["lock"]:
                    state["in_flight"] -= 1

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def page_table(tmp_path, base, names):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "data").mkdir()
    pq.write_table(pa.table({"book": ["b"] * len(names), "page": list(range(1, len(names) + 1)),
                             "image": [f"{base}/{n}.png" for n in names]}), tmp_path / "data" / "part-0.parquet")
    return str(tmp_path / "data")


@pytest.mark.parametrize("prefetch", [1, 4])
def test_http_images_in_a_page_table_are_requested_ahead_in_order(slow_server, tmp_path, prefetch):
    names = [f"p{i}" for i in range(12)]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST, prefetch=prefetch)
    pages = [page_of(d) for d in reader.run()]
    assert [p.page_id for p in pages] == [f"b_{i:04d}" for i in range(1, 13)]
    assert [p.image.uri for p in pages] == [f"{slow_server['base']}/{n}.png" for n in names]
    assert slow_server["max_in_flight"] == (1 if prefetch == 1 else prefetch)


def test_an_image_that_cannot_be_read_is_that_pages_error_and_the_task_goes_on(slow_server, tmp_path):
    names = ["p1", "missing", "p3", "html", "p5"]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST, prefetch=3)
    docs = list(reader.run())
    assert [page_of(d).page_id for d in docs] == [f"b_{i:04d}" for i in range(1, 6)]
    assert [failed(d) for d in docs] == [False, True, False, True, False]
    assert [bool(d.media) for d in docs] == [True, False, True, False, True]
    missing, html = docs[1], docs[3]
    entry = missing.metadata["errors"][0]
    assert (entry["block"], entry["field"], entry["raw_value"]) == (
        "ImageParquetReader", "image", f"{slow_server['base']}/missing.png")
    assert entry["type"] == "HTTPStatusError" and html.metadata["errors"][0]["raw_value"].endswith("/html.png")
    page = page_of(missing)
    assert (page.item_id, page.sequence, page.image.uri) == ("b", 2, f"{slow_server['base']}/missing.png")
    assert reader.stats["image_errors"].total == 2 and reader.stats["pages"].total == 3


def test_more_failed_images_than_the_error_budget_fail_the_task(slow_server, tmp_path):
    slow_server["delay"] = 0
    names = ["missing"] * 120
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST, prefetch=16)
    reader.max_page_errors = 0.5                     # the builder sets it from --max-page-errors
    got = []
    with pytest.raises(PageError, match="more than the error budget"):
        for doc in reader.run():
            got.append(doc)
    assert len(got) == 99                            # judged from page 100 on (ERROR_GRACE)


def test_image_files_writer_passes_a_failed_page_through_without_a_file(slow_server, tmp_path):
    from linecaster.blocks.writers.images import ImageFilesWriter

    slow_server["delay"] = 0
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], ["p1", "missing", "p3"]),
                                item_key="book", sequence_key="page", http=FAST)
    writer = ImageFilesWriter(str(tmp_path / "images"))
    docs = list(writer.run(reader.run()))
    assert [failed(d) for d in docs] == [False, True, False]
    assert sorted(p.name for p in (tmp_path / "images" / "b").iterdir()) == ["b_0001.png", "b_0003.png"]
    assert page_of(docs[1]).image.uri == f"{slow_server['base']}/missing.png"      # still the source, no copy
    assert writer.stats["skipped_after_error"].total == 1 and writer.stats["images"].total == 2


def test_a_harvest_with_a_dead_link_finishes_with_the_page_in_records_and_rejects(slow_server, tmp_path):
    """The harvest stage's blocks as the builder runs them (with its RejectWriter): the task completes."""
    import gzip
    import json

    from datatrove.executor import LocalPipelineExecutor

    from linecaster.blocks.writers.images import ImageFilesWriter
    from linecaster.blocks.writers.records import PageJsonlWriter
    from linecaster.runtime.builder import build

    slow_server["delay"] = 0
    out = tmp_path / "out"
    plan = build([ImageParquetReader(page_table(tmp_path, slow_server["base"], ["p1", "missing", "p3"]),
                                     item_key="book", sequence_key="page", http=FAST),
                  ImageFilesWriter(str(out / "images")),
                  PageJsonlWriter(str(out / "pages"), output_filename="${rank}.jsonl.gz")], run_folder=str(out))
    assert [type(b).__name__ for b in plan.stages[0].blocks][:3] == ["ImageParquetReader", "RejectWriter",
                                                                     "ImageFilesWriter"]
    LocalPipelineExecutor(pipeline=plan.stages[0].pipeline, tasks=1, logging_dir=str(out / "logs")).run()

    assert sorted(p.name for p in (out / "images" / "b").iterdir()) == ["b_0001.png", "b_0003.png"]
    with gzip.open(out / "pages" / "00000.jsonl.gz", "rt") as f:
        rows = [json.loads(line) for line in f]
    assert [r["id"] for r in rows] == ["b_0001", "b_0002", "b_0003"]
    assert [bool(r.get("errors")) for r in rows] == [False, True, False]
    rejects = [json.loads(line) for p in (out / "rejects").rglob("*") if p.is_file()
               for line in (gzip.open(p, "rt") if p.suffix == ".gz" else open(p))]
    assert [(r["key"], r["field"], r["raw_value"]) for r in rejects] == [
        ("b_0002", "image", f"{slow_server['base']}/missing.png")]
    assert (out / "logs" / "completions" / "00000").exists()             # the task finished


def test_prefetch_option_reaches_the_parquet_reader(tmp_path):
    from linecaster.runtime import run

    ap = run.parser(None)
    reader = run.reader(run.check(ap, ap.parse_args(["--parquet", str(tmp_path), "OUT", "--prefetch", "3"])))
    assert isinstance(reader, ImageParquetReader) and reader.prefetch == 3
    with pytest.raises(PipelineConfigError):
        ImageParquetReader(str(tmp_path), prefetch=0)
