"""Requests ahead: ``linecaster.net.http.prefetched`` keeps a window of submitted entries in order and cancels what
is left when the consumer stops; ``ImageParquetReader`` uses it for ``http(s)://`` images, so a task keeps up to
``prefetch`` requests in flight (1: one at a time) and its pages keep the rows' order; ``--prefetch`` reaches it."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linecaster.blocks.base.page import page_of
from linecaster.blocks.readers.images import ImageParquetReader
from linecaster.errors import PipelineConfigError
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
    """Images ``/<name>.png`` after a delay, counting the requests in flight; ``/missing.png`` is a 404."""
    state = {"in_flight": 0, "max_in_flight": 0, "requests": [], "lock": threading.Lock()}
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
                time.sleep(0.15)
                if self.path == "/missing.png":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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


def test_a_failed_image_fails_at_its_page_after_the_pages_before(slow_server, tmp_path):
    names = ["p1", "p2", "missing", "p4", "p5", "p6", "p7", "p8"]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST, prefetch=3)
    import httpx

    got = []
    with pytest.raises(httpx.HTTPStatusError):
        for doc in reader.run():
            got.append(page_of(doc).page_id)
    assert got == ["b_0001", "b_0002"]
    assert "/p8.png" not in slow_server["requests"]          # nothing requested beyond the window


def test_prefetch_option_reaches_the_parquet_reader(tmp_path):
    from linecaster.runtime import run

    ap = run.parser(None)
    reader = run.reader(run.check(ap, ap.parse_args(["--parquet", str(tmp_path), "OUT", "--prefetch", "3"])))
    assert isinstance(reader, ImageParquetReader) and reader.prefetch == 3
    with pytest.raises(PipelineConfigError):
        ImageParquetReader(str(tmp_path), prefetch=0)
