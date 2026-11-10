"""The breaker (``linecaster.net.http.Breaker``): a fetcher pauses while its server fails (most recent attempts got a
5xx), sends a probe after a wait that doubles while the server keeps failing, and goes on with the first answer that is
not a server error; a reader's pages are delayed through an outage, not failed."""
import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linecaster.net import http as nethttp
from linecaster.net.http import Breaker, close_shared
from linecaster.testing import sample_png


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


@pytest.fixture
def quick(monkeypatch):
    """A breaker that opens after 4 attempts and probes after 0.3 s (0.6 s, ...); the waits only make the tests
    quick, the outcomes do not depend on them."""
    monkeypatch.setattr(nethttp, "BREAKER_MIN_ATTEMPTS", 4)
    monkeypatch.setattr(nethttp, "BREAKER_FIRST_WAIT", 0.3)
    monkeypatch.setattr(nethttp, "BREAKER_MAX_WAIT", 1.0)


def test_it_opens_when_most_recent_attempts_got_server_errors(quick):
    b = Breaker()
    for status in (200, 520, 502, 200):
        b.record(status)
    assert b.paused                                       # 2 of 4: half
    b2 = Breaker()
    for status in (200, 200, 404, 520):
        b2.record(status)
    assert not b2.paused                                  # 1 of 4: a single error is retried, not paused for


def test_a_probe_goes_out_after_the_wait_and_its_answer_decides(quick):
    b = Breaker()
    for _ in range(4):
        b.record(520)

    async def turn():
        t = time.monotonic()
        await b.wait_turn()
        return time.monotonic() - t

    assert 0.2 < asyncio.run(turn()) < 1.0               # the probe, after the first wait
    b.record(520)                                         # the probe failed: the wait doubles
    assert b.paused and 0.4 < b.next_try() <= 0.6
    assert 0.4 < asyncio.run(turn()) < 1.2
    b.record(200)                                         # answered: closed
    assert not b.paused and asyncio.run(turn()) < 0.05


def test_it_opens_after_as_many_server_errors_in_a_row_as_a_request_has_retries():
    b = Breaker(in_a_row=3)
    for status in (520, 502):
        b.record(status)
    assert not b.paused
    b.record(200)                                         # an answer breaks the run
    for status in (500, 503):
        b.record(status)
    assert not b.paused
    b.record(520)                                         # three in a row: a request alone would now have failed
    assert b.paused


@pytest.fixture
def fast(monkeypatch):
    """Like ``quick``, with waits of a few milliseconds: the outage tests count requests, they do not time them."""
    monkeypatch.setattr(nethttp, "BREAKER_MIN_ATTEMPTS", 4)
    monkeypatch.setattr(nethttp, "BREAKER_FIRST_WAIT", 0.01)
    monkeypatch.setattr(nethttp, "BREAKER_MAX_WAIT", 0.02)
    monkeypatch.setattr(nethttp, "BREAKER_POLL", 0.01)


def failing_server(failures: int):
    """A server whose first ``failures`` requests get 520 and the rest a PNG: counted, not timed."""
    body, lock, seen = sample_png(), threading.Lock(), [0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            with lock:
                seen[0] += 1
                fail = seen[0] <= failures
            if fail:
                self.send_response(520)
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
    return httpd, seen


def harvest(tmp_path, base: str, pages: int):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.readers.images import ImageParquetReader

    (tmp_path / "data").mkdir()
    pq.write_table(pa.table({"book": ["b"] * pages, "page": list(range(1, pages + 1)),
                             "image": [f"{base}/p{i}.png" for i in range(pages)]}), tmp_path / "data" / "p.parquet")
    reader = ImageParquetReader(str(tmp_path / "data"), item_key="book", sequence_key="page",
                                http={"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 2, "trust_env": False})
    return reader, list(reader.run())


@pytest.mark.parametrize("pages, failures", [(1, 3), (1, 7), (6, 6), (6, 11)])
def test_pages_wait_out_an_outage_instead_of_failing(fast, tmp_path, pages, failures):
    """However the requests interleave, every retry that runs out does so after at least three server errors in a
    row, so in a pause, and waits it out: no page fails. One page alone was the race (its three attempts used up
    before the breaker had seen enough of them)."""
    from linecaster.blocks.base.page import failed

    httpd, seen = failing_server(failures)
    try:
        reader, docs = harvest(tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}", pages)
        assert len(docs) == pages and not any(failed(d) for d in docs)
        assert seen[0] >= failures + pages                     # every failure answered, then every page
        assert not reader._opener._fetcher.breaker.paused
    finally:
        httpd.shutdown()


def test_a_url_that_keeps_failing_still_fails_after_its_waits(fast, tmp_path, monkeypatch):
    """A server that never recovers: the request waits out ``BREAKER_WAITS`` pauses, then its page fails."""
    from linecaster.blocks.base.page import failed

    monkeypatch.setattr(nethttp, "BREAKER_WAITS", 2)
    httpd, seen = failing_server(10**6)
    try:
        reader, docs = harvest(tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}", 1)
        assert failed(docs[0]) and docs[0].metadata["errors"][0]["type"] == "HTTPStatusError"
    finally:
        httpd.shutdown()


def test_a_request_waits_out_an_outage_its_errors_opened_although_a_probe_closed_it_since(monkeypatch):
    """The race behind the outage test's flaky page: the request's last server error opened the breaker, and another
    request's probe was answered (closing it) before that error got back to the fetch. The fetch tries again (the
    breaker opened during its attempts), instead of failing with the 520."""
    import httpx

    from linecaster.net.http import HTTPFetcher

    fetcher = HTTPFetcher(trust_env=False)
    calls = []

    async def attempts(self, url, fallback_url=None, expect=None):
        request = httpx.Request("GET", url)
        calls.append(url)
        if len(calls) == 1:
            for _ in range(fetcher.breaker.in_a_row):
                fetcher.breaker.record(520)                       # this request's errors open the breaker ...
            fetcher.breaker._probe = time.monotonic()
            fetcher.breaker.record(200)                           # ... and a probe's answer closes it again
            assert not fetcher.breaker.paused
            raise httpx.HTTPStatusError("520", request=request, response=httpx.Response(520, request=request))
        return httpx.Response(200, request=request)

    monkeypatch.setattr(HTTPFetcher, "_attempts", attempts)
    try:
        assert fetcher.get("http://127.0.0.1:9/x").status_code == 200 and len(calls) == 2
    finally:
        fetcher.close()
