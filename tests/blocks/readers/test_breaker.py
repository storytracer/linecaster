"""The breaker (``linecaster.net.http.Breaker``): a fetcher pauses while its server fails (most recent attempts got a
5xx), sends a probe after a wait that doubles while the server keeps failing, and goes on with the first answer that is
not a server error; a reader's pages are delayed through an outage, not failed."""
import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("pybookget")

from linecaster.net import http as nethttp  # noqa: E402
from linecaster.net.http import Breaker, close_shared  # noqa: E402
from linecaster.testing import sample_png  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


@pytest.fixture
def quick(monkeypatch):
    """A breaker that opens after 4 attempts and probes after 0.3 s (0.6 s, ...)."""
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


def test_pages_wait_out_an_outage_instead_of_failing(quick, tmp_path, monkeypatch):
    """The server answers 520 for 0.8 s; every page arrives, none failed."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.base.page import failed
    from linecaster.blocks.readers.images import ImageParquetReader

    body, start = sample_png(), time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if time.monotonic() - start < 0.8:
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
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        (tmp_path / "data").mkdir()
        pq.write_table(pa.table({"book": ["b"] * 6, "page": list(range(1, 7)),
                                 "image": [f"{base}/p{i}.png" for i in range(6)]}), tmp_path / "data" / "p.parquet")
        reader = ImageParquetReader(str(tmp_path / "data"), item_key="book", sequence_key="page",
                                    http={"retry_wait_min": 0.05, "retry_wait_max": 0.1, "max_retries": 3,
                                          "trust_env": False})
        docs = list(reader.run())
        assert len(docs) == 6 and not any(failed(d) for d in docs)
        assert not reader._opener._fetcher.breaker.paused
    finally:
        httpd.shutdown()
