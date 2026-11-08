"""HTTP for linecaster's readers: pybookget's HTTP layer (``linecaster[pybookget]``: rate limits, retries that honor
``Retry-After``, the fallback URL on 404, the environment's proxy settings) on an event loop in a background thread,
for blocking callers such as datatrove blocks.

Rate limits hold per ``HTTPFetcher``. Readers share one per process and configuration (``HTTPFetcher.shared``), so
the limits hold per worker, across the tasks it runs one after the other: a server sees the workers running at once
times the limits.

Readers request ahead (``prefetched``) in a window that sizes itself: it grows while the reader waits for a response
and no request is waiting for the rate limits (``HTTPFetcher.waiting``), so the limits stay busy, rate times latency
in flight, without a setting, up to the rate limits times the deadline per attempt (``HTTPFetcher.max_ahead``).
Readers take pages as their requests finish, not in row order, so a slow request (one being retried) delays only
itself.

With a proxy list (``proxy_file``: one proxy per line, ``read_proxies``) requests go through resilient-httpx
(``linecaster[resilient-httpx]``): each attempt through the next proxy in turn, a proxy that fails an attempt (a
timeout, a connection or proxy error, a retryable status) blacklisted for ``PROXY_BLACKLIST_TTL`` seconds after
``PROXY_BLACKLIST_THRESHOLD`` failures, or for a shorter ``Retry-After`` a 429 or 503 asks for (storytracer's fork of
resilient-httpx, ``blacklist_ttl_from_retry_after``), the retries resilient-httpx's (pybookget's counts and waits; no
``Retry-After``: the next attempt goes out through another proxy). Each proxy's client is made by pybookget's
``create_client``, so the rate limits (shared by all proxies), the deadline per attempt and the records below hold
as without. Proxy URLs are never logged with their credentials (``redact``).

A fetcher pauses while its server fails (``Breaker``): when most recent attempts got a server error (5xx, Cloudflare's
520-524 among them), no request goes out except a probe now and then, with waits that double up to ten minutes; the
first probe the server answers ends the pause. Requests waiting there count as waiting for the rate limits, so the
window does not grow, and their pages are delayed, not failed. The retries themselves are pybookget's (520-524
included); with a proxy list a server error is retried through another proxy without blacklisting the one it came
through (resilient-httpx's ``blacklist_on``: only a 429 counts against a proxy, besides timeouts and connection or
proxy errors, and the statuses of a host's ``blacklist_on``, which are then retried through the next proxy).

A fetch that fails keeps its record too: it travels with the exception (``FETCH_KEY`` as an attribute, ``failed_fetch``),
so a failed page's trace shows its attempts; and its message names what failed last (``after 5 attempts: HTTP 520``,
``ReadTimeout (no message)``), where resilient-httpx's or httpx's own can be empty.

With a proxy list an HTML page where another format was expected (``submit(..., expect=...)``: a resource's format,
an image) is that proxy's block, as a 429 is: the attempt fails (``ProxyBlocked``), the proxy is left out (its host's
``blacklist_ttl``) and the request goes on through the next one; it does not count toward the breaker. A host whose
proxies are all left out stops the run (``StopRequests``, naming when the first one returns) instead of failing every
item that follows. With ``proxy_blocks`` (a folder) the blocks are shared: each is written there as a marker, and a
fetcher leaves out the proxies other workers, or earlier runs, found blocked (``linecaster.net.proxy_blocks``).

Every fetch records its attempts (``tries``): per attempt ``"200"`` (or another status) for a response read whole,
``"200-cut"`` for one cut after its headers (the deadline per attempt), ``"no-response"`` for none (a timeout, a
connection or proxy error), so a trace tells a slow server from one that answers 429 or 503.

Every fetch records what it took (``fetch_record``): start and end, the host, the status, the attempts (retries and
redirects count) and the time spent waiting for the rate limits. Readers put the records on the page they fetched
(``doc.metadata["trace"]["fetch"]``), which the tracing turns into ``linecaster.http.fetch`` spans.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import TypeVar
from urllib.parse import quote, urlsplit

from loguru import logger

from ..errors import ServerError

T = TypeVar("T")
S = TypeVar("S")

#: the User-Agent sent by default: datatrove's (``HTTPFetchReader``'s ``custom_agent``)
USER_AGENT = "HF-Research/1.0"
#: pybookget ``Config`` settings for bulk work: datatrove's user agent, reused connections, patient retries, and a
#: deadline per attempt (15 s plus 1 s per 50 kB the response says it holds, counted after the rate limits), so a
#: connection that hangs or trickles (a slow proxy exit) is cut and retried within seconds
HTTP_DEFAULTS = dict(use_fake_user_agent=False, user_agent=USER_AGENT, max_keepalive_connections=16,
                     max_retries=5, retry_wait_min=2.0, retry_wait_max=60.0, attempt_timeout=15.0,
                     attempt_min_rate=50_000, show_progress=False)


def _pybookget():
    try:
        import pybookget  # noqa: F401
    except ImportError as e:
        raise ImportError("manifests and http(s) images need pybookget: install linecaster[pybookget]") from e


#: a proxy that fails this many attempts in a row is left out of the rotation ...
PROXY_BLACKLIST_THRESHOLD = 1
#: ... for this many seconds
PROXY_BLACKLIST_TTL = 3600.0


def read_proxies(path: str) -> list[str]:
    """The proxies listed in the file ``path`` (any fsspec path), as URLs: one per line, as a URL
    (``http://user:pass@host:port``, ``socks5://host:port``) or as Webshare's lists give them (``host:port`` or
    ``host:port:user:pass``, meaning http). Blank lines and ``#`` comments are skipped."""
    from datatrove.io import get_datafolder

    folder, _, name = path.rpartition("/")
    with get_datafolder(folder or ".").open(name, "r") as f:
        lines = f.read().splitlines()
    out = []
    for n, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "://" in line:
            out.append(line)
            continue
        parts = line.split(":")
        if len(parts) == 2:
            out.append(f"http://{parts[0]}:{parts[1]}")
        elif len(parts) == 4:
            host, port, user, password = parts
            out.append(f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}")
        else:
            raise ValueError(f"{path}, line {n}: a proxy is a URL, host:port or host:port:user:pass")
    if not out:
        raise ValueError(f"{path}: no proxies")
    return out


def redact(proxy: str | None) -> str:
    """``proxy`` without its credentials: ``http://***@host:port``."""
    if not proxy:
        return "direct"
    parts = urlsplit(proxy)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{'***@' if parts.username or parts.password else ''}{host}{port}"


class _QuietLog:
    """resilient-httpx's structlog logger, silenced: it logs proxy URLs with their credentials; linecaster logs the
    blacklisting itself (redacted)."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _proxy_client(fetcher: HTTPFetcher, proxies: list[str], threshold: int, ttl: float,
                  blacklist_on: list[int] | None = None):
    """resilient-httpx's ``AsyncProxyHttpClient`` over ``proxies`` whose per-proxy clients are pybookget's
    ``create_client`` (with ``fetcher``'s hooks and its shared rate limiter), retrying as pybookget's ``Config``
    says. ``blacklist_on``: statuses besides 429 that leave a proxy out; they are retried (through the next
    proxy)."""
    try:
        import httpx
        from resilient_httpx import AsyncProxyHttpClient, RetryPolicy
    except ImportError as e:
        raise ImportError("a proxy list needs resilient-httpx: install linecaster[resilient-httpx]") from e
    from pybookget.http.client import RETRYABLE_STATUS_CODES

    config = fetcher.config
    total = len(proxies)
    blacklisting = {429, *(blacklist_on or ())}

    def blacklisted(pool: str, proxy: str) -> None:
        left = sum(1 for p in client.blacklist_snapshot().get(pool, ()) if p["in_rotation"])
        log = logger.warning if left < max(1, total // 10) else logger.debug
        log("proxy {proxy} left out for {ttl:.0f} s; {left} of {total} in rotation", proxy=redact(proxy), ttl=ttl,
            left=left, total=total)
        if fetcher._blocks is not None:
            record = _FETCH.get() or {}
            remaining = max((p["ttl_remaining_seconds"] or 0.0 for p in client.blacklist_snapshot().get(pool, ())
                             if p["proxy"] == proxy), default=ttl)
            status = (record.get("tries") or [None])[-1]
            asyncio.get_running_loop().run_in_executor(
                None, fetcher._write_block, record.get("host") or "", proxy, remaining or ttl, status)

    class Client(AsyncProxyHttpClient):
        def _get_client(self, proxy, impersonate=False):
            if proxy not in self._clients:
                self._clients[proxy] = fetcher._new_client(proxy)
            return self._clients[proxy]

    client = Client(proxies=proxies, retry=RetryPolicy(
        max_attempts=config.max_retries, backoff="exponential", min_wait=config.retry_wait_min,
        max_wait=config.retry_wait_max, retry_on=sorted(RETRYABLE_STATUS_CODES | blacklisting),
        retry_on_exception=[httpx.TransportError]),
        timeout=config.timeout, blacklist_threshold=threshold, blacklist_ttl=ttl, blacklist_ttl_from_retry_after=True,
        blacklist_on=blacklisting, on_blacklist=blacklisted)
    client._log = _QuietLog()
    return client


def is_url(path: str) -> bool:
    return path.startswith(("http://", "https://"))


#: the most requests a reader keeps ahead of the page it gives on (their responses wait there, in order)
MAX_AHEAD = 256
#: how often a reader waiting for a response looks whether its window should grow, which it does by one at a time
POLL_SECONDS = 0.05


def prefetched(entries: Iterable[T], submit: Callable[[T], S], cancel: Callable[[S], None],
               future: Callable[[S], Future] | None = None,
               fetcher: Callable[[], HTTPFetcher | None] | None = None, ordered: bool = True) -> Iterator[S]:
    """``submit(entry)`` for each of ``entries``, submitted ahead of the ones given back. ``submit`` starts the work
    (e.g. ``HTTPFetcher.submit``) and returns its handle, whose ``concurrent.futures.Future`` is ``future(handle)``
    (default: the handle itself). ``ordered``: handles are given back in the order of ``entries``, so the first one's
    work holds back the others; else as their work is done (the earliest submitted of those done first), so a slow
    request delays only itself.

    The window sizes itself: it starts at ``fetcher().ahead`` and grows by one, at most every ``POLL_SECONDS``, while
    the consumer would wait (the first handle's work, or with ``ordered=False`` every handle's, is not done) and no
    request waits for the fetcher's rate limits (``HTTPFetcher.waiting``), so they are kept busy, up to
    ``fetcher().max_ahead`` (more in flight than rate limits times the deadline per attempt never helps).
    ``ahead`` keeps the size for the next task in this process. Without a fetcher (``fetcher`` None, or returning
    None: nothing fetched over http yet) one entry is submitted at a time, as a plain loop would. Whatever is still
    in the window when the consumer stops is passed to ``cancel``, and ``entries`` is closed if it is a generator (its
    open files closed at once)."""
    future = future or (lambda handle: handle)
    window: deque = deque()
    source = iter(entries)
    more = True

    def add() -> None:
        nonlocal more
        for entry in source:
            window.append(submit(entry))
            return
        more = False

    def ready():
        """The index in the window of the handle to give back now, or None."""
        if ordered:
            return 0 if future(window[0]).done() else None
        return next((i for i, h in enumerate(window) if future(h).done()), None)

    try:
        while True:
            f = fetcher() if fetcher else None
            while more and len(window) < (min(f.ahead, f.max_ahead) if f is not None else 1):
                add()
            if not window:
                return
            while (i := ready()) is None:
                wait([future(window[0])] if ordered else [future(h) for h in window], timeout=POLL_SECONDS,
                     return_when=FIRST_COMPLETED)
                f = fetcher() if fetcher else None
                if ready() is None and more and f is not None and f.waiting == 0 and len(window) < f.max_ahead:
                    add()
                    f.ahead = max(f.ahead, len(window))
            handle = window[i]
            del window[i]
            yield handle
    finally:
        for handle in window:
            cancel(handle)
        if close := getattr(source, "close", None):
            close()


#: the record of the fetch running in this task of the event loop (httpx calls its hooks in the request's task)
_FETCH: contextvars.ContextVar[dict | None] = contextvars.ContextVar("linecaster_fetch", default=None)
#: where a response carries its fetch's record (``response.extensions``)
FETCH_KEY = "linecaster.fetch"


def _duration(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600} h {s % 3600 // 60:02d} min" if s >= 3600 else f"{s // 60} min {s % 60:02d} s"


def last_error(error: BaseException | None) -> str:
    """What failed last in resilient-httpx's retries: ``HTTP 520`` for a retried status, else the error's type and
    message (``ReadTimeout (no message)`` for httpx's silent timeouts)."""
    if error is None:
        return "unknown"
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None) is not None:
        return f"HTTP {response.status_code}"
    return f"{type(error).__name__}: {error}" if str(error) else f"{type(error).__name__} (no message)"


def _server_error(error: BaseException) -> bool:
    """Whether ``error`` (pybookget's ``HTTPStatusError``, or resilient-httpx's retries used up) is a server error."""
    for e in (error, error.__cause__):
        response = getattr(e, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            return status >= 500
    return False


def failed_fetch(error: BaseException) -> dict | None:
    """The record of the fetch that raised ``error`` (``HTTPFetcher._fetch``), or None."""
    return getattr(error, FETCH_KEY.replace(".", "_"), None)


def fetch_record(response) -> dict | None:
    """What fetching ``response`` took: ``{"start", "end"}`` (ns since the epoch), ``host``, ``status``, ``attempts``,
    ``wait_seconds`` (rate limits); None for a response that was not fetched here."""
    return getattr(response, "extensions", {}).get(FETCH_KEY) if response is not None else None


#: the ticket of the fetch running in this task of the event loop: whether it waits for the rate limits
_TICKET: contextvars.ContextVar[_Ticket | None] = contextvars.ContextVar("linecaster_ticket", default=None)


class _Ticket:
    """A fetch's place in ``HTTPFetcher.waiting``: queued from its submission until its first attempt has passed the
    rate limits, and again for each retry until it has passed them."""

    def __init__(self, fetcher: HTTPFetcher, expect: str | None = None):
        self.fetcher, self.queued, self.expect = fetcher, False, expect

    def queue(self, queued: bool) -> None:
        with self.fetcher._lock:
            if self.queued != queued:
                self.queued = queued
                self.fetcher._waiting += 1 if queued else -1


async def _before(request) -> None:
    record = _FETCH.get()
    if record is not None:
        record["attempts"] += 1
        record["tries"].append("no-response")             # until its response comes
        record["_t"] = time.perf_counter()
    if (ticket := _TICKET.get()) is not None:
        ticket.queue(True)


async def _after(request) -> None:              # after the rate limits' hook: the time they made it wait
    if (ticket := _TICKET.get()) is not None:
        ticket.queue(False)
    record = _FETCH.get()
    if record is not None and "_t" in record:
        record["wait_seconds"] = round(record["wait_seconds"] + time.perf_counter() - record.pop("_t"), 4)


class StopRequests(ServerError):
    """A host answered with a status its policy stops the run on (``stop_on``, ``linecaster.net.hosts``), raised
    before any retry since a retry would only prolong its block; or every proxy of a host is left out. A
    ``ServerError``: it stops the run (``NOT_THE_PAGES``)."""


class ProxyBlocked(Exception):
    """An HTML page through a proxy where another format was expected: that proxy's block (made a ``TransportError``
    where it is raised, so resilient-httpx leaves the proxy out and retries through the next)."""


def _is_html(response) -> bool:
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype == "text/html":
        return True
    try:
        head = response.content[:512].lstrip().lower()
    except Exception:  # noqa: BLE001 - not read: decided by the content type alone
        return False
    return head.startswith((b"<!doctype html", b"<html"))


async def _headers(response) -> None:          # the first response hook: the headers are in
    if (ticket := _TICKET.get()) is not None:
        if response.status_code in ticket.fetcher.stop_on:
            raise StopRequests(f"HTTP {response.status_code} from {response.request.url.host}: its policy stops "
                               "the run here (stop_on), without a retry")
        ticket.fetcher.breaker.record(response.status_code)
    record = _FETCH.get()
    if record is not None and record["tries"]:
        record["tries"][-1] = f"{response.status_code}-cut"


async def _read(response) -> None:             # the last response hook: read whole (the deadline did not cut it)
    record = _FETCH.get()
    ticket = _TICKET.get()
    if (ticket is not None and ticket.expect and ticket.expect != "html" and ticket.fetcher._proxies is not None
            and response.status_code < 300):
        await response.aread()
        if _is_html(response):                   # a proxy's block page: the attempt fails, the proxy is left out
            if record is not None and record["tries"]:
                record["tries"][-1] = f"{response.status_code}-html"
            import httpx

            class Blocked(ProxyBlocked, httpx.TransportError):
                pass

            raise Blocked(f"an HTML page through the proxy where {ticket.expect} was expected", request=response.request)
    if record is not None and record["tries"]:
        record["tries"][-1] = str(response.status_code)


#: a pause starts when at least this share of the attempts in the last ``BREAKER_WINDOW`` seconds got a server error,
BREAKER_SHARE = 0.5
BREAKER_WINDOW = 60.0
#: ... counting at least this many attempts
BREAKER_MIN_ATTEMPTS = 20
#: the first wait before a probe; each probe the server fails doubles it, up to ``BREAKER_MAX_WAIT``
BREAKER_FIRST_WAIT = 60.0
BREAKER_MAX_WAIT = 600.0
#: a probe without an answer (a timeout, a proxy error) after this long lets another probe go
BREAKER_PROBE_TIMEOUT = 60.0
#: how often a request waiting in a pause looks again (at the latest)
BREAKER_POLL = 1.0
#: how often one request waits out a pause after its retries ran out in it (``HTTPFetcher._fetch``), so a URL that
#: fails for itself, not because of an outage, still ends
BREAKER_WAITS = 5


class Breaker:
    """Pauses a fetcher's requests while its server fails. Closed, it notes each attempt's answer (``record``: a
    server error, 5xx, or not); when at least ``BREAKER_SHARE`` of the attempts in the last ``BREAKER_WINDOW`` seconds
    (``BREAKER_MIN_ATTEMPTS`` at least) were server errors, or the last ``in_a_row`` were (the fetcher's retries per
    request, so a request alone cannot use them up before the breaker sees the outage), it opens: requests wait in ``wait_turn`` (before the rate
    limits) except one probe after ``BREAKER_FIRST_WAIT``, then after waits that double up to ``BREAKER_MAX_WAIT``;
    the first answer that is not a server error closes it. Used from the fetcher's event loop only."""

    def __init__(self, in_a_row: int | None = None):
        self.in_a_row = in_a_row
        self._errors_in_a_row = 0
        self._outcomes: deque = deque()                  # (time, server error)
        self.open_until: float | None = None             # monotonic; None: closed
        self.opened_at: float | None = None
        self._wait = BREAKER_FIRST_WAIT
        self._probe: float | None = None                 # when the probe went out

    @property
    def paused(self) -> bool:
        return self.open_until is not None

    def next_try(self) -> float:
        """Seconds until the next probe (0 when one is out or the breaker is closed)."""
        return max(0.0, self.open_until - time.monotonic()) if self.open_until is not None and not self._probe else 0.0

    def record(self, status: int) -> None:
        now, server_error = time.monotonic(), status >= 500
        if self.open_until is not None:
            if self._probe is None:                      # an attempt that went out before the pause began
                return
            self._probe = None
            if server_error:
                self._wait = min(self._wait * 2, BREAKER_MAX_WAIT)
                self.open_until = now + self._wait
                logger.info("the server still fails (HTTP {status}): next try in {wait}", status=status,
                            wait=f"{self._wait:.0f} s")
            else:
                logger.warning("the server answers again after {paused}: requests go on",
                               paused=f"{now - (self.opened_at or now):.0f} s")
                self.open_until = self.opened_at = None
                self._wait = BREAKER_FIRST_WAIT
                self._outcomes.clear()
                self._errors_in_a_row = 0
            return
        self._outcomes.append((now, server_error))
        self._errors_in_a_row = self._errors_in_a_row + 1 if server_error else 0
        while self._outcomes and now - self._outcomes[0][0] > BREAKER_WINDOW:
            self._outcomes.popleft()
        failed = sum(1 for _, e in self._outcomes if e)
        if (len(self._outcomes) >= BREAKER_MIN_ATTEMPTS and failed >= BREAKER_SHARE * len(self._outcomes)
                or self.in_a_row and self._errors_in_a_row >= self.in_a_row):
            self.opened_at, self.open_until = now, now + self._wait
            logger.warning("server errors in {failed} of the last {n} attempts: requests pause, next try in {wait}",
                           failed=failed, n=len(self._outcomes), wait=f"{self._wait:.0f} s")

    async def wait_out(self) -> None:
        """Return when the pause is over or its next probe is due, without taking the probe (the request's next
        attempt takes it in ``wait_turn``, as any attempt does)."""
        while self.open_until is not None and time.monotonic() < self.open_until:
            await asyncio.sleep(min(BREAKER_POLL, max(0.01, self.open_until - time.monotonic())))

    async def wait_turn(self) -> None:
        """Return when a request may go out: at once while closed; while open, as the probe once its time has come
        (or the probe before it went unanswered for ``BREAKER_PROBE_TIMEOUT``), else after the pause."""
        while self.open_until is not None:
            now = time.monotonic()
            if self._probe is not None and now - self._probe > BREAKER_PROBE_TIMEOUT:
                self._probe = None                       # unanswered (a timeout, a proxy error): another may go
            if self._probe is None and now >= self.open_until:
                self._probe = now
                return
            await asyncio.sleep(BREAKER_POLL if self._probe is not None
                                else min(BREAKER_POLL, max(0.01, self.open_until - now)))


async def _breaker_turn(request) -> None:       # a request hook, before the rate limits'
    if (ticket := _TICKET.get()) is not None:
        await ticket.fetcher.breaker.wait_turn()


_SHARED: dict[tuple, HTTPFetcher] = {}
_SHARED_LOCK = threading.Lock()


class HTTPFetcher:
    """GETs with pybookget's ``fetch`` from blocking code: ``submit`` returns a ``concurrent.futures.Future``
    of the read ``httpx.Response``, ``get`` waits for it. ``config`` overrides ``HTTP_DEFAULTS`` (any field of
    pybookget's ``Config``, e.g. ``rate_limits=[(5, 1), (200, 60)]``, ``iiif_format="png"``). ``waiting``: the
    requests submitted that wait for the rate limits; ``ahead``: the window ``prefetched`` has grown to."""

    @classmethod
    def shared(cls, **config) -> HTTPFetcher:
        """The fetcher of this process for ``config``, made at first use and kept open: the rate limits then hold
        across the tasks a worker runs one after the other, and so does the window ``prefetched`` has learned."""
        key = (os.getpid(), json.dumps(config, sort_keys=True, default=repr))
        with _SHARED_LOCK:
            fetcher = _SHARED.get(key)
            if fetcher is None or fetcher._loop.is_closed():
                fetcher = _SHARED[key] = cls(**config)
            return fetcher

    def __init__(self, proxy_file: str | None = None, proxy_blacklist_threshold: int = PROXY_BLACKLIST_THRESHOLD,
                 proxy_blacklist_ttl: float = PROXY_BLACKLIST_TTL, proxy_blacklist_on: list[int] | None = None,
                 proxy_blocks: str | None = None, stop_on: list[int] | None = None, **config):
        _pybookget()
        from pybookget.config import Config

        self.config = Config(**{**HTTP_DEFAULTS, **config})
        self._lock, self._waiting, self.ahead = threading.Lock(), 0, 1
        self.breaker = Breaker(in_a_row=self.config.max_retries)
        self.stop_on = frozenset(stop_on or ())
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="linecaster-http", daemon=True)
        self._thread.start()

        async def client():
            return self._new_client(self.config.proxy)

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()
        self._proxies, self._blocks, self._block_hosts, self._block_poll = None, None, set(), None
        if proxy_file:
            proxies = read_proxies(proxy_file)
            self._proxies = _proxy_client(self, proxies, proxy_blacklist_threshold, proxy_blacklist_ttl,
                                          proxy_blacklist_on)
            if proxy_blocks:
                from .proxy_blocks import ProxyBlocks, proxy_id

                self._blocks = ProxyBlocks(proxy_blocks)
                self._proxy_ids = {proxy_id(p): p for p in proxies}
                self._block_poll = asyncio.run_coroutine_threadsafe(self._poll_blocks(), self._loop)

    def _write_block(self, host: str, proxy: str, ttl: float, status: str | None) -> None:
        try:
            self._blocks.write(host, proxy, ttl, status)
        except Exception as e:  # noqa: BLE001 - the block still holds in this process
            logger.warning("proxy block of {proxy} not written to {folder}: {error}", proxy=redact(proxy),
                           folder=self._blocks.path, error=e)

    async def _apply_blocks(self, live: dict[str, float]) -> None:
        for pid, remaining in live.items():
            proxy = self._proxy_ids.get(pid)
            if proxy is not None and await self._proxies.block_proxy(proxy, remaining):
                logger.info("proxy {proxy} left out for {left}: found blocked by another worker or an earlier run",
                            proxy=redact(proxy), left=_duration(remaining))

    def _read_blocks(self, host: str) -> dict[str, float]:
        try:
            return self._blocks.live(host)
        except Exception as e:  # noqa: BLE001 - read again at the next poll
            logger.warning("proxy blocks in {folder} not read: {error}", folder=self._blocks.path, error=e)
            return {}

    async def _poll_blocks(self) -> None:
        """Every ``POLL_SECONDS``, the blocks other workers found at the hosts this fetcher sends requests to."""
        from .proxy_blocks import POLL_SECONDS

        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(POLL_SECONDS)
            for host in list(self._block_hosts):
                await self._apply_blocks(await loop.run_in_executor(None, self._read_blocks, host))

    def _new_client(self, proxy: str | None):
        """pybookget's client for ``proxy`` (None: the environment's settings), with linecaster's hooks; every client
        shares this fetcher's rate limiter (pybookget keeps it per ``Config`` and event loop)."""
        import dataclasses

        from pybookget.http import create_client

        config = self.config
        if proxy != config.proxy:
            config = dataclasses.replace(config, proxy=proxy)
            config._limiters = self.config._limiters
        c = create_client(config)
        hooks = dict(c.event_hooks)
        hooks["request"] = [_before, _breaker_turn, *hooks.get("request", []), _after]
        hooks["response"] = [_headers, *hooks.get("response", []), _read]
        c.event_hooks = hooks
        return c

    def proxies_in_rotation(self) -> tuple[int, int] | None:
        """(proxies in rotation, proxies) with a proxy list, else None."""
        if self._proxies is None:
            return None
        states = [p for pool in self._proxies.blacklist_snapshot().values() for p in pool]
        return sum(1 for p in states if p["in_rotation"]), len(states)

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def max_ahead(self) -> int:
        """The most requests worth having in flight: the rate limits' rate (the strictest window's) times the deadline
        per attempt, since every attempt ends within it; ``MAX_AHEAD`` without either, and never more."""
        limits, deadline = self.config.rate_limits, getattr(self.config, "attempt_timeout", None)
        if not limits or not deadline:
            return MAX_AHEAD
        rate = min(n / s for n, s in limits)
        return max(1, min(MAX_AHEAD, int(rate * deadline) + 1))

    async def _fetch(self, url: str, fallback_url: str | None, ticket: _Ticket):
        from pybookget.http import fetch

        record = {"start": time.time_ns(), "host": urlsplit(url).hostname or "", "attempts": 0, "wait_seconds": 0.0,
                  "tries": []}
        token, ticket_token = _FETCH.set(record), _TICKET.set(ticket)
        try:
            for waits in range(BREAKER_WAITS + 1):
                try:
                    if self._proxies is None:
                        response = await fetch(self._client, url, self.config, fallback_url=fallback_url)
                    else:
                        response = await self._through_proxies(url, fallback_url)
                    break
                except Exception as e:
                    # retries used up on a server error while the server is down (the breaker paused, at the
                    # latest by this request's last error): wait the outage out and try again, instead of failing
                    if waits < BREAKER_WAITS and self.breaker.paused and _server_error(e):
                        await self.breaker.wait_out()
                        continue
                    raise
            record["status"] = response.status_code
            response.extensions[FETCH_KEY] = record
            return response
        except Exception as e:
            record["error"] = type(e).__name__
            if not str(e):                                # httpx's timeouts say nothing: say at least that much
                e.args = (f"{type(e).__name__} (no message) after {record['attempts']} attempt(s)",)
            try:
                setattr(e, FETCH_KEY.replace(".", "_"), record)   # the record goes with the exception
            except AttributeError:
                pass
            raise
        finally:
            record["end"] = time.time_ns()
            record.pop("_t", None)
            ticket.queue(False)
            _FETCH.reset(token)
            _TICKET.reset(ticket_token)

    async def _through_proxies(self, url: str, fallback_url: str | None):
        """``url`` through the proxy list (resilient-httpx's retries and blacklist); on 404 ``fallback_url``, as
        pybookget's ``fetch`` does. A status that is not retried (404, 403, ...) raises ``httpx.HTTPStatusError``;
        retries used up raise ``MaxRetriesExceeded`` naming the last error, no proxy left ``StopRequests`` (the run
        stops)."""
        from resilient_httpx import AllProxiesExhausted, MaxRetriesExceeded

        try:
            response = await self._proxies.get(url)
            if response.status_code == 404 and fallback_url:
                logger.warning("{url}: 404, trying the fallback {fallback}", url=url, fallback=fallback_url)
                response = await self._proxies.get(fallback_url)
        except MaxRetriesExceeded as e:
            record = _FETCH.get() or {}
            raise MaxRetriesExceeded(f"after {record.get('attempts', '?')} attempts: {last_error(e.__cause__)}") \
                from e.__cause__
        except AllProxiesExhausted as e:
            waits = [p["ttl_remaining_seconds"] for pool in self._proxies.blacklist_snapshot().values() for p in pool
                     if p["ttl_remaining_seconds"] is not None]
            back = f"the first returns in {_duration(min(waits))}" if waits else "none returns"
            raise StopRequests(f"no proxy left for {urlsplit(url).hostname}: every one is left out ({back}); "
                               "the run stops instead of failing every item that follows") from e
        response.raise_for_status()
        return response

    def submit(self, url: str, fallback_url: str | None = None, expect: str | None = None) -> Future:
        """A future of ``url``'s response. ``expect``: the format it should have (``xml``, ``json``, ``image``):
        through a proxy, an HTML page instead is that proxy's block (see the module docstring)."""
        if self._blocks is not None:
            host = urlsplit(url).hostname or ""
            if host not in self._block_hosts:              # the first request there: its blocks first
                self._block_hosts.add(host)
                live = self._read_blocks(host)
                asyncio.run_coroutine_threadsafe(self._apply_blocks(live), self._loop).result()
        ticket = _Ticket(self, expect)
        ticket.queue(True)
        future = asyncio.run_coroutine_threadsafe(self._fetch(url, fallback_url, ticket), self._loop)
        future.add_done_callback(lambda _: ticket.queue(False))      # also when cancelled before it started
        return future

    def get(self, url: str, fallback_url: str | None = None):
        return self.submit(url, fallback_url).result()

    def new_user_agent(self) -> None:
        """With ``use_fake_user_agent``: a new random browser User-Agent for the requests from now on (the readers
        take one per task); otherwise nothing. The rate limits and the window stay as they are."""
        if not self.config.use_fake_user_agent:
            return
        from fake_useragent import UserAgent

        agent = UserAgent().random

        async def set_header():
            self._client.headers["User-Agent"] = agent
            for c in (self._proxies._clients.values() if self._proxies is not None else ()):
                c.headers["User-Agent"] = agent
            if self._proxies is not None:
                self._proxies._headers = {**self._proxies._headers, "User-Agent": agent}

        asyncio.run_coroutine_threadsafe(set_header(), self._loop).result()

    def close(self) -> None:
        if self._loop.is_closed():
            return
        if self._block_poll is not None:
            self._block_poll.cancel()
        asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result()
        if self._proxies is not None:
            asyncio.run_coroutine_threadsafe(self._proxies.aclose(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()


def proxy_rotation() -> tuple[int, int] | None:
    """(proxies in rotation, proxies) over this process's shared fetchers with a proxy list; None without one."""
    with _SHARED_LOCK:
        counts = [c for f in _SHARED.values() if (c := f.proxies_in_rotation()) is not None]
    return (sum(c[0] for c in counts), sum(c[1] for c in counts)) if counts else None


def paused() -> float | None:
    """Seconds until the next probe of a paused fetcher of this process (``Breaker``; 0: a probe is out); None when
    none is paused."""
    with _SHARED_LOCK:
        waits = [f.breaker.next_try() for f in _SHARED.values() if f.breaker.paused]
    return min(waits) if waits else None


def close_shared() -> None:
    """Close the fetchers ``HTTPFetcher.shared`` keeps (they are daemon threads, so a process may also just end)."""
    with _SHARED_LOCK:
        fetchers = list(_SHARED.values())
        _SHARED.clear()
    for fetcher in fetchers:
        fetcher.close()
