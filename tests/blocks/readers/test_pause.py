"""The pause (``linecaster.net.http.Pause``): a status in a host's ``pause_on`` (429 by default) on a direct connection
pauses the fetcher that got it until the response's ``Retry-After`` has passed (or, without one, a wait that doubles
while the status keeps coming), then the request that got it is tried again; requests in flight extend the pause,
never shorten it; other fetchers go on; beyond ``max_pause`` since the last successful response the run stops."""
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linecaster.net.http import HTTPFetcher, Pause, StopRequests, close_shared, retry_after
from linecaster.testing import sample_png

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "trust_env": False}


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


class Clocks:
    """A monotonic clock and a wall clock that move only when told to."""

    def __init__(self):
        self.t, self.wall = 1000.0, 1_800_000_000.0

    def advance(self, seconds: float) -> None:
        self.t += seconds
        self.wall += seconds


def pause(clocks: Clocks, **kwargs) -> Pause:
    return Pause(clock=lambda: clocks.t, wall_clock=lambda: clocks.wall, **kwargs)


def test_retry_after_is_seconds_or_an_http_date():
    now = 1_800_000_000.0
    assert retry_after("120", now) == 120.0 and retry_after(" 0 ", now) == 0.0
    assert retry_after(formatdate(now + 90, usegmt=True), now) == 90.0
    assert retry_after(formatdate(now - 90, usegmt=True), now) == 0.0        # gone by
    assert retry_after(None, now) is None and retry_after("", now) is None and retry_after("soon", now) is None


def test_a_pause_lasts_as_long_as_retry_after_says():
    clocks = Clocks()
    p = pause(clocks)
    p.hit(429, "30", generation=0, host="a.library.test")
    assert p.paused and p.remaining() == 30.0 and p.generation == 1 and p.status == 429
    p2 = pause(clocks)
    p2.hit(429, formatdate(clocks.wall + 45, usegmt=True), generation=0, host="a.library.test")   # an HTTP-date
    assert p2.remaining() == 45.0
    p3 = pause(clocks)
    p3.hit(429, "0", generation=0)                                     # at least PAUSE_MIN_WAIT
    assert p3.remaining() == 1.0
    clocks.advance(30)
    assert not p.paused


def test_without_retry_after_the_wait_doubles_while_the_status_keeps_coming():
    clocks = Clocks()
    p = pause(clocks, first_wait=10, max_wait=40)
    waits = []
    for _ in range(4):
        p.hit(429, None, generation=p.generation)                     # a request sent after the pause before
        waits.append(p.remaining())
        clocks.advance(p.remaining())
    assert waits == [10, 20, 40, 40]
    p.hit(429, "5", generation=p.generation)                          # its own Retry-After: that value
    assert p.remaining() == 5.0
    clocks.advance(5)
    p.answered(p.generation)                                          # answered: the doubling starts again
    p.hit(429, None, generation=p.generation)
    assert p.remaining() == 10


def test_statuses_for_requests_in_flight_extend_the_pause_and_never_shorten_it():
    clocks = Clocks()
    p = pause(clocks, first_wait=10, max_wait=40)
    p.hit(429, "100", generation=0)
    clocks.advance(5)
    p.hit(429, "10", generation=0)                                    # sent before the pause: ends earlier
    assert p.remaining() == 95.0
    p.hit(429, "200", generation=0)                                   # ends later: extends it
    assert p.remaining() == 200.0 and p.generation == 1                # still the same pause
    q = pause(clocks, first_wait=10, max_wait=40)
    q.hit(429, None, generation=0)
    clocks.advance(2)
    q.hit(429, None, generation=0)                                    # in flight: the same wait, not doubled
    assert q.remaining() == 10.0


def test_beyond_max_pause_the_run_stops_and_a_success_starts_the_count_again():
    clocks = Clocks()
    p = pause(clocks, max_total=100)
    p.hit(429, "60", generation=0, host="a.library.test")
    clocks.advance(60)
    p.answered(0)                                                     # sent before the pause: no reset
    with pytest.raises(StopRequests, match="max_pause"):
        p.hit(429, "60", generation=p.generation, host="a.library.test")      # 120 s in all
    p.answered(p.generation)                                          # sent after the pause and answered
    p.hit(429, "60", generation=p.generation)
    assert p.remaining() == 60.0
    with pytest.raises(StopRequests, match="max_pause"):
        pause(clocks, max_total=100).hit(429, "259200", generation=0)  # a pause that alone passes it


def server(script: dict[str, list]):
    """A loopback server: each path answers its ``script`` in turn (a status, or ``(status, retry_after)``; the last
    answer repeats; 200 is a PNG; paths not in it get 200); ``seen`` holds ``(path, monotonic time)`` per request."""
    body, lock, seen, counts = sample_png(), threading.Lock(), [], {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            with lock:
                seen.append((self.path, time.monotonic()))
                n = counts[self.path] = counts.get(self.path, 0) + 1
            answers = script.get(self.path, [200])
            answer = answers[min(n, len(answers)) - 1]
            status, after = answer if isinstance(answer, tuple) else (answer, None)
            if status != 200:
                self.send_response(status)
                if after is not None:
                    self.send_header("Retry-After", str(after))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}", seen


def until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_429_pauses_the_fetcher_and_its_request_is_tried_again():
    """No retries (``max_retries: 0``): the request that got the 429 is still tried again after the pause, and the
    requests submitted during it go out only after it."""
    httpd, base, seen = server({"/a": [(429, 1), 200]})
    fetcher = HTTPFetcher(max_retries=0, **FAST)
    try:
        first = fetcher.submit(base + "/a")
        until(lambda: fetcher.pause.paused)
        hit = seen[0][1]
        later = [fetcher.submit(f"{base}/p{i}") for i in range(3)]
        response = first.result(timeout=10)
        assert response.status_code == 200
        record = response.extensions["linecaster.fetch"]
        assert record["tries"] == ["429", "200"] and record["attempts"] == 2
        assert 0.8 < record["pause_seconds"] < 2.0 and record["wait_seconds"] < 0.5
        assert all(f.result(timeout=10).status_code == 200 for f in later)
        assert all(t - hit > 0.9 for path, t in seen[1:])               # none went out during the pause
        assert not fetcher.pause.paused
    finally:
        fetcher.close()
        httpd.shutdown()


def test_requests_waiting_for_the_rate_limits_when_a_pause_begins_wait_it_out_too():
    """Submitted together with the one that gets the 429: those past the rate limits when the pause begins are held
    after them (``_hold``), so none goes out during the pause."""
    httpd, base, seen = server({"/a": [(429, 1), 200]})
    fetcher = HTTPFetcher(rate_limits=[(2, 0.4)], **FAST)
    try:
        futures = [fetcher.submit(base + "/a"), *(fetcher.submit(f"{base}/p{i}") for i in range(5))]
        assert all(f.result(timeout=10).status_code == 200 for f in futures)
        hit = next(t for path, t in seen if path == "/a")
        assert not [path for path, t in seen if hit + 0.05 < t < hit + 0.9]
        assert len(seen) == 7
    finally:
        fetcher.close()
        httpd.shutdown()


def test_a_429_to_one_fetcher_does_not_pause_another():
    httpd, base, seen = server({"/a": [(429, 1), 200]})
    paused, other = HTTPFetcher(**FAST), HTTPFetcher(**FAST)          # two workers' fetchers
    try:
        first = paused.submit(base + "/a")
        until(lambda: paused.pause.paused)
        t = time.monotonic()
        response = other.get(base + "/b")
        assert response.status_code == 200 and time.monotonic() - t < 0.5
        assert "pause_seconds" not in response.extensions["linecaster.fetch"]   # only a fetch that paused has it
        assert paused.pause.paused and not other.pause.paused
        assert first.result(timeout=10).status_code == 200
    finally:
        paused.close()
        other.close()
        httpd.shutdown()


def test_without_retry_after_the_fetcher_waits_its_own_doubling_waits():
    httpd, base, _ = server({"/a": [429, 429, 200]})
    fetcher = HTTPFetcher(pause_wait=0.2, pause_max_wait=1.0, **FAST)
    try:
        record = fetcher.get(base + "/a").extensions["linecaster.fetch"]
        assert record["tries"] == ["429", "429", "200"]
        assert 0.5 < record["pause_seconds"] < 1.5                        # 0.2 s, then 0.4 s
    finally:
        fetcher.close()
        httpd.shutdown()


def test_a_fetcher_that_would_pause_beyond_max_pause_stops_the_run():
    httpd, base, _ = server({"/a": [429]})
    fetcher = HTTPFetcher(pause_wait=0.2, pause_max_wait=1.0, max_pause=0.5, **FAST)
    try:
        with pytest.raises(StopRequests, match="max_pause"):
            fetcher.get(base + "/a")                                       # 0.2 s, then 0.4 s would pass 0.5 s
    finally:
        fetcher.close()
        httpd.shutdown()


def test_pause_on_empty_leaves_a_429_to_the_retries():
    httpd, base, seen = server({"/a": [429]})
    fetcher = HTTPFetcher(pause_on=[], max_retries=1, **FAST)
    try:
        with pytest.raises(Exception, match="429"):
            fetcher.get(base + "/a")
        assert len(seen) == 2 and not fetcher.pause.paused
    finally:
        fetcher.close()
        httpd.shutdown()


def test_a_page_waits_out_a_pause_instead_of_failing(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.base.page import failed
    from linecaster.blocks.readers.images import ImageParquetReader

    httpd, base, _ = server({"/p1.png": [(429, 1), 200]})
    try:
        (tmp_path / "data").mkdir()
        pq.write_table(pa.table({"book": ["b"] * 3, "page": [1, 2, 3],
                                 "image": [f"{base}/p{i}.png" for i in range(3)]}), tmp_path / "data" / "p.parquet")
        reader = ImageParquetReader(str(tmp_path / "data"), item_key="book", sequence_key="page",
                                    http={**FAST, "max_retries": 0})
        docs = list(reader.run())
        assert len(docs) == 3 and not any(failed(d) for d in docs)
    finally:
        httpd.shutdown()
