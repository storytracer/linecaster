"""HTTP for linecaster's readers: pybookget's HTTP layer (``linecaster[pybookget]``: rate limits, retries that honor
``Retry-After``, the fallback URL on 404, the environment's proxy settings) on an event loop in a background thread,
for blocking callers such as datatrove blocks.

Rate limits hold per ``HTTPFetcher``. Readers share one per process and configuration (``HTTPFetcher.shared``), so
on a direct connection the limits hold per worker, across the tasks it runs one after the other: a server sees the
workers running at once times the limits. With a proxy list they hold per proxy (below).

Readers request ahead (``prefetched``) in a window that sizes itself: it grows while the reader waits for a response
and no request is waiting for the rate limits (``HTTPFetcher.waiting``), so the limits stay busy, rate times latency
in flight, without a setting, up to the rate limits times the deadline per attempt (``HTTPFetcher.max_ahead``; with
a proxy list times the proxies the worker holds). Readers take pages as their requests finish, not in row order, so a
slow request (one being retried) delays only itself.

With a proxy list (``proxy_file``: one proxy per line, ``read_proxies``) the workers share the proxies through the
broker (``broker``, any fsspec folder; ``linecaster.broker``, ``linecaster.net.proxies``): each proxy has one worker
at a time, which holds its lease, and each worker holds a fair share of the free ones (``proxies_per_worker``:
``"share"``, the default), one (``1``) or up to N. The host's rate limits then hold per proxy, so per IP, as servers
count them: its owner spaces the requests through it to a host by the strictest limit (``HTTPFetcher.interval``), and
each attempt goes through the owned proxy whose turn comes first. Each proxy has its
own pybookget client (``create_client``: the deadline per attempt and the records below hold as without). What leaves
a proxy out is what is the proxy's fault: a block (a 429, until its ``Retry-After`` or for the host's
``blacklist_ttl``; a status in the host's ``blacklist_on``; an HTML page where another format was expected) is a mark
in the broker for that host, and a broken proxy (``PROXY_ERRORS``: a proxy error, no connection to the proxy, after
``PROXY_BLACKLIST_THRESHOLD`` failures in a row) one for every host, for ``PROXY_BLACKLIST_TTL`` seconds. The owner
stops using the proxy there at once and releases it when it is blocked for every host it uses (and claims another
free one at once), and whoever claims it later sees the mark, so no worker sends a request into another's block. A block does not count as an attempt: the
request goes on through another proxy at once. A timeout, mostly a slow server, and a server error are retried after
pybookget's backoff (through the proxy whose turn comes next) without counting against the proxy: ``max_retries + 1``
attempts that were not blocks. When no proxy the worker holds is usable for a host and none is free to claim, its
requests to that host wait (a pause: one warning when it begins and one when it ends, the wait in ``pause_seconds``)
until a block ends or another worker gives a proxy back; a pause that would pass the host's ``max_pause`` stops the run
instead (``StopRequests``). Proxy URLs are never logged or written with their credentials (``redact``; the broker
names proxies by a hash, ``linecaster.net.proxies.proxy_id``).

A fetcher pauses while its server fails (``Breaker``): when most recent attempts got a server error (5xx, Cloudflare's
520-524 among them), no request goes out except a probe now and then, with waits that double up to ten minutes; the
first probe the server answers ends the pause. Requests waiting there count as waiting for the rate limits, so the
window does not grow, and their pages are delayed, not failed. The retries themselves are pybookget's (520-524
included), or with a proxy list ``HTTPFetcher._through_proxies``'s with the same counts and waits.

A fetcher also pauses when its server says it gets too many requests (``Pause``): a status in its host's ``pause_on``
(429 by default, ``PAUSE_ON``) on a direct connection (without a proxy list; through proxies a 429 blocks that proxy
instead, above) stops the fetcher's requests until the response's ``Retry-After`` has passed (seconds or an
HTTP-date; without one ``PAUSE_FIRST_WAIT``, doubling while the status keeps coming, up to ``PAUSE_MAX_WAIT``). The
request that got it waits out the pause and is tried again, without using up one of its retries (pybookget never sees
the status: the response hook takes it first), and a status that comes back for a request already in flight extends
the pause, never shortens it. Requests waiting in a pause count as waiting for the rate limits, so the window does not
grow. Other fetchers (other workers, other host settings) go on. A fetcher that would pause more than its host's
``max_pause`` (``MAX_PAUSE``, 6 hours) in all since its last successful response stops the run instead
(``StopRequests``).

A fetch that fails keeps its record too: it travels with the exception (``FETCH_KEY`` as an attribute, ``failed_fetch``),
so a failed page's trace shows its attempts; and its message names what failed last (``after 5 attempts: HTTP 520``,
``ReadTimeout (no message)``; blocks are not among the attempts it counts), where httpx's own can be empty.

Every fetch records its attempts (``tries``): per attempt ``"200"`` (or another status) for a response read whole,
``"200-cut"`` for one cut after its headers (the deadline per attempt), ``"200-html"`` for a block page through a
proxy, ``"no-response"`` for none (a timeout, a connection or proxy error), so a trace tells a slow server from one
that answers 429 or 503.

Every fetch records what it took (``fetch_record``): start and end, the host, the status, the attempts (retries,
blocks and redirects count), the time spent waiting for the rate limits (with a proxy list: for a proxy's turn) and
the time spent in pauses. Readers put the records on the page they fetched (``doc.metadata["trace"]["fetch"]``), which
the tracing turns into ``linecaster.http.fetch`` spans.
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
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import quote, urlsplit

from loguru import logger

from ..errors import ServerError

if TYPE_CHECKING:
    from .proxies import ProxyPool

T = TypeVar("T")
S = TypeVar("S")

#: the User-Agent sent by default: datatrove's (``HTTPFetchReader``'s ``custom_agent``)
USER_AGENT = "HF-Research/1.0"
#: pybookget ``Config`` settings for bulk work: datatrove's user agent, reused connections, patient retries (4 after the
#: first attempt), and a
#: deadline per attempt (15 s plus 1 s per 50 kB the response says it holds, counted after the rate limits), so a
#: connection that hangs or trickles (a slow proxy exit) is cut and retried within seconds
HTTP_DEFAULTS = dict(use_fake_user_agent=False, user_agent=USER_AGENT, max_keepalive_connections=16,
                     max_retries=4, retry_wait_min=2.0, retry_wait_max=60.0, attempt_timeout=15.0,
                     attempt_min_rate=50_000, show_progress=False)


def _pybookget():
    try:
        import pybookget  # noqa: F401
    except ImportError as e:
        raise ImportError("manifests and http(s) images need pybookget: install linecaster[pybookget]") from e


#: a proxy that fails this many attempts in a row itself (``PROXY_ERRORS``) is left out for every host ...
PROXY_BLACKLIST_THRESHOLD = 1
#: ... for this many seconds
PROXY_BLACKLIST_TTL = 3600.0
#: the httpx errors that are a broken proxy's (besides blocks), so they count against it: the proxy refused or failed
#: the tunnel, or could not be reached; a timeout reading the server's answer (a slow server) does not
PROXY_ERRORS = ("ProxyError", "ConnectError", "ConnectTimeout")


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
    """What failed last in a request's retries: ``HTTP 520`` for a retried status, else the error's type and
    message (``ReadTimeout (no message)`` for httpx's silent timeouts)."""
    if error is None:
        return "unknown"
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None) is not None:
        return f"HTTP {response.status_code}"
    return f"{type(error).__name__}: {error}" if str(error) else f"{type(error).__name__} (no message)"


def _server_error(error: BaseException) -> bool:
    """Whether ``error`` (pybookget's ``HTTPStatusError``, or ``MaxRetriesExceeded`` through proxies) is a server
    error."""
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
    ``wait_seconds`` (rate limits, the breaker), ``pause_seconds`` (pauses, ``Pause``; only when the fetch paused);
    None for a response that was not fetched here."""
    return getattr(response, "extensions", {}).get(FETCH_KEY) if response is not None else None


#: the ticket of the fetch running in this task of the event loop: whether it waits for the rate limits
_TICKET: contextvars.ContextVar[_Ticket | None] = contextvars.ContextVar("linecaster_ticket", default=None)


class _Ticket:
    """A fetch's place in ``HTTPFetcher.waiting``: queued from its submission until its first attempt has passed the
    rate limits, and again for each retry until it has passed them."""

    def __init__(self, fetcher: HTTPFetcher, expect: str | None = None):
        self.fetcher, self.queued, self.expect = fetcher, False, expect
        self.generation = 0                      # the fetcher's pauses begun when its attempt went out

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
    """A host answered with a status its policy stops the run on (``stop_on``, ``linecaster.net.policy``), raised
    before any retry since a retry would only prolong its block; a fetcher would pause longer than its host's
    ``max_pause`` (``Pause``); or every proxy of a host is left out. A ``ServerError``: it stops the run
    (``NOT_THE_PAGES``)."""


class Paused(Exception):
    """An attempt got a status that pauses its fetcher (``pause_on``, ``Pause``): raised by the response hook, so
    pybookget does not retry it (neither an ``httpx.HTTPStatusError`` nor a ``TransportError``), and the fetch tries
    again once the pause is over (``HTTPFetcher._fetch``)."""


class ProxyBlocked(Exception):
    """An HTML page through a proxy where another format was expected: that proxy's block (made a ``TransportError``
    where it is raised, so it ends the attempt; ``HTTPFetcher._through_proxies`` marks the proxy blocked for the host
    and goes on through another)."""


class MaxRetriesExceeded(Exception):
    """A request through the proxies used up its attempts (``max_retries + 1`` that were not blocks); the message
    names the attempts and what failed last, the cause is the last error (an ``httpx.HTTPStatusError`` for a
    status)."""


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
        fetcher, status = ticket.fetcher, response.status_code
        if status in fetcher.stop_on:
            raise StopRequests(f"HTTP {status} from {response.request.url.host}: its policy stops "
                               "the run here (stop_on), without a retry")
        if status in fetcher.pause_on and fetcher._proxies is None:
            if (record := _FETCH.get()) is not None and record["tries"]:
                record["tries"][-1] = str(status)
            fetcher.pause.hit(status, response.headers.get("retry-after"), ticket.generation,
                              response.request.url.host)
            raise Paused(f"HTTP {status} from {response.request.url.host}: requests pause")
        if status < 400:
            fetcher.pause.answered(ticket.generation)
        fetcher.breaker.record(status)
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
        self.openings = 0                                # how often it opened

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
            self.openings += 1
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


#: the statuses that pause a fetcher's requests by default (a host's ``pause_on``): the server's "too many requests"
PAUSE_ON = (429,)
#: a pause without a ``Retry-After`` lasts this long at first, doubling while the status keeps coming, up to
#: ``PAUSE_MAX_WAIT``
PAUSE_FIRST_WAIT = 60.0
PAUSE_MAX_WAIT = 3600.0
#: the shortest pause, whatever ``Retry-After`` says (0, a date gone by)
PAUSE_MIN_WAIT = 1.0
#: the most a fetcher pauses in all since its last successful response (a host's ``max_pause``); a pause beyond it
#: stops the run
MAX_PAUSE = 21600.0
#: how often a request waiting in a pause looks again (at the latest)
PAUSE_POLL = 1.0
#: how often a request waiting for a usable proxy looks again (at the latest; ``ProxyPool.fill`` lists the broker
#: at most every ``linecaster.net.proxies.FILL_SECONDS``)
PROXY_POLL = 1.0
#: how long a request that found a proxy to claim waits for the next ``ProxyPool.fill``
FILL_WAIT = 0.25


def retry_after(value: str | None, now: float | None = None) -> float | None:
    """The seconds a ``Retry-After`` header asks for (delta-seconds or an HTTP-date, counted from ``now``, seconds
    since the epoch, default the time now), at least 0; None without one or for one that is neither."""
    from email.utils import parsedate_to_datetime

    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:                      # an HTTP-date is GMT
        from datetime import timezone

        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


def _at(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Pause:
    """Pauses a fetcher's requests after a status its host pauses on (``pause_on``): ``hit`` starts the pause, until
    the response's ``Retry-After`` has passed (``retry_after``; at least ``PAUSE_MIN_WAIT``), or without one for
    ``first_wait``, doubled for each status that comes for a request sent after the pause before (up to
    ``max_wait``); a status for a request already in flight when the pause began extends the pause to its own end,
    never shortens it. While it lasts no request goes out (``wait``, in the request hooks before and after the rate
    limits). ``max_total``: the most it pauses in all since the last successful response (``answered``) before the
    next status stops the run (``StopRequests``); a pause that would pass it is not taken. Kept apart from the
    ``Breaker`` (an outage: a share of server errors, probes): here the server says how long. ``clock`` (monotonic)
    and ``wall_clock`` (seconds since the epoch, for an HTTP-date) can be replaced in tests. Used from the fetcher's
    event loop only."""

    def __init__(self, first_wait: float = PAUSE_FIRST_WAIT, max_wait: float = PAUSE_MAX_WAIT,
                 max_total: float = MAX_PAUSE, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time):
        self.first_wait, self.max_wait, self.max_total = first_wait, max_wait, max_total
        self._clock, self._wall = clock, wall_clock
        self.until: float | None = None          # monotonic; None: no pause (or its end announced)
        self.status: int | None = None           # the status of the pause now
        self.host = ""
        self.generation = 0                      # the pauses begun
        self.spent = 0.0                         # seconds paused since the last successful response
        self._wait: float | None = None          # the last wait without Retry-After; None: none since that response
        self._began: float | None = None

    def remaining(self) -> float:
        """Seconds until the pause ends (0: none)."""
        return max(0.0, self.until - self._clock()) if self.until is not None else 0.0

    @property
    def paused(self) -> bool:
        return self.remaining() > 0

    def hit(self, status: int, retry_after_header: str | None, generation: int, host: str = "") -> None:
        """A response with ``status`` (one to pause on) and its ``Retry-After`` header, to a request that went out
        when ``generation`` pauses had begun: start the pause or extend it; ``StopRequests`` instead when it would
        take the pauses since the last successful response past ``max_total``."""
        self._announce_end()
        now = self._clock()
        fresh = generation == self.generation and not self.paused    # sent after the pause before, if any
        asked = retry_after(retry_after_header, self._wall())
        if asked is None:
            if self._wait is None:
                self._wait = self.first_wait
            elif fresh:
                self._wait = min(self._wait * 2, self.max_wait)
            asked = self._wait
        else:
            asked = max(asked, PAUSE_MIN_WAIT)
        ongoing = self.paused
        added = now + asked - (self.until if ongoing else now)
        if added <= 0:                           # within the pause already
            return
        if self.spent + added > self.max_total:
            raise StopRequests(
                f"HTTP {status} from {host}: paused {_duration(self.spent)} since its last successful response, and "
                f"another {_duration(added)} would pass max_pause ({_duration(self.max_total)}): the run stops")
        self.spent += added
        if ongoing:
            logger.debug("HTTP {status} from {host}: the pause lasts until {until}", status=status, host=host,
                         until=_at(self._wall() + asked))
        else:
            self.generation += 1
            self._began, self.status, self.host = now, status, host
            logger.warning("HTTP {status} from {host}: requests pause for {wait}, until {until}", status=status,
                           host=host, wait=_duration(asked), until=_at(self._wall() + asked))
        self.until = now + asked

    def answered(self, generation: int) -> None:
        """A successful response to a request that went out when ``generation`` pauses had begun: if it went out
        after the last pause, the count toward ``max_total`` and the doubling start again."""
        if generation == self.generation and not self.paused:
            self.spent, self._wait = 0.0, None

    def _announce_end(self) -> None:
        if self.until is not None and self._clock() >= self.until:
            logger.warning("requests to {host} go on after a pause of {paused}", host=self.host,
                           paused=_duration(self.until - (self._began or self.until)))
            self.until = None

    async def wait(self) -> float:
        """Return when no pause holds, with the seconds waited (0.0 without a pause)."""
        start, waited = time.perf_counter(), False
        while (left := self.remaining()) > 0:
            waited = True
            await asyncio.sleep(min(PAUSE_POLL, max(0.01, left)))
        self._announce_end()
        return time.perf_counter() - start if waited else 0.0


def _paused_for(seconds: float) -> None:
    """Note a wait in a pause on the fetch's record: in ``pause_seconds``, not in the rate limits' ``wait_seconds``."""
    record = _FETCH.get()
    if record is not None and seconds > 0:
        record["pause_seconds"] = round(record.get("pause_seconds", 0.0) + seconds, 4)
        if "_t" in record:
            record["_t"] += seconds


async def _turn(request) -> None:               # a request hook, before the rate limits': the pause, the breaker
    if (ticket := _TICKET.get()) is not None:
        fetcher = ticket.fetcher
        _paused_for(await fetcher.pause.wait())
        await fetcher.breaker.wait_turn()
        _paused_for(await fetcher.pause.wait())   # one begun while the breaker held the request


async def _hold(request) -> None:               # a request hook, right after the rate limits'
    """A pause that began while the request waited for the rate limits holds it too; after the pause it waits for
    them again, so the requests held do not go out at once."""
    if (ticket := _TICKET.get()) is not None:
        fetcher = ticket.fetcher
        while fetcher.pause.paused:
            _paused_for(await fetcher.pause.wait())
            if fetcher.config.rate_limits:
                from pybookget.http.ratelimit import wait_for_rate_limit

                await wait_for_rate_limit(fetcher.config)
        ticket.generation = fetcher.pause.generation


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
                 broker: str | None = None, default_broker: str | None = None, broker_run: str | None = None,
                 proxies_per_worker: int | str = "share", stop_on: list[int] | None = None, pause_on: list[int] | None = None, max_pause: float = MAX_PAUSE,
                 pause_wait: float = PAUSE_FIRST_WAIT, pause_max_wait: float = PAUSE_MAX_WAIT, **config):
        _pybookget()
        from pybookget.config import Config

        self.config = Config(**{**HTTP_DEFAULTS, **config})
        self._lock, self._waiting, self.ahead = threading.Lock(), 0, 1
        self.breaker = Breaker(in_a_row=self.config.max_retries + 1)      # as many as a request's attempts
        self.stop_on = frozenset(stop_on or ())
        self.pause_on = frozenset(PAUSE_ON if pause_on is None else pause_on) - self.stop_on
        self.pause = Pause(pause_wait, pause_max_wait, max_pause)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="linecaster-http", daemon=True)
        self._thread.start()

        async def client():
            return self._new_client(self.config.proxy)

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()
        self._proxies: ProxyPool | None = None
        self._proxy_clients: dict[str, object] = {}
        self._blacklist_threshold, self._blacklist_ttl = proxy_blacklist_threshold, proxy_blacklist_ttl
        self._blacklist_on = frozenset({429, *(proxy_blacklist_on or ())})
        self._no_proxy_since: float | None = None          # monotonic: since when no proxy is usable here
        if proxy_file:
            from .. import broker as brokers
            from .proxies import shared_pool

            self._proxies = shared_pool(brokers.shared(broker or default_broker, run=broker_run),
                                        read_proxies(proxy_file), proxies_per_worker)

    def _new_client(self, proxy: str | None, rate_limited: bool = True):
        """pybookget's client for ``proxy`` (None: the environment's settings), with linecaster's hooks; every client
        shares this fetcher's rate limiter (pybookget keeps it per ``Config`` and event loop), unless
        ``rate_limited`` is False (a proxy's client: the proxy pool spaces its requests, ``ProxyPool.pick``)."""
        import dataclasses

        from pybookget.http import create_client

        config = self.config
        if proxy != config.proxy or not rate_limited:
            config = dataclasses.replace(config, proxy=proxy, rate_limits=config.rate_limits if rate_limited else None)
            config._limiters = self.config._limiters
        c = create_client(config)
        hooks = dict(c.event_hooks)
        theirs = list(hooks.get("request", []))         # pybookget's: the rate limits, then the attempt's deadline
        limits = next((i + 1 for i, h in enumerate(theirs) if getattr(h, "__name__", "") == "_wait_for_rate_limit"), 0)
        hooks["request"] = [_before, _turn, *theirs[:limits], _hold, *theirs[limits:], _after]
        hooks["response"] = [_headers, *hooks.get("response", []), _read]
        c.event_hooks = hooks
        return c

    def proxy_counts(self) -> tuple[int, int, int] | None:
        """(proxies this worker holds, blocked, free) with a proxy list (``ProxyPool.counts``), else None."""
        return self._proxies.counts() if self._proxies is not None else None

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def interval(self) -> float:
        """The seconds between two requests through one proxy: the strictest rate limit's (0 without limits)."""
        limits = self.config.rate_limits
        return max(s / n for n, s in limits) if limits else 0.0

    @property
    def max_ahead(self) -> int:
        """The most requests worth having in flight: the rate limits' rate (the strictest window's; with a proxy list
        per proxy, times the proxies this worker holds) times the deadline per attempt, since every attempt ends within
        it; ``MAX_AHEAD`` without either, and never more."""
        limits, deadline = self.config.rate_limits, getattr(self.config, "attempt_timeout", None)
        if not limits or not deadline:
            return MAX_AHEAD
        rate = min(n / s for n, s in limits) * (max(1, self._proxies.held()) if self._proxies is not None else 1)
        return max(1, min(MAX_AHEAD, int(rate * deadline) + 1))

    async def _fetch(self, url: str, fallback_url: str | None, ticket: _Ticket):
        from pybookget.http import fetch

        record = {"start": time.time_ns(), "host": urlsplit(url).hostname or "", "attempts": 0, "wait_seconds": 0.0,
                  "tries": []}
        token, ticket_token = _FETCH.set(record), _TICKET.set(ticket)
        try:
            waits = 0
            while True:
                openings = self.breaker.openings
                try:
                    if self._proxies is None:
                        response = await fetch(self._client, url, self.config, fallback_url=fallback_url)
                    else:
                        response = await self._through_proxies(url, fallback_url)
                    break
                except Paused:
                    continue                   # again once the pause is over (the next attempt waits in a hook)
                except Exception as e:
                    # retries used up on a server error while the server is down (the breaker opened during these
                    # attempts, at the latest at this request's last error, even if a probe has closed it since):
                    # wait the outage out and try again, instead of failing
                    if (waits < BREAKER_WAITS and _server_error(e)
                            and (self.breaker.paused or self.breaker.openings != openings)):
                        waits += 1
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

    def _proxy_client(self, proxy: str):
        client = self._proxy_clients.get(proxy)
        if client is None:
            client = self._proxy_clients[proxy] = self._new_client(proxy, rate_limited=False)
            if (agent := self._client.headers.get("User-Agent")) is not None:
                client.headers["User-Agent"] = agent
        return client

    async def _proxy_turn(self, host: str) -> str:
        """A proxy for the next attempt to ``host``, at its turn (``ProxyPool.pick``): the wait for the turn counts as
        waiting for the rate limits; with none usable, claims more (``ProxyPool.fill``), else pauses until a block
        ends or another worker gives one back (``_no_proxy``)."""
        pool, record, ticket = self._proxies, _FETCH.get(), _TICKET.get()
        if ticket is not None:
            ticket.queue(True)
        try:
            while True:
                got = pool.pick(host, self.interval)
                if got is not None:
                    proxy, wait = got
                    if wait > 0:
                        await asyncio.sleep(wait)
                        if record is not None:
                            record["wait_seconds"] = round(record["wait_seconds"] + wait, 4)
                    if not pool.usable(proxy, host):           # blocked by another request meanwhile
                        continue
                    self._proxy_usable(host)
                    pool.tick()
                    return proxy
                if await asyncio.to_thread(pool.fill, host) or pool.has_usable(host):
                    continue                                   # claimed (here or by a request alongside)
                started = time.perf_counter()
                await asyncio.sleep(self._no_proxy(host))
                _paused_for(time.perf_counter() - started)
        finally:
            if ticket is not None:
                ticket.queue(False)

    def _no_proxy(self, host: str) -> float:
        """No proxy is usable for ``host``: the pause begins (one warning) or goes on; returns how long to sleep before
        looking again. ``StopRequests`` when it would pass ``max_pause`` (a block that ends later, and no proxy that
        other workers hold), or has."""
        now = time.monotonic()
        first, others, free = self._proxies.outlook(host)
        if free:                                         # one to claim at the next fill: no pause
            return FILL_WAIT
        if self._no_proxy_since is None:
            self._no_proxy_since = now
            log = logger.warning if first is not None else logger.info
            log("no proxy usable for {host}: {why}; its requests wait{until}", host=host,
                why=(f"{others} held by other workers" if first is None else
                     f"the others blocked or held by other workers ({others})"),
                until=f", the first block ends in {_duration(first)}" if first is not None else "")
        spent, most = now - self._no_proxy_since, self.pause.max_total
        if spent > most or (others == 0 and (first is None or spent + first > most)):
            back = f"the first returns in {_duration(first)}" if first is not None else "none returns"
            raise StopRequests(f"no proxy left for {host}: every one is left out ({back}), beyond max_pause "
                               f"({_duration(most)}); the run stops instead of failing every item that follows")
        return max(0.05, min(PROXY_POLL, first if first is not None else PROXY_POLL))

    def _proxy_usable(self, host: str) -> None:
        if self._no_proxy_since is not None:
            logger.warning("a proxy is usable for {host} again after {paused}: its requests go on", host=host,
                           paused=_duration(time.monotonic() - self._no_proxy_since))
            self._no_proxy_since = None

    async def _through_proxies(self, url: str, fallback_url: str | None):
        """``url`` through this worker's proxies (``ProxyPool``); on 404 ``fallback_url``, as pybookget's ``fetch``
        does. A block (429, a status in ``blacklist_on``, an HTML page where another format was expected) marks the
        proxy blocked for the host and goes on through another without counting as an attempt; a broken proxy
        (``PROXY_ERRORS``) counts toward its ``blacklist_threshold``; other failures (a retryable status, a timeout)
        are retried after pybookget's backoff. A status that is not retried (404, 403, ...) raises
        ``httpx.HTTPStatusError``; attempts used up raise ``MaxRetriesExceeded`` naming the last error, no proxy
        usable within ``max_pause`` ``StopRequests`` (the run stops)."""
        import httpx
        from pybookget.http.client import RETRYABLE_STATUS_CODES

        host = urlsplit(url).hostname or ""
        broken = tuple(getattr(httpx, name) for name in PROXY_ERRORS)
        target, attempts, last = url, 0, None
        while True:
            proxy = await self._proxy_turn(host)
            try:
                response = await self._proxy_client(proxy).get(target)
            except ProxyBlocked:
                self._proxies.block(proxy, host, self._blacklist_ttl, status="html")
                continue
            except httpx.TransportError as e:
                if isinstance(e, broken):
                    self._proxies.broken(proxy, self._blacklist_threshold, self._blacklist_ttl)
                last = e
            else:
                status = response.status_code
                if status in self._blacklist_on:
                    asked = retry_after(response.headers.get("retry-after"))
                    ttl = self._blacklist_ttl if asked is None else max(asked, PAUSE_MIN_WAIT)
                    self._proxies.block(proxy, host, ttl, status=status)
                    continue
                self._proxies.answered(proxy)
                if status == 404 and fallback_url and target != fallback_url:
                    logger.warning("{url}: 404, trying the fallback {fallback}", url=url, fallback=fallback_url)
                    target, attempts = fallback_url, 0
                    continue
                if status not in RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return response
                last = httpx.HTTPStatusError(f"HTTP {status}", request=response.request, response=response)
            attempts += 1
            if attempts > self.config.max_retries:
                raise MaxRetriesExceeded(f"after {attempts} attempts: {last_error(last)}") from last
            wait = min(self.config.retry_wait_max, self.config.retry_wait_min * 2 ** (attempts - 1))
            if wait > 0:
                await asyncio.sleep(wait)

    def submit(self, url: str, fallback_url: str | None = None, expect: str | None = None) -> Future:
        """A future of ``url``'s response. ``expect``: the format it should have (``xml``, ``json``, ``image``):
        through a proxy, an HTML page instead is that proxy's block (see the module docstring)."""
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
            for c in self._proxy_clients.values():
                c.headers["User-Agent"] = agent

        asyncio.run_coroutine_threadsafe(set_header(), self._loop).result()

    def close(self) -> None:
        if self._loop.is_closed():
            return

        async def close_clients():
            for c in (self._client, *self._proxy_clients.values()):
                await c.aclose()

        asyncio.run_coroutine_threadsafe(close_clients(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()


def proxy_counts() -> tuple[int, int, int] | None:
    """(proxies held, blocked, free) of this process's proxy pools (``linecaster.net.proxies.ProxyPool.counts``);
    None without a proxy list."""
    from .proxies import pools

    counts = [p.counts() for p in pools()]
    return tuple(sum(c[i] for c in counts) for i in range(3)) if counts else None


def paused() -> float | None:
    """Seconds until the next probe of a paused fetcher of this process (``Breaker``; 0: a probe is out); None when
    none is paused."""
    with _SHARED_LOCK:
        waits = [f.breaker.next_try() for f in _SHARED.values() if f.breaker.paused]
    return min(waits) if waits else None


def pause_left() -> tuple[float, int] | None:
    """(seconds until it ends, its status) of the pause of this process's fetchers that ends first (``Pause``); None
    when none is paused."""
    with _SHARED_LOCK:
        pauses = [(f.pause.remaining(), f.pause.status) for f in _SHARED.values() if f.pause.paused]
    return min(pauses) if pauses else None


def close_shared() -> None:
    """Close the fetchers ``HTTPFetcher.shared`` keeps (they are daemon threads, so a process may also just end), and
    hand the worker's proxies over to its slot's next process (``linecaster.net.proxies.close_pools``)."""
    with _SHARED_LOCK:
        fetchers = list(_SHARED.values())
        _SHARED.clear()
    for fetcher in fetchers:
        fetcher.close()
    from .proxies import close_pools

    close_pools()
