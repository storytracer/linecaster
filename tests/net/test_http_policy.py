"""The HTTP policy's behavior (``linecaster.net.http``, ``linecaster.net.proxies``, ``linecaster.net.policy``), each case
on both paths, direct and through proxies, without a policy file: an HTML page where an image was expected (a soft
404), a 503 maintenance page in HTML, a redirect to an HTML login page, sporadic 500s, a slow server past the deadline
per attempt, a 429 without ``Retry-After`` and with one (seconds and an HTTP-date). Then the opt-ins (``block_on:
[429, html]``, ``stop_on``, ``block_ttl``, ``broken_after``), the doubling of blocks and of a broken proxy's time out,
the inheritance (root, command line, host; the ``proxies:`` section per level) and the errors for the fields of
earlier versions.

Every case asserts the attempts, the waits, the trace entries (``tries``), the proxies marked in the broker (with how
long), whether the page fails cleanly or comes through, and whether the run goes on, pauses or stops. The waits run on
injected clocks (``HTTPFetcher``'s ``clock``, ``wall_clock``, ``sleep``): nothing sleeps for real but the slow server.
The servers are local: one answers directly, two more act as http proxies (they answer absolute-URI requests
themselves), for the host ``library.test``."""
import asyncio
import json
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from linecaster.errors import PipelineConfigError
from linecaster.net.http import (MaxRetriesExceeded, StopRequests, UnexpectedHTML, close_shared, failed_fetch,
                                 fetch_record, HTTPFetcher)
from linecaster.net.policy import HTTPPolicy
from linecaster.testing import sample_png

HTML = b"<!DOCTYPE html><html><head><title>Not here</title></head><body>Sorry</body></html>"
HOST = "library.test"


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


class Clocks:
    """A monotonic clock and a wall clock that move only by the fetcher's sleeps, which are noted (``sleeps``) and
    return at once."""

    def __init__(self):
        self.t, self.wall, self.sleeps = 1000.0, 1_800_000_000.0, []

    def clock(self) -> float:
        return self.t

    def wall_clock(self) -> float:
        return self.wall

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        self.wall += seconds
        await asyncio.sleep(0)

    def kwargs(self) -> dict:
        return {"clock": self.clock, "wall_clock": self.wall_clock, "sleep": self.sleep}


def A(status: int = 200, body: str | bytes = "png", retry_after=None, location: str | None = None, slow: float = 0.0,
      ctype: str = "application/json"):
    """One answer of the scripted server: ``body`` ``png`` (an image), ``html`` or ``empty``, or bytes sent as
    ``ctype``; ``retry_after`` a value or a callable of the wall clock (an HTTP-date); ``location`` a path to redirect
    to; ``slow`` seconds to send the body after the headers."""
    return {"status": status, "body": body, "retry_after": retry_after, "location": location, "slow": slow,
            "ctype": ctype}


class Site:
    """Scripted answers per path (each request takes the next; the last repeats), served directly (``base``) and through
    two proxies (``proxy_file``), which note the requests they carried (``carried``). A key ``(n, path)`` scripts what
    proxy ``n`` (1 or 2) answers there, counted per proxy. ``address``: the loopback address the servers listen on
    (``127.0.0.2``: a second host for the direct path)."""

    def __init__(self, tmp_path, clocks: Clocks, script: dict, address: str = "127.0.0.1"):
        self.script, self.clocks, self.lock, self.counts = script, clocks, threading.Lock(), {}
        self.address = address
        self.carried: dict[int, list[str]] = {0: [], 1: [], 2: []}      # 0: direct
        self.servers = [self._server(n) for n in range(3)]
        self.base = f"http://{address}:{self.servers[0].server_address[1]}"
        self.proxies = [f"{address}:{s.server_address[1]}" for s in self.servers[1:]]
        self.proxy_file = str(tmp_path / "proxies.txt")
        (tmp_path / "proxies.txt").write_text("".join(f"{p}\n" for p in self.proxies))

    def _server(self, n: int):
        site, png = self, sample_png()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                own = (n, path) in site.script                # this proxy's own script
                with site.lock:
                    site.carried[n].append(path)
                    key = (n, path) if own else path
                    k = site.counts[key] = site.counts.get(key, 0) + 1
                answers = site.script[(n, path)] if own else site.script.get(path, [A()])
                a = answers[min(k, len(answers)) - 1]
                raw = isinstance(a["body"], bytes)
                body = a["body"] if raw else {"png": png, "html": HTML, "empty": b""}[a["body"]]
                self.send_response(a["status"])
                self.send_header("Content-Type", a["ctype"] if raw else {
                    "png": "image/png", "html": "text/html; charset=utf-8", "empty": "text/plain"}[a["body"]])
                if a["retry_after"] is not None:
                    value = a["retry_after"]
                    self.send_header("Retry-After", value(site.clocks.wall) if callable(value) else str(value))
                if a["location"]:
                    self.send_header("Location", f"http://{self.headers['Host']}{a['location']}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if a["slow"]:
                    self.wfile.flush()
                    time.sleep(a["slow"])
                try:
                    self.wfile.write(body)
                except OSError:                                # the client cut the attempt
                    pass

        httpd = ThreadingHTTPServer((self.address, 0), Handler)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return httpd

    def url(self, path: str, via: str) -> str:
        return f"{self.base}{path}" if via == "direct" else f"http://{HOST}{path}"

    def close(self) -> None:
        for s in self.servers:
            s.shutdown()


@pytest.fixture
def site(tmp_path):
    made = []

    def make(script: dict, clocks: Clocks, address: str = "127.0.0.1") -> Site:
        made.append(Site(tmp_path, clocks, script, address))
        return made[-1]

    yield make
    for s in made:
        s.close()


def fetcher(s: Site, via: str, clocks: Clocks, tmp_path, clocked_broker: bool = False, **settings) -> HTTPFetcher:
    """A fetcher with linecaster's defaults (no policy file), direct or through the two proxies (both held).
    ``clocked_broker``: the broker runs on the clocks' wall clock too (its leases never expire), so the proxies'
    blocks end as the fetcher's waits pass."""
    proxies = {"proxy_file": s.proxy_file, "broker": str(tmp_path / "broker")} if via == "proxies" else {}
    if clocked_broker and via == "proxies":
        pool_on(clocks, proxies["broker"], s.proxy_file)
    return HTTPFetcher(trust_env=False, **proxies, **clocks.kwargs(), **settings)


def pool_on(clocks: Clocks, folder: str, proxy_file: str, worker: str | None = None):
    """The process's shared broker for ``folder`` (``linecaster.broker.shared``) and proxy pool for ``proxy_file``
    (``linecaster.net.proxies.shared_pool``) on the clocks: the broker on the wall clock, with leases that never
    expire (they are written and renewed on the real clock), the pool on the monotonic clock, listing the broker at
    every look for a proxy."""
    import os

    from linecaster import broker as brokers
    from linecaster.net import proxies
    from linecaster.net.http import read_proxies

    b = brokers.Broker(folder, worker=worker, clock=clocks.wall_clock, lease_ttl=1e9)
    with brokers._SHARED_LOCK:
        brokers._SHARED[(os.getpid(), folder)] = b
    listed = read_proxies(proxy_file)
    pool = proxies.ProxyPool(b, listed, clock=clocks.clock, fill_seconds=0, keep_alive=False)
    with proxies._POOLS_LOCK:
        proxies._POOLS[(os.getpid(), id(b), tuple(listed))] = pool
    return pool


def dead_port() -> int:
    """A loopback port nothing listens on (a proxy that refuses connections)."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch(f: HTTPFetcher, url: str, expect: str | None = "image"):
    """("ok", response, record) or ("error", exception, record)."""
    try:
        r = f.get(url, expect=expect)
        return "ok", r, fetch_record(r)
    except Exception as e:  # noqa: BLE001 - the outcome under test
        return "error", e, failed_fetch(e)


def marks(tmp_path) -> list[tuple[str, float, object]]:
    """(scope, seconds, status) of every mark in the broker: the proxies left out, for how long."""
    out = []
    for p in sorted((tmp_path / "broker").glob("proxies/*/marks/*/*.json")):
        m = json.loads(p.read_text())
        out.append((p.parent.name, round(m["ttl"]), m.get("status")))
    return out


def backoffs(clocks: Clocks) -> list[float]:
    return list(clocks.sleeps)


VIA = ["direct", "proxies"]


# ---------------------------------------------------------------- the defaults, on both paths


@pytest.mark.parametrize("via", VIA)
def test_a_soft_404_is_a_failed_attempt_retried_then_the_page_fails(site, tmp_path, via):
    """200 with an HTML page where an image was expected: every attempt counts and is retried after the backoff (2, 4,
    8, 16 s); after the fifth the page fails with an error that names the expected format and the content type. No
    proxy is left out, nothing pauses, the run goes on."""
    clocks = Clocks()
    s = site({"/p1.png": [A(body="html")]}, clocks)
    f = fetcher(s, via, clocks, tmp_path)
    try:
        outcome, error, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "error"
        cause = error if via == "direct" else error.__cause__
        assert isinstance(cause, UnexpectedHTML) and isinstance(error, UnexpectedHTML if via == "direct" else
                                                                 MaxRetriesExceeded)
        assert "an HTML page (text/html; charset=utf-8, " in str(error) and "where an image was expected" in str(error)
        assert record["tries"] == ["200-html"] * 5 and record["attempts"] == 5
        assert backoffs(clocks) == [2, 4, 8, 16] and "pause_seconds" not in record
        assert marks(tmp_path) == [] and not any(p.paused for p in f.pauses())
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_a_503_maintenance_page_in_html_is_a_503_retried(site, tmp_path, via):
    """503 with an HTML page, twice, then the image: a 503 (only a successful response is judged by its content),
    retried after 2 and 4 s; the page comes through, no proxy is left out."""
    clocks = Clocks()
    s = site({"/p1.png": [A(503, "html"), A(503, "html"), A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path)
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "ok" and response.status_code == 200
        assert record["tries"] == ["503", "503", "200"] and record["attempts"] == 3
        assert backoffs(clocks) == [2, 4] and marks(tmp_path) == [] and not f.breaker.paused
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_a_redirect_to_an_html_login_page_fails_after_its_attempts(site, tmp_path, via):
    """A 302 to a login page (200, HTML) on every attempt: each attempt is the redirect and the page (both counted in
    ``attempts``), traced ``302`` and ``200-html``; the error names the login page's URL."""
    clocks = Clocks()
    s = site({"/p1.png": [A(302, "empty", location="/login")], "/login": [A(body="html")]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, max_retries=2)
    try:
        outcome, error, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "error" and "/login" in str(error) and "where an image was expected" in str(error)
        assert record["tries"] == ["302", "200-html"] * 3 and record["attempts"] == 6
        assert backoffs(clocks) == [2, 4] and marks(tmp_path) == []
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_sporadic_500s_are_retried_and_the_page_comes_through(site, tmp_path, via):
    clocks = Clocks()
    s = site({"/p1.png": [A(500, "empty"), A(500, "empty"), A()], "/p2.png": [A(500, "empty"), A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path)
    try:
        first, second = fetch(f, s.url("/p1.png", via)), fetch(f, s.url("/p2.png", via))
        assert first[0] == second[0] == "ok"
        assert first[2]["tries"] == ["500", "500", "200"] and second[2]["tries"] == ["500", "200"]
        assert backoffs(clocks) == [2, 4, 2] and marks(tmp_path) == [] and not f.breaker.paused
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_a_slow_server_past_the_deadline_is_cut_and_retried(site, tmp_path, via):
    """The first answer sends its headers, then its body after 1 s: past the deadline per attempt (0.3 s here), so the
    attempt is cut (``200-cut``) and retried after 2 s; the server's slowness is not the proxy's (no mark)."""
    clocks = Clocks()
    s = site({"/p1.png": [A(slow=1.0), A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, attempt_timeout=0.3, attempt_min_rate=None)
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "ok" and record["tries"] == ["200-cut", "200"] and record["attempts"] == 2
        assert backoffs(clocks) == [2] and marks(tmp_path) == []
    finally:
        f.close()


def test_a_429_without_retry_after_direct_pauses_60_s_then_doubles(site, tmp_path):
    """Direct: a 429 pauses the worker's requests to the host for 60 s, a second one (for the request sent after the
    pause) for 120 s; the request is tried again each time without using up an attempt, and comes through. A
    successful response starts the doubling again."""
    clocks = Clocks()
    s = site({"/p1.png": [A(429, "empty"), A(429, "empty"), A()], "/p2.png": [A(429, "empty"), A()]}, clocks)
    f = fetcher(s, "direct", clocks, tmp_path, max_retries=0)
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", "direct"))
        assert outcome == "ok" and record["tries"] == ["429", "429", "200"]
        assert record["pause_seconds"] == 180 and sum(clocks.sleeps) == 180 and max(clocks.sleeps) <= 1
        assert f.pause_for("127.0.0.1").generation == 2 and not f.pause_for("127.0.0.1").paused
        clocks.sleeps.clear()
        assert fetch(f, s.url("/p2.png", "direct"))[2]["pause_seconds"] == 60       # answered: 60 s again
    finally:
        f.close()


def test_a_429_without_retry_after_through_proxies_leaves_the_proxy_out_60_s(site, tmp_path):
    """Through proxies: the proxy that got the 429 is left out at the host for 60 s, and the request goes on at once
    through the other one, without using up an attempt and without a wait."""
    clocks = Clocks()
    s = site({"/p1.png": [A(429, "empty"), A()]}, clocks)
    f = fetcher(s, "proxies", clocks, tmp_path, max_retries=0)
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", "proxies"))
        assert outcome == "ok" and record["tries"] == ["429", "200"] and clocks.sleeps == []
        assert marks(tmp_path) == [(HOST, 60, 429)]
        assert sorted(len(c) for n, c in s.carried.items() if n) == [1, 1]     # one request through each proxy
        assert f.proxy_counts() == (1, 1, 0)
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("form", ["seconds", "http-date"])
def test_a_429_with_retry_after_waits_exactly_that(site, tmp_path, via, form):
    """``Retry-After: 30``, or an HTTP-date 45 s ahead: direct, the worker pauses exactly that long; through proxies,
    the proxy is left out at the host exactly that long and the request goes on through the other at once."""
    clocks = Clocks()
    value, seconds = ("30", 30) if form == "seconds" else (lambda wall: formatdate(wall + 45, usegmt=True), 45)
    s = site({"/p1.png": [A(429, "empty", retry_after=value), A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, max_retries=0)
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "ok" and record["tries"] == ["429", "200"]
        if via == "direct":
            assert record["pause_seconds"] == seconds and sum(clocks.sleeps) == seconds and marks(tmp_path) == []
        else:
            assert "pause_seconds" not in record and clocks.sleeps == [] and marks(tmp_path) == [(HOST, seconds, 429)]
    finally:
        f.close()


def test_a_block_past_max_pause_stops_the_run_direct(site, tmp_path):
    """Direct: a 429 whose wait would take the pauses past ``max_pause`` stops the run (``StopRequests``)."""
    clocks = Clocks()
    s = site({"/p1.png": [A(429, "empty", retry_after="86400")]}, clocks)
    f = fetcher(s, "direct", clocks, tmp_path)
    try:
        outcome, error, record = fetch(f, s.url("/p1.png", "direct"))
        assert outcome == "error" and isinstance(error, StopRequests) and "max_pause" in str(error)
        assert record["tries"] == ["429"] and clocks.sleeps == []
    finally:
        f.close()


# ---------------------------------------------------------------- the opt-ins


@pytest.mark.parametrize("via", VIA)
def test_html_in_block_on_makes_an_html_page_a_block(site, tmp_path, via):
    """``block_on: [429, html]``: an HTML page where an image was expected blocks: direct the worker pauses 60 s and
    the request is tried again; through proxies the proxy is left out at the host for 60 s and the request goes on
    through the other at once. Neither uses up an attempt (``max_retries: 0``)."""
    clocks = Clocks()
    s = site({"/p1.png": [A(body="html"), A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, max_retries=0, block_on=[429, "html"])
    try:
        outcome, response, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "ok" and record["tries"] == ["200-html", "200"]
        if via == "direct":
            assert record["pause_seconds"] == 60 and marks(tmp_path) == []
        else:
            assert clocks.sleeps == [] and marks(tmp_path) == [(HOST, 60, "html")]
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("stop, answer, entry", [("html", A(body="html"), "200-html"), (503, A(503, "html"), "503")])
def test_stop_on_stops_the_run_at_once(site, tmp_path, via, stop, answer, entry):
    clocks = Clocks()
    s = site({"/p1.png": [answer]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, stop_on=[stop])
    try:
        outcome, error, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "error" and isinstance(error, StopRequests) and "stop_on" in str(error)
        assert record["tries"] == [entry] and clocks.sleeps == [] and marks(tmp_path) == []
    finally:
        f.close()


def test_block_ttl_caps_a_proxys_block_without_retry_after(site, tmp_path):
    clocks = Clocks()
    s = site({"/p1.png": [A(429, "empty"), A()]}, clocks)
    f = fetcher(s, "proxies", clocks, tmp_path, block_ttl=30)
    try:
        assert fetch(f, s.url("/p1.png", "proxies"))[0] == "ok" and marks(tmp_path) == [(HOST, 30, 429)]
    finally:
        f.close()


@pytest.mark.parametrize("broken_after, failures", [(None, 3), (1, 1)])
def test_a_broken_proxy_is_left_out_after_broken_after_errors_in_a_row(site, tmp_path, broken_after, failures):
    """One proxy refuses connections, the other works; six pages one after the other. The dead one takes every other
    attempt until it is left out for every host: after 3 errors in a row by default, after 1 with ``broken_after:
    1``; first for 300 s (``broken_ttl``). Every page comes through."""
    clocks = Clocks()
    s = site({}, clocks)
    (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{dead_port()}\n{s.proxies[0]}\n")
    settings = {} if broken_after is None else {"broken_after": broken_after}
    f = fetcher(s, "proxies", clocks, tmp_path, **settings)
    try:
        results = [fetch(f, s.url(f"/p{i}.png", "proxies")) for i in range(6)]
        assert all(r[0] == "ok" for r in results)
        assert sum(r[2]["tries"].count("no-response") for r in results) == failures
        assert marks(tmp_path) == [("*", 300, "broken")] and backoffs(clocks) == [2] * failures
    finally:
        f.close()


# ---------------------------------------------------------------- max_pause: one count on both paths

STRICT = {"block_on": [429, "html"]}


@pytest.mark.parametrize("via", VIA)
def test_a_permanent_html_page_under_the_strict_policy_stops_after_max_pause(site, tmp_path, via):
    """``block_on: [429, html]`` and a page that is always HTML: direct the worker pauses 60, 120, 240, 480 s; through
    proxies both are left out as long each time and the requests wait for the first to return. Either way the waits
    since the host's last successful response add up (900 s), and the next (960 s) would pass ``max_pause`` (1000 s):
    the run stops, at the same point on both paths, instead of waiting forever."""
    clocks = Clocks()
    s = site({"/p1.png": [A(body="html")]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, clocked_broker=True, max_pause=1000, **STRICT)
    try:
        outcome, error, record = fetch(f, s.url("/p1.png", via))
        assert outcome == "error" and isinstance(error, StopRequests)
        assert "would pass max_pause (16 min 40 s)" in str(error) and "waited 15 min 00 s" in str(error)
        assert record["pause_seconds"] == 900 and sum(clocks.sleeps) == 900
        if via == "direct":
            assert record["tries"] == ["200-html"] * 5 and str(error).startswith("an HTML page from 127.0.0.1")
            assert f.total_for("127.0.0.1").spent == 900
        else:
            assert record["tries"] == ["200-html"] * 10 and [len(s.carried[n]) for n in (1, 2)] == [5, 5]
            assert str(error).startswith(f"no proxy left for {HOST}: every one is left out (the first returns in 16 min")
            assert f.total_for(HOST).spent == 900
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_a_host_that_recovers_in_time_starts_the_count_again(site, tmp_path, via):
    """The first page waits 180 s in blocks, then comes through: the count starts again, so the second page may wait
    another 180 s under a ``max_pause`` of 300 s (360 s in all would pass it)."""
    clocks = Clocks()
    if via == "direct":           # pauses of 60 and 120 s
        script = {"/p1.png": [A(429, "empty"), A(429, "empty"), A()], "/p2.png": [A(429, "empty"), A(429, "empty"), A()]}
    else:                         # both proxies left out 60 s, then 120 s; through each proxy its own answers
        script = {(n, p): [A(429, "empty"), A(429, "empty"), A()] for n in (1, 2) for p in ("/p1.png", "/p2.png")}
    s = site(script, clocks)
    f = fetcher(s, via, clocks, tmp_path, clocked_broker=True, max_pause=300)
    host = "127.0.0.1" if via == "direct" else HOST
    try:
        first = fetch(f, s.url("/p1.png", via))
        assert first[0] == "ok" and first[2]["pause_seconds"] == 180 and f.total_for(host).spent == 0
        second = fetch(f, s.url("/p2.png", via))
        assert second[0] == "ok" and second[2]["pause_seconds"] >= 120 and f.total_for(host).spent == 0
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_several_hosts_are_counted_separately(site, tmp_path, via):
    """``max_pause`` 200 s. One host only blocks: it waits 60 and 120 s, and the next wait (240 s) stops the run for
    it. Then another host blocks before it answers: its own wait counts from 0, so it comes through, where 180 s and
    its wait together would have passed ``max_pause``; nor did the first host's pauses hold its requests."""
    clocks = Clocks()
    if via == "direct":           # the two hosts: two loopback addresses
        a = site({"/p1.png": [A(429, "empty")]}, clocks)
        b = site({"/p2.png": [A(429, "empty"), A(429, "empty"), A()]}, clocks, address="127.0.0.2")
        f = fetcher(a, via, clocks, tmp_path, max_pause=200)
        urls, hosts, waited = (a.url("/p1.png", via), b.url("/p2.png", via)), ("127.0.0.1", "127.0.0.2"), 180
    else:                         # the proxies answer for any host
        a = site({"/p1.png": [A(429, "empty")], "/p2.png": [A(429, "empty"), A(429, "empty"), A()]}, clocks)
        f = fetcher(a, via, clocks, tmp_path, clocked_broker=True, max_pause=200)
        urls, hosts, waited = (f"http://{HOST}/p1.png", f"http://images.{HOST}/p2.png"), (HOST, f"images.{HOST}"), 60
    try:
        outcome, error, record = fetch(f, urls[0])
        assert outcome == "error" and isinstance(error, StopRequests) and record["pause_seconds"] == 180
        assert f.total_for(hosts[0]).spent == 180
        outcome, response, record = fetch(f, urls[1])
        assert outcome == "ok" and record["pause_seconds"] == waited and f.total_for(hosts[1]).spent == 0
        assert f.total_for(hosts[0]).spent == 180                       # the first host's count is its own
    finally:
        f.close()


def test_a_success_through_another_proxy_starts_the_count_again(site, tmp_path):
    """Through proxies the count is the host's, not a proxy's. Proxy 1 is left out (60 s, then 120 s) and proxy 2
    for its ``Retry-After`` (100 s): the requests wait 100 s; then proxy 2 carries a successful response, and the
    host's count starts again. The next page waits 60 s more (proxy 2 blocked again): fine under a ``max_pause`` of
    150 s, where 160 s since the first block would have stopped the run."""
    clocks = Clocks()
    s = site({(1, "/p1.png"): [A(429, "empty")], (2, "/p1.png"): [A(429, "empty", retry_after="100"), A()],
              (2, "/p2.png"): [A(429, "empty"), A()]}, clocks)
    f = fetcher(s, "proxies", clocks, tmp_path, clocked_broker=True, max_pause=150)
    try:
        first = fetch(f, s.url("/p1.png", "proxies"))
        assert first[0] == "ok" and first[2]["pause_seconds"] == 100 and f.total_for(HOST).spent == 0
        assert s.carried[1] == ["/p1.png", "/p1.png"] and s.carried[2] == ["/p1.png", "/p1.png"]
        second = fetch(f, s.url("/p2.png", "proxies"))
        assert second[0] == "ok" and second[2]["pause_seconds"] == 60 and second[2]["tries"] == ["429", "200"]
        assert s.carried[1] == ["/p1.png", "/p1.png"]                    # proxy 1 still left out
    finally:
        f.close()


# ---------------------------------------------------------------- the doubling, on a proxy pool


def test_a_proxys_blocks_and_breaks_double_until_it_answers(tmp_path):
    """``ProxyPool.block`` without ``Retry-After``: 60, 120, 240 s for repeats, at most ``block_ttl`` (here 200 s); a
    successful response from the host starts it again; ``Retry-After`` is taken as it is and keeps the doubling. A
    broken proxy: 300, 600 s, at most ``block_ttl``; any answer through it starts that again."""
    from linecaster.broker import Broker
    from linecaster.net.proxies import ProxyPool, proxy_id

    now = [1_800_000_000.0]
    broker = Broker(str(tmp_path), worker="a-0", clock=lambda: now[0])
    proxy = "http://10.0.0.1:8080"
    pool = ProxyPool(broker, [proxy], keep_alive=False)

    def ends(scope: str) -> float:
        end = pool._blocked[(proxy_id(proxy), scope)] - now[0]
        now[0] += end                                    # the block ends
        return round(end)

    waits = []
    for _ in range(3):
        pool.block(proxy, HOST, cap=200, status=429)
        waits.append(ends(HOST))
    pool.block(proxy, HOST, 30, cap=200, status=429)    # Retry-After: 30
    waits.append(ends(HOST))
    pool.block(proxy, HOST, cap=200, status=429)
    waits.append(ends(HOST))
    pool.answered(proxy, HOST)
    pool.block(proxy, HOST, cap=200, status=429)
    waits.append(ends(HOST))
    assert waits == [60, 120, 200, 30, 200, 60]
    broken = []
    for _ in range(3):
        pool.broken(proxy, after=1, first=300, cap=1000)
        broken.append(ends("*"))
    pool.answered(proxy)
    pool.broken(proxy, after=1, first=300, cap=1000)
    broken.append(ends("*"))
    assert broken == [300, 600, 1000, 300]


# ---------------------------------------------------------------- the schema


def policy_file(tmp_path, text: str, name: str = "policy.yaml") -> str:
    (tmp_path / name).write_text(text)
    return str(tmp_path / name)


def test_the_levels_inherit_root_then_command_line_then_host(tmp_path):
    """Level 1: the root's, the run's options over them, the host's over both. The ``proxies:`` section: the root's,
    then the host's, field by field (``--proxies`` between them for the file). ``direct: true``: no proxies there."""
    policy = HTTPPolicy(policy_file(tmp_path, """
rate_limits: ["100/60", "2/1"]
attempt_timeout: 120
max_retries: 6
random_user_agent: true
block_on: [429, 403]
max_pause: 2h
proxies: {file: root.txt, per_worker: share, block_ttl: 1h, broken_after: 2, broken_ttl: 10m}
broker: s3://bucket/broker
hosts:
  catalog.example.org: {direct: true, rate_limits: ["25/60"], stop_on: [html]}
  images.example.org: {proxies: {block_ttl: 72h}, max_retries: 2}
  files.example.org: {proxies: {file: host.txt}, block_on: [429, html]}
"""), base={"rate_limits": [(50, 60.0)], "proxy_file": "cli.txt"})
    catalog, images, files, other = (policy.http_for(f"https://{h}/x") for h in (
        "catalog.example.org", "images.example.org", "files.example.org", "elsewhere.example.org"))
    assert other["rate_limits"] == [(50, 60.0)] and other["proxy_file"] == "cli.txt"          # the command line's
    assert (other["attempt_timeout"], other["max_retries"], other["use_fake_user_agent"]) == (120, 6, True)
    assert other["block_on"] == [403, 429] and other["max_pause"] == 7200 and other["broker"] == "s3://bucket/broker"
    assert (other["per_worker"], other["block_ttl"], other["broken_after"], other["broken_ttl"]) == ("share", 3600, 2, 600)
    assert catalog["rate_limits"] == [(25, 60.0)] and "proxy_file" not in catalog and catalog["stop_on"] == ["html"]
    assert images["block_ttl"] == 259200 and images["broken_after"] == 2 and images["proxy_file"] == "cli.txt"
    assert images["max_retries"] == 2 and images["rate_limits"] == [(50, 60.0)]
    assert files["proxy_file"] == "host.txt" and files["block_on"] == [429, "html"] and files["block_ttl"] == 3600
    described = policy.describe()
    assert "catalog.example.org: direct, 25/60 per worker" in described
    assert "stops when the wait would pass 2 h, stops on html" in described
    assert "images.example.org: through proxies, a fair share per worker, 50/60 per proxy, 2 retries" in described
    assert "the proxy left out for the host for Retry-After, else 1 min doubling up to 72 h" in described
    assert "files.example.org: through proxies" in described and "blocks on 429, html" in described
    assert "left out 10 min doubling up to 1 h" in described


@pytest.mark.parametrize("old, new", [
    ("pause_on: [429, 503]", "block_on: [429, 503]"),
    ("pause_on: []", "block_on: []"),
    ("blacklist_on: [403]", "block_on: [403, 429]"),
    ("blacklist_ttl: 72h", "proxies: {block_ttl: 72h}"),
    ("blacklist_threshold: 2", "proxies: {broken_after: 2}"),
    ("proxies: p.txt", "proxies: {file: p.txt}"),
    ("proxies_per_worker: 1", "proxies: {per_worker: 1}"),
    ("{proxies: p.txt, proxies_per_worker: 1, blacklist_ttl: 72h}",
     "proxies: {file: p.txt, per_worker: 1, block_ttl: 72h}"),
])
@pytest.mark.parametrize("where", ["root", "host"])
def test_the_fields_of_earlier_versions_name_the_line_to_write(tmp_path, old, new, where):
    text = old[1:-1].replace(", ", "\n") if old.startswith("{") else old
    if where == "host":
        text = "hosts:\n  a.example.org: {" + text.replace("\n", ", ") + "}"
    with pytest.raises(PipelineConfigError, match="no longer read; write `" + new.replace("[", r"\[").replace(
            "{", r"\{") + "` instead"):
        HTTPPolicy(policy_file(tmp_path, text + "\n"))


def test_the_proxies_section_and_its_checks(tmp_path):
    for text, problem in [("proxies: {files: p.txt}", "unknown files"),
                          ("proxies: {broken_after: 0}", "broken_after is a whole number"),
                          ("proxies: {broken_ttl: soon}", "a duration"),
                          ("proxies: [p.txt]", "proxies: a mapping"),
                          ("direct: yes please", "direct is true or false"),
                          ("stop_on: [captcha]", "stop_on holds HTTP statuses and `html`")]:
        with pytest.raises(PipelineConfigError, match=problem):
            HTTPPolicy(policy_file(tmp_path, text + "\n"))


# ---------------------------------------------------------------- the policy reaches every reader


def manifest(base: str, names: list[str]) -> bytes:
    """A IIIF Presentation 3 manifest whose pages are the images ``<base>/<name>.png``."""
    return json.dumps({
        "@context": "http://iiif.io/api/presentation/3/context.json", "id": f"{base}/item1/manifest",
        "type": "Manifest", "label": {"none": ["Item 1"]}, "items": [
            {"id": f"{base}/item1/canvas/{n}", "type": "Canvas", "items": [{"type": "AnnotationPage", "items": [
                {"type": "Annotation", "body": {"id": f"{base}/{n}.png", "type": "Image"}}]}]} for n in names]}).encode()


def reader_for(kind: str, tmp_path, base: str, http: dict, policy: str | None):
    """A reader of ``kind`` whose one page (or resource) is the image ``<base>/p1.png``."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.readers.images import ImageParquetReader
    from linecaster.blocks.readers.manifests import ManifestReader
    from linecaster.blocks.readers.records import PageRecordReader
    from linecaster.blocks.readers.resources import ResourceReader

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    if kind == "parquet":
        pq.write_table(pa.table({"id": ["p1"], "image": [f"{base}/p1.png"]}), data / "p.parquet")
        return ImageParquetReader(str(data), http=http, http_policy=policy)
    if kind == "items":
        pq.write_table(pa.table({"item": ["p1"]}), data / "p.parquet")
        return ResourceReader(str(data), item_key="item", templates={"image": f"{base}/{{item}}.png"}, http=http,
                              http_policy=policy)
    if kind == "manifests":
        (data / "m.txt").write_text(f"{base}/item1/manifest\n")
        return ManifestReader(str(data), paths_file=str(data / "m.txt"), http=http, http_policy=policy)
    (data / "r.jsonl").write_text(json.dumps({"id": "p1", "text": "", "page": {"page_id": "p1", "image": {
        "uri": f"{base}/p1.png"}}}) + "\n")
    return PageRecordReader(str(data), http=http, http_policy=policy)


@pytest.mark.parametrize("kind", ["parquet", "items", "manifests", "pages"])
@pytest.mark.parametrize("with_policy", [True, False])
def test_the_policy_holds_for_every_reader_that_fetches(site, tmp_path, kind, with_policy):
    """``--parquet``, ``--items``, ``--manifests`` and ``--pages`` read one image that is an HTML page at first. With a
    policy whose ``block_on`` has ``html``, every reader's request is a block: the worker pauses 60 s, then the image
    comes through; without it, an ordinary failed attempt, retried after 2 s."""
    clocks = Clocks()
    s = site({"/p1.png": [A(body="html"), A()]}, clocks)
    s.script["/item1/manifest"] = [A(body=manifest(s.base, ["p1"]))]
    policy = policy_file(tmp_path, "block_on: [429, html]\n") if with_policy else None
    reader = reader_for(kind, tmp_path, s.base, {"trust_env": False, **clocks.kwargs()}, policy)
    docs = list(reader.run())
    assert len(docs) == 1 and docs[0].media and docs[0].media[0].media_bytes.startswith(b"\x89PNG")
    assert sum(clocks.sleeps) == (60 if with_policy else 2) and s.carried[0].count("/p1.png") == 2


def test_a_policys_proxies_rate_limits_and_block_on_reach_the_manifest_reader(site, tmp_path):
    """A policy for ``library.test`` (a name only the proxies answer for) with a proxy list, a rate limit of one
    request per 10 s per proxy and ``block_on: [429, html]``: the manifest's first answer is an HTML page, so the
    proxy that carried it is left out (marked ``html``) and the manifest comes through the other; its two images go
    out through that one, 10 s apart, and the OCR files likewise. Nothing goes out directly."""
    from linecaster.blocks.readers.manifests import ManifestReader

    clocks = Clocks()
    base = f"http://{HOST}"
    body = json.loads(manifest(base, ["p1", "p2"]))
    for canvas, n in zip(body["items"], ["p1", "p2"]):
        canvas["seeAlso"] = [{"id": f"{base}/{n}.xml", "type": "Dataset", "format": "application/xml",
                              "profile": "http://www.loc.gov/standards/alto/"}]
    alto = (b'<?xml version="1.0"?><alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Layout>'
            b'<Page ID="p" WIDTH="6" HEIGHT="4"/></Layout></alto>')
    s = site({"/item1/manifest": [A(body="html"), A(body=json.dumps(body).encode())],
              "/p1.xml": [A(body=alto, ctype="application/xml")], "/p2.xml": [A(body=alto, ctype="application/xml")]},
             clocks)
    policy = policy_file(tmp_path, f"""
broker: {tmp_path / "broker"}
hosts:
  {HOST}:
    block_on: [429, html]
    rate_limits: ["1/10"]
    proxies: {{file: {s.proxy_file}}}
""")
    reader = ManifestReader(str(tmp_path), paths_file=policy_file(tmp_path, f"{base}/item1/manifest\n", "m.txt"),
                            existing_ocr=True, http={"trust_env": False, **clocks.kwargs()}, http_policy=policy)
    docs = list(reader.run())
    assert sorted(d.id for d in docs) == ["item1_0001", "item1_0002"] and all(len(d.media) == 2 for d in docs)
    assert s.carried[0] == [] and sorted(s.carried[1] + s.carried[2]) == sorted(
        ["/item1/manifest"] * 2 + ["/p1.png", "/p2.png", "/p1.xml", "/p2.xml"])
    assert marks(tmp_path) == [(HOST, 60, "html")]
    blocked = 1 if s.carried[1] == ["/item1/manifest"] else 2
    assert s.carried[blocked] == ["/item1/manifest"] and len(s.carried[3 - blocked]) == 5
    fetcher = reader._fetchers.last
    assert fetcher.config.rate_limits == [(1, 10.0)] and fetcher.block_on == {429, "html"}
    waits = sorted(f["wait_seconds"] for d in docs for f in d.metadata["trace"]["fetch"])
    assert [round(w) for w in waits] == [10, 20, 30, 40]                  # one request per 10 s through the proxy



@pytest.mark.parametrize("option", ["--manifests", "--pages", "--parquet", "--items"])
def test_the_http_policy_option_is_taken_by_every_input_that_fetches(tmp_path, option):
    """``--http-policy`` with each input that fetches over http(s) reaches its reader, with the run's options as the
    policy's base (proxies, the broker)."""
    from linecaster.runtime import run

    policy = policy_file(tmp_path, "block_on: [429, html]\n")
    extra = {"--manifests": [str(tmp_path / "m.txt")], "--pages": [str(tmp_path)], "--parquet": [str(tmp_path)],
             "--items": [str(tmp_path), "--item-key", "id", "--resource", "x=https://example.org/{item}"]}[option]
    (tmp_path / "proxies.txt").write_text("127.0.0.1:9\n")
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args([option, *extra, "OUT", "--http-policy", policy,
                                     "--proxies", str(tmp_path / "proxies.txt")]))
    reader = run.reader(a)
    fetchers = getattr(reader, "_fetchers", None) or reader._opener._fetchers
    assert fetchers.http_policy == policy and fetchers.http["proxy_file"] == str(tmp_path / "proxies.txt")
    settings = fetchers.settings("https://example.org/x")
    assert settings["block_on"] == [429, "html"] and settings["default_broker"] == "OUT/logs/broker"
    import pickle

    assert pickle.loads(pickle.dumps(reader))                       # executors pickle it: no fetcher, no thread


# ---------------------------------------------------------------- what stops a run stops it from every reader


@pytest.mark.parametrize("what", ["manifest", "image", "ocr"])
def test_a_stop_stops_a_manifests_run_whatever_it_fetches(site, tmp_path, what):
    """``stop_on: [403]`` and a 403 for the manifest, an image or an OCR file: the run stops (``StopRequests``, a
    ``ServerError``), it is not one more failed manifest or page."""
    from linecaster.blocks.readers.manifests import ManifestReader
    from linecaster.errors import ServerError

    clocks = Clocks()
    s = site({}, clocks)
    body = json.loads(manifest(s.base, ["p1"]))
    body["items"][0]["seeAlso"] = [{"id": f"{s.base}/p1.xml", "type": "Dataset", "format": "application/xml",
                                    "profile": "http://www.loc.gov/standards/alto/"}]
    s.script["/item1/manifest"] = [A(403, "empty") if what == "manifest" else A(body=json.dumps(body).encode())]
    s.script["/p1.png"] = [A(403, "empty") if what == "image" else A()]
    s.script["/p1.xml"] = [A(403, "empty") if what == "ocr" else A(body=b"<alto/>", ctype="application/xml")]
    reader = reader_for("manifests", tmp_path, s.base, {"trust_env": False, **clocks.kwargs()},
                        policy_file(tmp_path, "stop_on: [403]\n"))
    reader.existing_ocr = True
    with pytest.raises(ServerError, match="HTTP 403 from 127.0.0.1: its policy stops the run here"):
        list(reader.run())


@pytest.mark.parametrize("kind", ["parquet", "items", "manifests", "pages"])
@pytest.mark.parametrize("problem", ["missing policy", "unknown field", "missing proxy list"])
def test_a_configuration_error_stops_every_reader(site, tmp_path, kind, problem):
    """A policy file that is not there, an HTTP field linecaster does not know (one of pybookget's) or a proxy list
    that cannot be read: a ``PipelineConfigError`` that stops the run, never a failed page or manifest."""
    clocks = Clocks()
    s = site({"/item1/manifest": [A(body=manifest("http://127.0.0.1:9", ["p1"]))]}, clocks)
    http, policy = {"trust_env": False}, None
    if problem == "missing policy":
        policy = str(tmp_path / "nowhere.yaml")
    elif problem == "unknown field":
        http["show_progress"] = False
    else:
        http.update(proxy_file=str(tmp_path / "no-proxies.txt"), broker=str(tmp_path / "broker"))
    reader = reader_for(kind, tmp_path, s.base, http, policy)
    with pytest.raises(PipelineConfigError):
        list(reader.run())


def test_a_fetcher_that_cannot_be_made_leaves_no_thread_behind(tmp_path):
    before = sum(1 for t in threading.enumerate() if t.name == "linecaster-http")
    for _ in range(3):
        with pytest.raises(FileNotFoundError):
            HTTPFetcher(proxy_file=str(tmp_path / "no-proxies.txt"), broker=str(tmp_path / "broker"))
    assert sum(1 for t in threading.enumerate() if t.name == "linecaster-http") == before


@pytest.mark.parametrize("body, html", [
    (b'{"id": "m"}', False), (b"[1]", False), (b'<?xml version="1.0"?><alto/>', False), (b"png", False),
    (b"\xff\xd8\xff\xe0jpeg", False), (b'<?xml version="1.0"?><!DOCTYPE html><html></html>', True),
    (HTML, True), (b"Please sign in", True), (b"", True)])
def test_data_served_as_text_html_is_not_unexpected_html(site, tmp_path, body, html):
    """A server that sends JSON, XML or an image as ``text/html``: the body is what it says, so the fetch succeeds;
    a body that is HTML (XHTML too), or text that is neither, sent as ``text/html``, is unexpected HTML."""
    clocks = Clocks()
    data = sample_png() if body == b"png" else body
    s = site({"/m": [A(body=data, ctype="text/html; charset=utf-8")]}, clocks)
    f = fetcher(s, "direct", clocks, tmp_path, max_retries=0)
    try:
        outcome, result, record = fetch(f, s.url("/m", "direct"), expect="manifest")
        assert (outcome == "error" and isinstance(result, UnexpectedHTML)) is html
        assert record["tries"] == ["200-html" if html else "200"]
    finally:
        f.close()


@pytest.mark.parametrize("via", VIA)
def test_unexpected_html_counts_as_no_answer_for_the_breaker(site, tmp_path, via):
    """The breaker notes an attempt's status from its headers, except a successful response where a format was
    expected: that is noted once its body is known to be one, and unexpected HTML not at all, so HTML pages do not
    count as answers that keep the breaker closed."""
    clocks = Clocks()
    s = site({"/p1.png": [A(body="html")], "/p2.png": [A()]}, clocks)
    f = fetcher(s, via, clocks, tmp_path, max_retries=2)
    try:
        assert fetch(f, s.url("/p1.png", via))[0] == "error" and list(f.breaker._outcomes) == []
        assert fetch(f, s.url("/p2.png", via))[0] == "ok"
        assert [e for _, e in f.breaker._outcomes] == [False]
    finally:
        f.close()


def test_a_resource_that_fails_as_html_is_one_server_error_for_the_breaker(site, tmp_path):
    clocks = Clocks()
    s = site({"/r1.png": [A(body="html")]}, clocks)
    reader = reader_for("items", tmp_path, s.base, {"trust_env": False, "max_retries": 2, **clocks.kwargs()}, None)
    reader.templates = {"image": f"{s.base}/r{{item}}.png"}
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"item": ["1"]}), tmp_path / "data" / "p.parquet")
    docs = list(reader.run())
    assert len(docs) == 1 and not docs[0].media
    breaker = reader._last.breaker
    until_true = time.monotonic() + 5
    while not breaker._outcomes and time.monotonic() < until_true:              # noted in the fetcher's loop
        time.sleep(0.01)
    assert [e for _, e in breaker._outcomes] == [True] and breaker._errors_in_a_row == 1
