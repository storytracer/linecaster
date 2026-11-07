"""Requests ahead: ``linecaster.net.http.prefetched`` keeps a window of submitted entries in order, sizes it itself
(it grows while the first request is not done and none waits for the rate limits) and cancels what is left when the
consumer stops; ``ImageParquetReader`` uses it for ``http(s)://`` images, so one task keeps its rate limits busy and
its pages keep the rows' order. The fetcher is shared per process and configuration, so the limits hold across tasks.
An image that cannot be read is that page's error (no image, ``doc.metadata["errors"]``), the task goes on within
its error budget, and ``ImageFilesWriter`` passes such a page through without a file."""
import threading
import time
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linecaster.blocks.base.page import failed, page_of
from linecaster.blocks.readers.images import ImageParquetReader
from linecaster.errors import PageError
from linecaster.net.http import MAX_AHEAD, divided, prefetched
from linecaster.testing import sample_png

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 1, "trust_env": False}  # no proxy from the environment


class Handle(Future):
    """A future that is done as soon as it is submitted (an entry read at once)."""

    def __init__(self, entry):
        super().__init__()
        self.entry, self.cancelled_ = entry, False
        self.set_result(entry)


class FakeFetcher:
    def __init__(self, waiting=0, max_ahead=MAX_AHEAD):
        self.waiting, self.ahead, self.max_ahead = waiting, 1, max_ahead


def test_without_a_fetcher_each_entry_is_submitted_after_the_one_before_is_taken():
    submitted = []

    def submit(entry):
        submitted.append(entry)
        return Handle(entry)

    taken = []
    for handle in prefetched(range(5), submit, lambda h: None):
        assert submitted[-1] == handle.entry
        taken.append(handle.entry)
    assert taken == list(range(5))


def slow_handles(seconds):
    """``submit`` for handles that are done ``seconds`` after they were submitted."""
    def submit(entry):
        h = Future()
        h.entry = entry
        threading.Timer(seconds, h.set_result, [entry]).start()
        return h
    return submit


def test_the_window_grows_while_nothing_waits_for_the_rate_limits_and_keeps_order():
    fetcher = FakeFetcher(waiting=0)
    taken = [h.entry for h in prefetched(range(40), slow_handles(0.3), lambda h: None, fetcher=lambda: fetcher)]
    assert taken == list(range(40))
    assert fetcher.ahead > 2                   # it grew while the first request was out, and keeps what it learned


def test_the_window_does_not_grow_while_requests_wait_for_the_rate_limits():
    fetcher = FakeFetcher(waiting=1)
    submitted = []

    def submit(entry):
        submitted.append(entry)
        return slow_handles(0.1)(entry)

    for handle in prefetched(range(5), submit, lambda h: None, fetcher=lambda: fetcher):
        assert submitted[-1] == handle.entry   # one at a time: the limits are busy anyway
    assert fetcher.ahead == 1


def test_the_window_starts_at_what_the_fetcher_learned_and_stops_at_max_ahead():
    fetcher = FakeFetcher(waiting=1)
    fetcher.ahead = 7
    submitted, gaps = [], []

    def submit(entry):
        submitted.append(entry)
        return slow_handles(0.05)(entry)

    for handle in prefetched(range(20), submit, lambda h: None, fetcher=lambda: fetcher):
        gaps.append(len(submitted) - handle.entry)
    assert max(gaps) == 7
    assert MAX_AHEAD >= 64


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

    fetcher = FakeFetcher(waiting=1)
    fetcher.ahead = 4
    gen = prefetched(entries(), submit, lambda h: setattr(h, "cancelled_", True), fetcher=lambda: fetcher)
    assert next(gen).entry == 0
    gen.close()
    assert [h.entry for h in handles if h.cancelled_] == [1, 2, 3] and closed == [True]


@pytest.mark.parametrize("limits, tasks, share", [
    ([(150, 60)], 1, [(150, 60.0)]),
    ([(150, 60), (3, 1)], 2, [(75, 60.0), (1, 2 / 3)]),
    ([(5, 4)], 3, [(1, 2.4)]),
])
def test_divided_gives_each_task_its_share_of_the_rate_limits(limits, tasks, share):
    got = divided(limits, tasks)
    assert [n for n, _ in got] == [n for n, _ in share]
    assert [s for _, s in got] == pytest.approx([s for _, s in share])
    for (n, s), (total_n, total_s) in zip(got, limits):     # together: the same average rate, no more
        assert tasks * n / s == pytest.approx(total_n / total_s)


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
                state.setdefault("agents", []).append(self.headers.get("User-Agent"))
            try:
                time.sleep(state["delay"])
                if self.path == "/trickle.png" and state.setdefault("trickled", 0) < 1:
                    state["trickled"] += 1                 # the first attempt sends its bytes slowly
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    for i in range(len(body)):
                        self.wfile.write(body[i:i + 1])
                        self.wfile.flush()
                        time.sleep(0.05)
                    return
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


@pytest.fixture(autouse=True)
def fresh_fetchers():
    """Each test its own shared fetchers (they keep the rate limits and the window they learned)."""
    from linecaster.net.http import close_shared

    close_shared()
    yield
    close_shared()


def test_http_images_in_a_page_table_are_requested_ahead_in_order(slow_server, tmp_path):
    names = [f"p{i}" for i in range(12)]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST)
    pages = [page_of(d) for d in reader.run()]
    assert [p.page_id for p in pages] == [f"b_{i:04d}" for i in range(1, 13)]
    assert [p.image.uri for p in pages] == [f"{slow_server['base']}/{n}.png" for n in names]
    assert slow_server["max_in_flight"] > 1                # without rate limits it grows while the server is slow


def test_one_task_keeps_its_rate_limit_busy_without_a_setting(slow_server, tmp_path):
    """20 requests per second against a server that takes 0.3 s: one at a time would manage about 3 per second."""
    slow_server["delay"] = 0.3
    names = [f"p{i}" for i in range(40)]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http={**FAST, "rate_limits": [(20, 1)]})
    t = time.perf_counter()
    pages = [page_of(d) for d in reader.run()]
    elapsed = time.perf_counter() - t
    assert sorted(p.page_id for p in pages) == [f"b_{i:04d}" for i in range(1, 41)]
    assert elapsed < 5                                     # 40 at 20/s: about 2 s plus the ramp, not 12 s
    assert slow_server["max_in_flight"] >= 4


def test_the_rate_limits_hold_across_tasks_that_run_one_after_the_other(slow_server, tmp_path):
    """Two tasks of one worker share the fetcher: 2 + 2 requests within a 2-per-second limit take over a second."""
    slow_server["delay"] = 0
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], ["p1", "p2", "p3", "p4"]),
                                item_key="book", sequence_key="page", http={**FAST, "rate_limits": [(2, 1)]})
    t = time.perf_counter()
    first = [page_of(d).page_id for d in reader.run(rank=0, world_size=2)]
    second = [page_of(d).page_id for d in reader.run(rank=1, world_size=2)]
    assert (first, second) == (["b_0001", "b_0002"], ["b_0003", "b_0004"])
    assert time.perf_counter() - t >= 0.9


def test_an_image_that_cannot_be_read_is_that_pages_error_and_the_task_goes_on(slow_server, tmp_path):
    names = ["p1", "missing", "p3", "html", "p5"]
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], names), item_key="book",
                                sequence_key="page", http=FAST)
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
                                sequence_key="page", http=FAST)
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


def test_there_is_no_prefetch_option(tmp_path):
    from linecaster.runtime import run

    ap = run.parser(None)
    with pytest.raises(SystemExit):
        ap.parse_args(["--parquet", str(tmp_path), "OUT", "--prefetch", "3"])
    with pytest.raises(TypeError):
        ImageParquetReader(str(tmp_path), prefetch=3)


def test_a_response_that_trickles_is_cut_and_retried_so_the_pages_behind_it_go_on(slow_server, tmp_path):
    """The first attempt at ``trickle.png`` sends a byte every 50 ms; past its deadline it is cut and fetched again."""
    slow_server["delay"] = 0
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], ["p1", "trickle", "p3"]), item_key="book",
                                sequence_key="page", http={**FAST, "max_retries": 2, "attempt_timeout": 0.5})
    t = time.perf_counter()
    docs = list(reader.run())
    assert not any(failed(d) for d in docs) and time.perf_counter() - t < 3
    slow = next(d for d in docs if page_of(d).page_id == "b_0002")
    fetch = slow.metadata["trace"]["fetch"][0]
    assert fetch["attempts"] == 2 and fetch["status"] == 200 and fetch["tries"] == ["200-cut", "200"]
    assert page_of(docs[-1]).page_id == "b_0002"              # the others went on while it was retried


def test_bulk_defaults_carry_a_deadline_per_attempt():
    from linecaster.net.http import HTTP_DEFAULTS

    assert HTTP_DEFAULTS["attempt_timeout"] == 15.0 and HTTP_DEFAULTS["attempt_min_rate"] == 50_000


def test_unordered_a_slow_handle_holds_back_only_itself():
    delays = {0: 0.6}

    def submit(entry):
        h = Future()
        h.entry = entry
        threading.Timer(delays.get(entry, 0.02), h.set_result, [entry]).start()
        return h

    fetcher = FakeFetcher(waiting=0)
    taken = [h.entry for h in prefetched(range(10), submit, lambda h: None, fetcher=lambda: fetcher, ordered=False)]
    assert sorted(taken) == list(range(10)) and taken[-1] == 0


def test_max_ahead_is_the_rate_times_the_deadline():
    from linecaster.net.http import HTTPFetcher

    limited = HTTPFetcher(**FAST, rate_limits=[(150, 60), (3, 1)])            # 2.5/s, 15 s per attempt
    unlimited = HTTPFetcher(**FAST)
    try:
        assert limited.max_ahead == 38 and unlimited.max_ahead == MAX_AHEAD
    finally:
        limited.close()
        unlimited.close()


def test_a_random_user_agent_is_new_for_each_task(slow_server, tmp_path, monkeypatch):
    import fake_useragent

    agents = iter(["agent-1", "agent-2", "agent-3", "agent-4"])

    class FakeAgents:
        @property
        def random(self):
            return next(agents)

    monkeypatch.setattr(fake_useragent, "UserAgent", FakeAgents)
    slow_server["delay"] = 0
    reader = ImageParquetReader(page_table(tmp_path, slow_server["base"], ["p1", "p2", "p3", "p4"]), item_key="book",
                                sequence_key="page", http={**FAST, "use_fake_user_agent": True})
    for rank in range(2):
        list(reader.run(rank=rank, world_size=2))
    by_task = slow_server["agents"][:2], slow_server["agents"][2:]
    assert len(set(by_task[0])) == 1 and len(set(by_task[1])) == 1 and by_task[0][0] != by_task[1][0]
