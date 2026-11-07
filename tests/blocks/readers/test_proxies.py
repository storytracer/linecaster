"""A proxy list (``--proxies``, ``linecaster.net.http.read_proxies``) through resilient-httpx: proxy files as URLs or
in Webshare's formats; each attempt through the next proxy; a proxy that fails an attempt left out of the rotation
(threshold 1), the attempt retried through another; no proxy left fails the page; credentials never logged. The
proxies here are loopback servers that answer absolute-URI requests themselves (an http proxy's view)."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("pybookget")
pytest.importorskip("resilient_httpx")

from loguru import logger  # noqa: E402

from linecaster.blocks.base.page import failed, page_of  # noqa: E402
from linecaster.blocks.readers.images import ImageParquetReader  # noqa: E402
from linecaster.net.http import close_shared, read_proxies, redact  # noqa: E402
from linecaster.testing import sample_png  # noqa: E402

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 3, "trust_env": False}


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


def proxy_server(served: list):
    """An 'http proxy' that serves every absolute-URI GET itself with a PNG, noting which URL it served."""
    body = sample_png()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            served.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def dead_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def page_table(tmp_path, n):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "data").mkdir()
    pq.write_table(pa.table({"book": ["b"] * n, "page": list(range(1, n + 1)),
                             "image": [f"http://library.test/p{i}.png" for i in range(1, n + 1)]}),
                   tmp_path / "data" / "part-0.parquet")
    return str(tmp_path / "data")


def test_proxy_files_as_urls_or_webshare_lines(tmp_path):
    f = tmp_path / "proxies.txt"
    f.write_text("# Webshare\n1.2.3.4:8080\n5.6.7.8:9000:user:p@ss\n\nsocks5://9.9.9.9:1080  # a URL\n")
    assert read_proxies(str(f)) == ["http://1.2.3.4:8080", "http://user:p%40ss@5.6.7.8:9000", "socks5://9.9.9.9:1080"]
    (tmp_path / "bad.txt").write_text("1.2.3.4\n")
    with pytest.raises(ValueError, match="line 1"):
        read_proxies(str(tmp_path / "bad.txt"))
    assert redact("http://user:secret@5.6.7.8:9000") == "http://***@5.6.7.8:9000"
    assert redact("http://1.2.3.4:8080") == "http://1.2.3.4:8080"


def test_a_dead_proxy_is_left_out_and_its_attempt_retried_through_another(tmp_path):
    served = []
    good = proxy_server(served)
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{dead_port()}:user:secret\n"
                                              f"127.0.0.1:{good.server_address[1]}\n")
        lines = []
        sink = logger.add(lines.append, level="DEBUG")
        reader = ImageParquetReader(page_table(tmp_path, 4), item_key="book", sequence_key="page",
                                    http={**FAST, "proxy_file": str(tmp_path / "proxies.txt")})
        try:
            docs = list(reader.run())
        finally:
            logger.remove(sink)
        assert not any(failed(d) for d in docs) and len(docs) == 4
        assert sorted(served) == [f"http://library.test/p{i}.png" for i in range(1, 5)]   # all through the good one
        tries = [t for d in docs for t in d.metadata["trace"]["fetch"][0]["tries"]]
        assert tries.count("no-response") == 1 and tries.count("200") == 4                 # the dead one, once
        assert reader._opener._fetcher.proxies_in_rotation() == (1, 2)
        logged = "".join(str(x) for x in lines)
        assert "left out for 3600 s" in logged and "secret" not in logged and "***@127.0.0.1" in logged
    finally:
        good.shutdown()


def test_no_proxy_left_stops_the_run_and_says_when_one_returns(tmp_path):
    """Every proxy left out: the run stops (a ServerError) instead of failing every page that follows."""
    from linecaster.errors import ServerError

    (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{dead_port()}\n127.0.0.1:{dead_port()}\n")
    reader = ImageParquetReader(page_table(tmp_path, 1), item_key="book", sequence_key="page",
                                http={**FAST, "proxy_file": str(tmp_path / "proxies.txt")})
    with pytest.raises(ServerError, match=r"no proxy left for library\.test: every one is left out \(the first "
                                          r"returns in 59 min"):
        list(reader.run())


def test_the_proxies_option_reaches_the_readers_and_the_run_states_it(tmp_path):
    from linecaster.runtime import run

    (tmp_path / "proxies.txt").write_text("1.2.3.4:8080\n5.6.7.8:8080\n")
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--parquet", page_table(tmp_path, 1), "OUT", "--rate-limit", "150/60",
                                     "--proxies", str(tmp_path / "proxies.txt")]))
    a.has_engines = False
    assert run.reader(a)._opener.http["proxy_file"] == str(tmp_path / "proxies.txt")    # the file, not its lines
    run.allocate(a, [run.reader(a)])
    assert run.rate_note(a).endswith("through 2 proxies (left out for 3600 s after 1 failure)")
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(["--parquet", "d", "OUT", "--proxies", str(tmp_path / "missing.txt")]))


def test_a_proxy_answered_with_429_and_a_shorter_retry_after_is_left_out_that_long(tmp_path):
    """resilient-httpx's blacklist_ttl_from_retry_after (storytracer's fork): Retry-After 30 instead of an hour."""
    from linecaster.net.http import HTTPFetcher

    body = sample_png()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.path)
            if len(calls) == 1:
                self.send_response(429)
                self.send_header("Retry-After", "30")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        (tmp_path / "proxies.txt").write_text("".join(f"127.0.0.1:{s.server_address[1]}\n" for s in servers))
        fetcher = HTTPFetcher.shared(**FAST, proxy_file=str(tmp_path / "proxies.txt"))
        assert fetcher.get("http://library.test/p1.png").status_code == 200
        ttl = [p["ttl_remaining_seconds"] for pool in fetcher._proxies.blacklist_snapshot().values() for p in pool
               if p["ttl_remaining_seconds"] is not None]
        assert len(ttl) == 1 and 25 < ttl[0] <= 30                     # not 3600
    finally:
        for s in servers:
            s.shutdown()


def test_used_up_retries_and_an_empty_pool_say_what_failed(tmp_path, monkeypatch):
    """A proxy through which the server always answers 520: MaxRetriesExceeded names it, with the attempts traced.
    (No pauses waited out here: the breaker's waits are its own tests'.)"""
    from linecaster.net import http as nethttp

    monkeypatch.setattr(nethttp, "BREAKER_WAITS", 0)
    body = b""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(520)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{httpd.server_address[1]}\n")
        reader = ImageParquetReader(page_table(tmp_path, 1), item_key="book", sequence_key="page",
                                    http={**FAST, "proxy_file": str(tmp_path / "proxies.txt")})
        reader.max_page_errors = None
        (doc,) = list(reader.run())
        error = doc.metadata["errors"][0]
        assert error["type"] == "MaxRetriesExceeded" and error["error"] == "after 3 attempts: HTTP 520"
        assert doc.metadata["trace"]["fetch"][0]["tries"] == ["520", "520", "520"]
        assert reader._opener._fetcher.proxies_in_rotation() == (1, 1)     # a server error left the proxy in
    finally:
        httpd.shutdown()
