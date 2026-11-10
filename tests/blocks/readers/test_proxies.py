"""A proxy list (``--proxies``, ``linecaster.net.http.read_proxies``) through the worker's proxy pool
(``linecaster.net.proxies``): proxy files as URLs or in Webshare's formats; a broken proxy left out (after 3 proxy
errors in a row, for 300 s), the attempt retried through another; no proxy usable within max_pause stops the run; credentials never logged. The
proxies here are loopback servers that answer absolute-URI requests themselves (an http proxy's view)."""
import gzip
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from loguru import logger

from linecaster.blocks.base.page import failed, page_of
from linecaster.blocks.readers.images import ImageParquetReader
from linecaster.net.http import close_shared, read_proxies, redact
from linecaster.testing import sample_png

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
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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


def test_a_dead_proxy_is_left_out_and_its_attempts_retried_through_another(tmp_path):
    served = []
    good = proxy_server(served)
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{dead_port()}:user:secret\n"
                                              f"127.0.0.1:{good.server_address[1]}\n")
        lines = []
        sink = logger.add(lines.append, level="DEBUG")
        reader = ImageParquetReader(page_table(tmp_path, 6), item_key="book", sequence_key="page",
                                    http={**FAST, "proxy_file": str(tmp_path / "proxies.txt"),
                                          "per_worker": "share"})      # both held, the dead one's turn first
        try:
            docs = list(reader.run())
        finally:
            logger.remove(sink)
        assert not any(failed(d) for d in docs) and len(docs) == 6
        assert sorted(served) == sorted(f"http://library.test/p{i}.png" for i in range(1, 7))  # all through the good one
        tries = [t for d in docs for t in d.metadata["trace"]["fetch"][0]["tries"]]
        # the dead one: three times in a row, or more often if requests were on their way through it before
        assert tries.count("no-response") >= 3 and tries.count("200") == 6
        assert reader._opener._fetcher.proxy_counts() == (1, 1, 0)            # held, blocked, free
        logged = "".join(str(x) for x in lines)
        assert logged.count("blocked everywhere for 300 s") == 1                           # whatever was on its way
        assert "secret" not in logged and "***@127.0.0.1" in logged
    finally:
        good.shutdown()


def test_no_proxy_left_stops_the_run_and_says_when_one_returns(tmp_path):
    """Every proxy left out for longer than max_pause: the run stops (a ServerError) instead of pausing past it. (A
    broken proxy left out at its first error for an hour: ``broken_after`` 1, ``broken_ttl`` 3600.)"""
    from linecaster.errors import ServerError

    (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{dead_port()}\n127.0.0.1:{dead_port()}\n")
    reader = ImageParquetReader(page_table(tmp_path, 1), item_key="book", sequence_key="page",
                                http={**FAST, "proxy_file": str(tmp_path / "proxies.txt"), "max_pause": 60,
                                      "broken_after": 1, "broken_ttl": 3600})
    with pytest.raises(ServerError, match=r"no proxy left for library\.test: every one is left out \(the first "
                                          r"returns in 59 min"):
        list(reader.run())


def test_the_proxies_option_reaches_the_readers_and_the_run_states_it(tmp_path):
    from linecaster.runtime import run

    (tmp_path / "proxies.txt").write_text("1.2.3.4:8080\n5.6.7.8:8080\n")
    ap = run.parser(None)
    table = page_table(tmp_path, 1)
    a = run.check(ap, ap.parse_args(["--parquet", table, "OUT", "--rate-limit", "150/60",
                                     "--proxies", str(tmp_path / "proxies.txt")]))
    a.has_engines = False
    assert run.reader(a)._opener.http["proxy_file"] == str(tmp_path / "proxies.txt")    # the file, not its lines
    assert run.reader(a)._opener.http["default_broker"] == "OUT/logs/broker"      # shared by workers, runs
    shared = run.check(ap, ap.parse_args(["--parquet", table, "OUT", "--proxies",
                                          str(tmp_path / "proxies.txt"), "--broker", "s3://b/broker"]))
    assert run.reader(shared)._opener.http["broker"] == "s3://b/broker"
    run.allocate(a, [run.reader(a)])                                  # one task: one worker, a fair share: both
    assert run.workers_note(a) == "2 proxies available, 1 task → 1 worker, a fair share each"
    assert run.rate_note(a) == "rate limits per proxy: 150/60 · 2 proxies → up to 300/min at a server"
    (tmp_path / "one.yaml").write_text("proxies: {per_worker: 1}\n")
    one = run.check(ap, ap.parse_args(["--parquet", table, "OUT", "--rate-limit", "150/60", "--proxies",
                                       str(tmp_path / "proxies.txt"), "--http-policy", str(tmp_path / "one.yaml")]))
    one.has_engines = False
    run.allocate(one, [run.reader(one)])                              # one task: one worker, one proxy in use
    assert run.workers_note(one) == "2 proxies available, 1 task → 1 worker, 1 proxy each"
    assert run.rate_note(one).startswith("rate limits per proxy: 150/60 · 1 of 2 proxies in use (1 proxy per "
                                         "worker) → up to 150/min at a server")
    one.workers = one.tasks = 2
    assert run.rate_note(one).startswith("rate limits per proxy: 150/60 · 2 proxies → up to 300/min at a server")
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(["--parquet", "d", "OUT", "--proxies", str(tmp_path / "missing.txt")]))


def test_a_proxy_answered_with_429_and_a_shorter_retry_after_is_left_out_that_long(tmp_path):
    """A 429's Retry-After (30 s) is how long its proxy is blocked at the host, not the doubling from 60 s."""
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
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        (tmp_path / "proxies.txt").write_text("".join(f"127.0.0.1:{s.server_address[1]}\n" for s in servers))
        fetcher = HTTPFetcher.shared(**FAST, proxy_file=str(tmp_path / "proxies.txt"))
        assert fetcher.get("http://library.test/p1.png").status_code == 200
        first, _, _ = fetcher._proxies.outlook("library.test")
        assert 25 < first <= 30 and fetcher.proxy_counts() == (1, 1, 0)       # not 60
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
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{httpd.server_address[1]}\n")
        reader = ImageParquetReader(page_table(tmp_path, 1), item_key="book", sequence_key="page",
                                    http={**FAST, "proxy_file": str(tmp_path / "proxies.txt")})
        reader.max_page_errors = None
        (doc,) = list(reader.run())
        error = doc.metadata["errors"][0]
        assert error["type"] == "MaxRetriesExceeded" and error["error"] == "after 4 attempts: HTTP 520"
        assert doc.metadata["trace"]["fetch"][0]["tries"] == ["520"] * 4                 # max_retries 3: 3 retries
        assert reader._opener._fetcher.proxy_counts() == (1, 0, 0)        # a server error left the proxy in
    finally:
        httpd.shutdown()


def test_no_proxy_usable_pauses_the_requests_until_its_block_ends(tmp_path):
    """The only proxy gets a 429 with Retry-After 1: it is blocked at the host for a second, the request waits (a
    pause, one warning at its start and one at its end) and then comes through it, without using up an attempt."""
    from linecaster.net.http import HTTPFetcher, fetch_record

    body = sample_png()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.path)
            if len(calls) == 1:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=proxy.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    lines = []
    sink = logger.add(lines.append, level="INFO")
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{proxy.server_address[1]}\n")
        fetcher = HTTPFetcher.shared(**{**FAST, "max_retries": 0}, proxy_file=str(tmp_path / "proxies.txt"),
                                     broker=str(tmp_path / "broker"))
        response = fetcher.get("http://library.test/p1.png")
        record = fetch_record(response)
        assert response.status_code == 200 and record["tries"] == ["429", "200"]
        assert 0.5 < record["pause_seconds"] < 3
        logged = "".join(str(x) for x in lines)
        assert logged.count("no proxy usable for library.test") == 1
        assert logged.count("a proxy is usable for library.test again") == 1
    finally:
        logger.remove(sink)
        proxy.shutdown()


@pytest.mark.parametrize("per_worker", [None, 1])
def test_two_workers_share_the_proxies_and_their_rate_limits(tmp_path, monkeypatch, per_worker):
    """A local run with two worker processes through four proxies (one broker): every item comes through, and the
    requests through each proxy keep its rate limit (one per 0.2 s) although both workers send through the proxies.
    A fair share (``share``, the default): the requests are spread over all four; one proxy per worker (``1``): two
    proxies carry the requests, one each."""
    import json
    import time

    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.readers.resources import ResourceReader
    from linecaster.blocks.writers.resources import ResourceFilesWriter, ResourceRecordWriter
    from linecaster.net import proxies as netproxies
    from linecaster.runtime.builder import build
    from linecaster.runtime.local import LocalExecutor

    monkeypatch.setattr(netproxies, "REBALANCE_SECONDS", 0.5)        # the workers are forked: they see these
    monkeypatch.setattr(netproxies, "FILL_SECONDS", 0.2)
    seen: dict[int, list[float]] = {}
    xml = b'<?xml version="1.0"?><record/>'

    def proxy_server(n):
        seen[n] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen[n].append(time.monotonic())
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(xml)))
                self.end_headers()
                self.wfile.write(xml)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return httpd

    servers = [proxy_server(n) for n in range(4)]
    try:
        (tmp_path / "proxies.txt").write_text("".join(f"127.0.0.1:{s.server_address[1]}\n" for s in servers))
        (tmp_path / "items").mkdir()
        items = [f"i{n:02d}" for n in range(24)]
        pq.write_table(pa.table({"lccn": items}), tmp_path / "items" / "p.parquet")
        out = tmp_path / "out"
        reader = ResourceReader(str(tmp_path / "items"), item_key="lccn",
                                templates={"marcxml": "http://catalog.test/{item}/marcxml"},
                                http={**FAST, "proxy_file": str(tmp_path / "proxies.txt"), "rate_limits": [(5, 1)],
                                      "broker": str(tmp_path / "broker"),
                                      **({"per_worker": per_worker} if per_worker else {})})
        plan = build([reader, ResourceFilesWriter(str(out)), ResourceRecordWriter(str(out / "resources"))],
                     tasks=len(items), run_folder=str(out))
        LocalExecutor(plan.stages[0].pipeline, tasks=len(items), workers=2, logging_dir=str(out / "logs"),
                      out=str(out), reader=reader, title="harvest", start_method="fork").run()
        records = [json.loads(line) for p in (out / "resources").iterdir() for line in gzip.open(p, "rt")]
        assert len(records) == len(items) and not any(r.get("error") for r in records)
        assert sum(len(t) for t in seen.values()) == len(items)
        used = [len(t) for t in seen.values() if t]
        if per_worker == 1:
            assert len(used) == 2                          # one proxy per worker: one each, never the same
        else:
            assert len(used) == 4 and min(used) >= 2       # a fair share: spread over the four
        jitter = 0.08                                      # of a request's arrival, on a loaded machine
        for times in seen.values():                        # 0.2 s per proxy: k requests on take at least k * 0.2 s
            assert all(times[j] - times[i] > (j - i) * 0.2 - jitter
                       for i in range(len(times)) for j in range(i + 1, len(times))), times
        workers = sorted(p.name for p in (tmp_path / "broker" / "workers").iterdir())
        assert [w.rsplit("-", 1)[1] for w in workers] == ["0.json", "1.json"]   # the pool's worker indexes
    finally:
        for s in servers:
            s.shutdown()


def test_a_task_that_ends_hands_its_proxies_to_the_next_process_in_its_slot(tmp_path):
    """A Ray task's process ends (``linecaster.runtime.ray.hand_over``): its slot is free, its proxy leases stay, and
    the next process on the machine claims the slot, is the same worker and holds the proxies before its first
    request."""
    from linecaster import broker as brokers
    from linecaster.net.http import HTTPFetcher
    from linecaster.runtime.ray import hand_over

    served = []
    good = proxy_server(served)
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{good.server_address[1]}\n")
        config = {**FAST, "proxy_file": str(tmp_path / "proxies.txt"), "broker": str(tmp_path / "broker")}
        assert HTTPFetcher.shared(**config).get("http://library.test/p1.png").status_code == 200
        worker = brokers.shared(str(tmp_path / "broker")).worker
        hand_over()                                              # the task ends
        assert not list((tmp_path / "broker" / "slots").rglob("*.json"))
        assert len(list((tmp_path / "broker" / "proxies").rglob("leases/*.json"))) == 1
        successor = HTTPFetcher.shared(**config)                 # the next task's process
        assert successor.proxy_counts() == (1, 0, 0) and brokers.shared(str(tmp_path / "broker")).worker == worker
        assert successor.get("http://library.test/p2.png").status_code == 200 and len(served) == 2
    finally:
        good.shutdown()
