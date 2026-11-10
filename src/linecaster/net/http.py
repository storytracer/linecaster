"""HTTP for linecaster's readers: httpx clients (HTTP/2, reused connections, the environment's proxy settings) on an
event loop in a background thread, for blocking callers such as datatrove blocks, with rate limits
(``linecaster.net.limits``), retries that honor ``Retry-After``, a deadline per attempt and the fallback URL on 404.
Settings: ``HTTPConfig``, and an HTTP policy's per host (``linecaster.net.policy``; the reference:
``docs/reference/http.md``). The defaults follow the HTTP standards; what one site or CDN needs is opt-in per host.

A request is tried up to ``max_retries + 1`` times (``HTTPFetcher._attempts``): a transport error (a timeout, a broken
connection, a proxy error, an attempt past its deadline), a status in ``RETRYABLE_STATUS_CODES`` (408, 425, 429,
500, 502-504 and Cloudflare's 520-524) and an HTML page where an image, XML or JSON was expected (``expect``,
``UnexpectedHTML``: a successful response, an error or login page served with 200) are tried again after ``retry_wait_min * 2**(n-1)`` seconds, at most
``retry_wait_max``, after the n-th failed attempt; on a direct connection at least as long as the response's
``Retry-After`` asks (at most ``retry_after_max``). Every other status fails at once (``httpx.HTTPStatusError``), a 404
after trying the fallback URL, if any, with retries of its own. Retries used up raise the last error (on a direct
connection) or ``MaxRetriesExceeded`` (through proxies). Each attempt must be done within its deadline:
``attempt_timeout`` plus 1 s per ``attempt_min_rate`` bytes of the size the response declares, counted from when it
goes out, after the rate limits; one that takes longer is cut (``httpx.ReadTimeout``) and retried.

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
at a time, which holds its lease, and each worker holds a fair share of the free ones (``per_worker``:
``"share"``, the default), one (``1``) or up to N. The host's rate limits then hold per proxy, so per IP, as servers
count them: its owner spaces the requests through it to a host by the strictest limit (``HTTPFetcher.interval``), and
each attempt goes through the owned proxy whose turn comes first. Each proxy has its
own client (``HTTPFetcher._new_client``: the deadline per attempt and the records below hold as without).

A **block** means "this IP was turned away", through a proxy or direct (the server only sees an IP): a status in the
host's ``block_on`` (``BLOCK_ON``: 429) and, with ``html`` there, an HTML page where another format was expected. It
lasts as long as ``block_wait`` says, on both paths: the response's ``Retry-After`` (at least ``PAUSE_MIN_WAIT``), else
``BLOCK_FIRST_WAIT`` (60 s), twice the last on each repeat. Through proxies the proxy is marked in the broker for
that host (at most ``block_ttl`` without ``Retry-After``) and the request goes on at once through another; direct the
fetcher pauses (``Pause``, below). A block does not count as an attempt. What is in ``stop_on`` (statuses, ``html``)
stops the run at once (``StopRequests``). A **broken proxy** (``PROXY_ERRORS``: a proxy error, no connection to the
proxy, ``broken_after`` times in a row, 3 by default) is marked for every host, first for ``broken_ttl`` (300 s), twice
as long each time it breaks again, at most ``block_ttl``. The owner stops using a marked proxy there at once and
releases it when it is blocked for every host it uses (and claims another free one at once), and whoever claims it
later sees the mark, so no worker sends a request into another's block. The doubling is kept per worker (the
broker's marks hold the ends, not the waits). A timeout, mostly a slow server, and a server error are retried after
the backoff (through the proxy whose turn comes next) without counting against the proxy: ``max_retries + 1``
attempts that were not blocks. When no proxy the worker holds is usable for a host and none is free to claim, its
requests to that host wait (a pause: one warning when it begins and one when it ends, the wait in ``pause_seconds``)
until a block ends or another worker gives a proxy back; once the waits since the host's last successful response
would pass its ``max_pause`` (``PauseTotal``, as direct), the run stops instead (``StopRequests``). Proxy URLs are never logged or written with their credentials (``redact``; the broker
names proxies by a hash, ``linecaster.net.proxies.proxy_id``).

A fetcher pauses while its server fails (``Breaker``): when most recent attempts got a server error (5xx, Cloudflare's
520-524 among them), no request goes out except a probe now and then, with waits that double up to ten minutes; the
first probe the server answers ends the pause. Requests waiting there count as waiting for the rate limits, so the
window does not grow, and their pages are delayed, not failed. The retries themselves are ``HTTPFetcher._attempts``'s
(520-524 included).

A fetcher also pauses at a block on a direct connection (``Pause``, one per host; through proxies the proxy is left
out instead, above): the fetcher's requests to that host wait until the block's end has passed (``block_wait``:
``Retry-After`` in seconds or as an HTTP-date, else 60 s doubling while the blocks keep coming, at most
``max_pause``). The request that got it
waits out the pause and is tried again, without using up one of its retries (the retries never see the status: the
response hook takes it first), and a block that comes for a request already in flight extends the pause, never
shortens it. Requests waiting in a pause count as waiting for the rate limits, so the window does not
grow. Requests to other hosts and other fetchers (other workers, other host settings) go on. A fetcher whose requests
to a host would wait more than the host's ``max_pause`` (``MAX_PAUSE``, 6 hours) in all since its last successful
response stops the run instead (``StopRequests``): ``PauseTotal`` counts the pauses direct and the waits for a
usable proxy through proxies, per host.

A fetch that fails keeps its record too: it travels with the exception (``FETCH_KEY`` as an attribute, ``failed_fetch``),
so a failed page's trace shows its attempts; and its message names what failed last (``after 5 attempts: HTTP 520``,
``ReadTimeout (no message)``; blocks are not among the attempts it counts), where httpx's own can be empty.

Every fetch records its attempts (``tries``): per attempt ``"200"`` (or another status) for a response read whole,
``"200-cut"`` for one cut after its headers (the deadline per attempt), ``"200-html"`` for an HTML page where another
format was expected (a failed attempt, or a block with ``html`` in ``block_on``), ``"no-response"`` for none (a timeout, a connection or proxy error), so a trace tells a slow server from one
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
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import quote, urlsplit

from loguru import logger

from ..errors import ServerError
from ..formats.manifests import METS_IMAGE_GROUPS, METS_OCR_GROUPS
from .limits import RateLimiter, check_rate_limits

if TYPE_CHECKING:
    from .proxies import ProxyPool

T = TypeVar("T")
S = TypeVar("S")

#: the User-Agent sent by default: datatrove's (``HTTPFetchReader``'s ``custom_agent``), deliberately. datatrove is
#: integral to linecaster, so a run that fetches through both presents itself as one client to every host; a run sets
#: its own with ``--user-agent`` or an HTTP policy's ``user_agent``
USER_AGENT = "HF-Research/1.0"
#: the statuses tried again (the server is busy, overloaded or briefly failing, including Cloudflare's 520-524: its
#: origin sent an unusable answer, refused, or timed out); every other 4xx and 5xx is final
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})


@dataclass
class HTTPConfig:
    """How a fetcher's requests go out (``HTTPFetcher``'s ``config``, a reader's ``http``), with linecaster's
    settings for bulk work as defaults: datatrove's User-Agent, reused connections, patient retries (4 after the
    first attempt), and a deadline per attempt (15 s plus 1 s per 50 kB the response says it holds, counted after the
    rate limits), so a connection that hangs or trickles (a slow proxy exit) is cut and retried within seconds.

    Attributes:
        user_agent: the User-Agent of every request.
        use_fake_user_agent: a random browser User-Agent instead (fake-useragent), a new one per task
            (``HTTPFetcher.new_user_agent``).
        proxy: a proxy for every request; None: the environment's settings, if ``trust_env``.
        trust_env: read the proxy settings (``HTTPS_PROXY``, ``HTTP_PROXY``, ``ALL_PROXY``, ``NO_PROXY``),
            ``SSL_CERT_FILE`` and ``.netrc`` from the environment, as httpx does.
        verify_ssl: verify TLS certificates.
        timeout: seconds for each phase of a request (connect, read, write, pool).
        max_keepalive_connections: idle connections kept open for reuse.
        max_retries: retries after the first attempt (0: one attempt).
        retry_wait_min, retry_wait_max: the wait after the n-th failed attempt is ``retry_wait_min * 2**(n-1)``
            seconds, at most ``retry_wait_max``.
        retry_after_max: the longest ``Retry-After`` honored by a retry on a direct connection.
        attempt_timeout: the longest one attempt may take, from when it goes out (after the rate limits) to its
            last byte, plus 1 s per ``attempt_min_rate`` bytes the response declares (``Content-Length``); None:
            only ``timeout``.
        attempt_min_rate: bytes per second a large response is given.
        rate_limits: ``(N, S)`` windows, at most N requests in any S seconds, all at once (``linecaster.net.limits``);
            None: none.
        iiif_format, iiif_quality: the image format and quality asked of an IIIF image service
            (``linecaster.formats.manifests.read_manifest``).
        mets_image_groups, mets_ocr_groups: the METS file groups of page images, by priority, and of OCR.
    """

    user_agent: str = USER_AGENT
    use_fake_user_agent: bool = False
    proxy: str | None = None
    trust_env: bool = True
    verify_ssl: bool = True
    timeout: float = 300.0
    max_keepalive_connections: int = 16
    max_retries: int = 4
    retry_wait_min: float = 2.0
    retry_wait_max: float = 60.0
    retry_after_max: float = 300.0
    attempt_timeout: float | None = 15.0
    attempt_min_rate: float | None = 50_000
    rate_limits: list[tuple[int, float]] | None = None
    iiif_format: str = "jpg"
    iiif_quality: str = "default"
    mets_image_groups: tuple[str, ...] = METS_IMAGE_GROUPS
    mets_ocr_groups: tuple[str, ...] = METS_OCR_GROUPS

    def __post_init__(self):
        if self.rate_limits is not None:
            self.rate_limits = check_rate_limits(self.rate_limits) or None


#: ``HTTPConfig``'s defaults
HTTP_DEFAULTS = {f.name: f.default for f in fields(HTTPConfig)}


#: the statuses that block by default (an HTTP policy's ``block_on``): the server's "too many requests"
BLOCK_ON = (429,)
#: a block without ``Retry-After`` lasts this long at first, and twice as long as the last one on each repeat
#: (``block_wait``)
BLOCK_FIRST_WAIT = 60.0
#: through proxies, the longest a blocked proxy is left out without ``Retry-After`` (``block_ttl``): the ceiling of
#: the doubling, and of a broken proxy's
BLOCK_TTL = 3600.0
#: a proxy that fails this many attempts in a row itself (``PROXY_ERRORS``) is broken: left out for every host
#: (``broken_after``) ...
BROKEN_AFTER = 3
#: ... first for this many seconds (``broken_ttl``), twice as long on each repeat, at most ``block_ttl``
BROKEN_TTL = 300.0
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
    if isinstance(error, UnexpectedHTML):
        return str(error)
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None) is not None:
        return f"HTTP {response.status_code}"
    return f"{type(error).__name__}: {error}" if str(error) else f"{type(error).__name__} (no message)"


def _server_error(error: BaseException) -> bool:
    """Whether ``error`` (an ``httpx.HTTPStatusError``, or ``MaxRetriesExceeded`` through proxies) is a server
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
        self.generations: dict[str, int] = {}    # host -> its pauses begun when the attempt to it went out

    def queue(self, queued: bool) -> None:
        with self.fetcher._lock:
            if self.queued != queued:
                self.queued = queued
                self.fetcher._waiting += 1 if queued else -1


def _now() -> float:
    """The fetcher's clock (``HTTPFetcher``'s ``clock``) in a fetch's task, else ``time.monotonic``."""
    ticket = _TICKET.get()
    return ticket.fetcher._clock() if ticket is not None else time.monotonic()


async def _before(request) -> None:
    record = _FETCH.get()
    if record is not None:
        record["attempts"] += 1
        record["tries"].append("no-response")             # until its response comes
        record["_t"] = _now()
    if (ticket := _TICKET.get()) is not None:
        ticket.queue(True)


async def _after(request) -> None:              # after the rate limits' hook: the time they made it wait
    if (ticket := _TICKET.get()) is not None:
        ticket.queue(False)
    record = _FETCH.get()
    if record is not None and "_t" in record:
        record["wait_seconds"] = round(record["wait_seconds"] + _now() - record.pop("_t"), 4)


#: where a request keeps when its attempt went out (``request.extensions``, the event loop's clock)
_ATTEMPT_START = "linecaster.attempt_start"


def attempt_deadline(attempt_timeout: float, attempt_min_rate: float | None, content_length: str | None) -> float:
    """Seconds one attempt may take: ``attempt_timeout``, plus the response's ``Content-Length`` divided by
    ``attempt_min_rate`` when both are known (a large file gets the time it needs at that rate)."""
    seconds = float(attempt_timeout)
    if attempt_min_rate and content_length and content_length.isdigit():
        seconds += int(content_length) / attempt_min_rate
    return seconds


def _attempt_started(attempt_timeout: float):
    """A request hook, after the rate limits: the attempt's deadline starts, and until the response's headers no phase
    (connect, read, write, pool) may take longer than the whole attempt."""
    async def hook(request) -> None:
        request.extensions[_ATTEMPT_START] = asyncio.get_running_loop().time()
        limit = float(attempt_timeout)
        timeouts = dict(request.extensions.get("timeout") or {})
        request.extensions["timeout"] = {phase: limit if timeouts.get(phase) is None else min(timeouts[phase], limit)
                                         for phase in ("connect", "read", "write", "pool")}
    return hook


def _attempt_finished(attempt_timeout: float, attempt_min_rate: float | None):
    """A response hook: the body is read within the attempt's deadline (``attempt_deadline``), else the attempt is
    cut with ``httpx.ReadTimeout`` (retried like a timeout)."""
    async def hook(response) -> None:
        start = response.request.extensions.get(_ATTEMPT_START)
        if start is None:
            return
        seconds = attempt_deadline(attempt_timeout, attempt_min_rate, response.headers.get("Content-Length"))
        remaining = start + seconds - asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(max(remaining, 0.0)):
                await response.aread()
        except TimeoutError:
            import httpx

            await response.aclose()
            raise httpx.ReadTimeout(f"attempt took longer than its deadline ({seconds:.1f} s)",
                                    request=response.request) from None
    return hook


class StopRequests(ServerError):
    """A host answered with a status its policy stops the run on (``stop_on``, ``linecaster.net.policy``), raised
    before any retry since a retry would only prolong its block; a fetcher would pause longer than its host's
    ``max_pause`` (``Pause``); or every proxy of a host is left out. A ``ServerError``: it stops the run
    (``NOT_THE_PAGES``)."""


class Paused(Exception):
    """An attempt got a block on the direct path (``block_on``, ``Pause``): raised by the response hook (or, for an
    HTML page, by ``HTTPFetcher._attempts``), so the retries do not take it (neither an ``httpx.HTTPStatusError`` nor
    a ``TransportError``), and the fetch tries again once the pause is over (``HTTPFetcher._fetch``)."""


#: what the formats a fetch can expect (``HTTPFetcher.submit``'s ``expect``) are called in an error
EXPECTED = {"image": "an image", "xml": "XML", "json": "JSON", "manifest": "a manifest (JSON or XML)"}


class UnexpectedHTML(Exception):
    """A successful response (2xx) with an HTML page where another format was expected (``expect``): an error page
    served with 200, a soft 404, a login page after a redirect. Unless the host's policy has ``html`` in ``block_on``
    or ``stop_on`` it is an ordinary failed attempt, retried; after the last one the fetch fails with it (through
    proxies as ``MaxRetriesExceeded``'s cause). The message names the expected format and the content type."""

    def __init__(self, url: str, expect: str, content_type: str | None, size: int):
        what = EXPECTED.get(expect, expect)
        super().__init__(f"an HTML page ({content_type or 'no content type'}, {size} bytes) where {what} was "
                         f"expected: {url}")


class MaxRetriesExceeded(Exception):
    """A request through the proxies used up its attempts (``max_retries + 1`` that were not blocks); the message
    names the attempts and what failed last, the cause is the last error (an ``httpx.HTTPStatusError`` for a
    status)."""


def _unexpected_html(response, expect: str | None) -> bool:
    """Whether ``response`` is a successful one with an HTML page where ``expect`` (not None, not ``html``) was
    expected."""
    return bool(expect) and expect != "html" and 200 <= response.status_code < 300 and _is_html(response)


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
            _trace(str(status))
            raise StopRequests(f"HTTP {status} from {response.request.url.host}: its policy stops "
                               "the run here (stop_on), without a retry")
        if status in fetcher.block_on and fetcher._proxies is None:     # a block on the direct path: a pause
            host = response.request.url.host
            _trace(str(status))
            pause = fetcher.pause_for(host)
            pause.hit(status, response.headers.get("retry-after"), ticket.generations.get(host, pause.generation),
                      host)
            raise Paused(f"HTTP {status} from {host}: its requests pause")
        fetcher.breaker.record(status)
    record = _FETCH.get()
    if record is not None and record["tries"]:
        record["tries"][-1] = f"{response.status_code}-cut"


async def _read(response) -> None:             # the last response hook: read whole (the deadline did not cut it)
    _trace(str(response.status_code))


def _trace(entry: str) -> None:
    """The fetch's record says what its last attempt got (``tries``)."""
    record = _FETCH.get()
    if record is not None and record["tries"]:
        record["tries"][-1] = entry


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


#: the shortest block, whatever ``Retry-After`` says (0, a date gone by)
PAUSE_MIN_WAIT = 1.0
#: the most a fetcher pauses in all since its last successful response (a host's ``max_pause``); a pause beyond it
#: stops the run. Also the longest wait for a usable proxy, and the ceiling of the doubling on the direct path
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


def block_wait(asked: float | None, last: float | None, cap: float,
               first: float = BLOCK_FIRST_WAIT) -> tuple[float, float | None]:
    """How long a block lasts, on the direct path (a pause, ``Pause``) and through proxies (a proxy left out for the
    host, ``linecaster.net.proxies.ProxyPool.block``), and how long a broken proxy is left out.

    Args:
        asked: the seconds the response's ``Retry-After`` asks for (``retry_after``), or None without one.
        last: the last wait without ``Retry-After`` since the doubling started again (None: none; ``doubling``).
        cap: the longest wait without ``Retry-After`` (``block_ttl`` through proxies, ``max_pause`` direct).
        first: the first wait without ``Retry-After``.

    Returns:
        (the wait in seconds, what ``last`` is next time): with ``Retry-After`` exactly that, at least
        ``PAUSE_MIN_WAIT``, and ``last`` unchanged; without, ``first``, then twice ``last``, at most ``cap``.
    """
    if asked is not None:
        return max(asked, PAUSE_MIN_WAIT), last
    wait = min(first if last is None else last * 2, cap)
    return wait, wait


def doubling(last: float | None, ended: float | None, now: float) -> float | None:
    """The doubling's last wait for a block that comes ``now`` (``block_wait``'s ``last``): ``last``, or None (start
    again at the first wait) once the quiet period has passed: as long as ``last`` again after the last block there
    ended (``ended``; any block, with ``Retry-After`` or without), with no block in between. A successful response
    starts it again too (the callers forget ``last``). One rule on both paths: direct per host (``Pause``), through
    proxies per proxy and host, shared through the broker (``linecaster.net.proxies.ProxyPool.block``).

    Args:
        last: the last wait without ``Retry-After``, or None.
        ended: when the last block there ended (the clock of ``now``), or None.
        now: the time now.
    """
    if last is None or ended is None or now - ended <= last:
        return last
    return None


def _what(status: int | str) -> str:
    return f"HTTP {status}" if isinstance(status, int) else "an HTML page"


def _at(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class PauseTotal:
    """What a host's ``max_pause`` counts, one definition for both paths: the seconds a worker's requests to the host
    have spent waiting since the host's last successful response (``answered``), direct in pauses (``Pause``: the
    length each block adds), through proxies waiting for a usable proxy (``HTTPFetcher._no_proxy``: the time no proxy
    was usable there). Once the next wait would take it past ``max_total`` the run stops (``check``:
    ``StopRequests``). The breaker's waits (an outage, ``Breaker``) do not count: each request waits one out at most
    ``BREAKER_WAITS`` times, then fails. One per host and fetcher (``HTTPFetcher.total_for``); used from the
    fetcher's event loop only."""

    def __init__(self, max_total: float = MAX_PAUSE):
        self.max_total, self.spent = max_total, 0.0

    def check(self, more: float, why: str, host: str) -> None:
        """``StopRequests`` if waiting another ``more`` seconds would take the total past ``max_total``; ``why``: what
        the wait is for (``HTTP 429 from library.test``)."""
        if self.spent + more > self.max_total:
            raise StopRequests(
                f"{why}: {host}'s requests waited {_duration(self.spent)} since its last successful response, and "
                f"another {_duration(more)} would pass max_pause ({_duration(self.max_total)}): the run stops")

    def add(self, seconds: float) -> None:
        self.spent += max(0.0, seconds)

    def answered(self) -> None:
        """A successful response from the host: the count starts again."""
        self.spent = 0.0


class Pause:
    """Pauses a fetcher's requests to one host after a block there on the direct path (a status in its ``block_on``,
    or an HTML page with ``html`` there): ``hit`` starts the pause, for as long as ``block_wait`` says (the response's
    ``Retry-After``, else ``first_wait``, doubled for each block that comes for a request sent after the pause
    before, until a successful response or the quiet period of ``doubling``, at most ``max_total``); a block for a
    request already in flight when the pause began extends the pause to its own end, never shortens it. While it lasts
    no request to the host goes out (``wait``, in the request hooks before and after the rate limits); the fetcher's
    requests to other hosts go on. ``total``: what counts toward ``max_pause`` (``PauseTotal``); a pause that would
    take it past ``max_total`` is not taken, the run stops (``StopRequests``). Kept apart from the ``Breaker`` (an
    outage: a share of server errors, probes): here the server says how long. ``clock`` (monotonic), ``wall_clock``
    (seconds since the epoch, for an HTTP-date) and ``sleep`` can be replaced in tests. Used from the fetcher's event
    loop only."""

    def __init__(self, first_wait: float = BLOCK_FIRST_WAIT, max_total: float = MAX_PAUSE,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time,
                 sleep: Callable | None = None, total: PauseTotal | None = None):
        self.first_wait = first_wait
        self.total = total if total is not None else PauseTotal(max_total)
        self._clock, self._wall, self._sleep = clock, wall_clock, sleep or asyncio.sleep
        self.until: float | None = None          # monotonic; None: no pause (or its end announced)
        self.status: int | str | None = None     # what began the pause now: a status, or ``html``
        self.host = ""
        self.generation = 0                      # the pauses begun
        self._wait: float | None = None          # the last wait without Retry-After; None: the doubling starts again
        self._ended: float | None = None         # when the last pause ended (monotonic), for ``doubling``
        self._began: float | None = None

    @property
    def max_total(self) -> float:
        return self.total.max_total

    @property
    def spent(self) -> float:
        """Seconds paused since the host's last successful response (``PauseTotal``)."""
        return self.total.spent

    def remaining(self) -> float:
        """Seconds until the pause ends (0: none)."""
        return max(0.0, self.until - self._clock()) if self.until is not None else 0.0

    @property
    def paused(self) -> bool:
        return self.remaining() > 0

    def hit(self, status: int | str, retry_after_header: str | None, generation: int, host: str = "") -> None:
        """A block (``status``: a status in ``block_on``, or ``html``) and its response's ``Retry-After`` header, for
        a request that went out when ``generation`` pauses had begun: start the pause or extend it; ``StopRequests``
        instead when it would take the pauses since the last successful response past ``max_total``."""
        self._announce_end()
        now = self._clock()
        fresh = generation == self.generation and not self.paused    # sent after the pause before, if any
        asked = retry_after(retry_after_header, self._wall())
        if asked is None and self._wait is not None and not fresh:
            asked = self._wait                   # in flight when the pause began: the same wait, not doubled
        else:
            last = doubling(self._wait, self._ended, now) if fresh else self._wait
            asked, self._wait = block_wait(asked, last, self.max_total, self.first_wait)
        ongoing = self.paused
        added = now + asked - (self.until if ongoing else now)
        if added <= 0:                           # within the pause already
            return
        self.total.check(added, f"{_what(status)} from {host or 'the host'}", host or "the host")
        self.total.add(added)
        if ongoing:
            logger.debug("{what} from {host}: the pause lasts until {until}", what=_what(status), host=host,
                         until=_at(self._wall() + asked))
        else:
            self.generation += 1
            self._began, self.status, self.host = now, status, host
            logger.warning("{what} from {host}: its requests pause for {wait}, until {until}", what=_what(status),
                           host=host, wait=_duration(asked), until=_at(self._wall() + asked))
        self.until = self._ended = now + asked

    def answered(self, generation: int) -> None:
        """A successful response to a request that went out when ``generation`` pauses had begun: if it went out
        after the last pause, the count toward ``max_total`` and the doubling start again."""
        if generation == self.generation and not self.paused:
            self.total.answered()
            self._wait = None

    def _announce_end(self) -> None:
        if self.until is not None and self._clock() >= self.until:
            logger.warning("requests to {host} go on after a pause of {paused}", host=self.host,
                           paused=_duration(self.until - (self._began or self.until)))
            self.until = None

    async def wait(self) -> float:
        """Return when no pause holds, with the seconds waited (0.0 without a pause)."""
        start, waited = self._clock(), False
        while (left := self.remaining()) > 0:
            waited = True
            await self._sleep(min(PAUSE_POLL, max(0.01, left)))
        self._announce_end()
        return self._clock() - start if waited else 0.0


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
        pause = fetcher.pause_for(request.url.host)
        _paused_for(await pause.wait())
        await fetcher.breaker.wait_turn()
        _paused_for(await pause.wait())           # one begun while the breaker held the request


async def _hold(request) -> None:               # a request hook, right after the rate limits'
    """A pause of the request's host that began while it waited for the rate limits holds it too; after the pause it
    waits for them again, so the requests held do not go out at once."""
    if (ticket := _TICKET.get()) is not None:
        fetcher, host = ticket.fetcher, request.url.host
        pause = fetcher.pause_for(host)
        while pause.paused:
            _paused_for(await pause.wait())
            if fetcher._limiter is not None:
                await fetcher._limiter.acquire()
        ticket.generations[host] = pause.generation


_SHARED: dict[tuple, HTTPFetcher] = {}
_SHARED_LOCK = threading.Lock()


class HTTPFetcher:
    """GETs from blocking code: ``submit`` returns a ``concurrent.futures.Future`` of the read ``httpx.Response``,
    ``get`` waits for it. ``config``: ``HTTPConfig`` fields over its defaults (``HTTP_DEFAULTS``), e.g.
    ``rate_limits=[(5, 1), (200, 60)]``, ``iiif_format="png"``. ``waiting``: the
    requests submitted that wait for the rate limits; ``ahead``: the window ``prefetched`` has grown to.

    Args:
        proxy_file: a proxy list (``read_proxies``); None: direct (or the environment's proxy settings).
        broker, default_broker, broker_run: the broker through which the workers share the proxies
            (``linecaster.broker.shared``): ``broker``, else ``default_broker``; ``broker_run`` names the run.
        per_worker: how many proxies of the list the worker holds (``linecaster.net.proxies``): ``"share"``, 1 or N.
        block_on: what blocks (statuses and ``html``; default ``BLOCK_ON``): through proxies the proxy is left out
            for the host, direct the fetcher pauses (``Pause``).
        stop_on: what stops the run at once (statuses and ``html``; ``StopRequests``).
        max_pause: the most the fetcher pauses in all since the host's last successful response, and the longest
            wait for a usable proxy, before the run stops.
        block_ttl: through proxies, the longest a blocked proxy is left out without ``Retry-After``.
        broken_after, broken_ttl: a proxy that fails ``broken_after`` attempts in a row itself is left out for every
            host, first for ``broken_ttl`` seconds, twice as long on each repeat, at most ``block_ttl``.
        first_wait: the first wait of a block without ``Retry-After`` (``block_wait``).
        clock, wall_clock, sleep: monotonic seconds, seconds since the epoch and ``asyncio.sleep``, for the waits
            (backoff, pauses, the wait for a proxy); replaced in tests.
    """

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

    def __init__(self, proxy_file: str | None = None, broker: str | None = None, default_broker: str | None = None,
                 broker_run: str | None = None, per_worker: int | str = "share",
                 block_on: list[int | str] | None = None, stop_on: list[int | str] | None = None,
                 max_pause: float = MAX_PAUSE, block_ttl: float = BLOCK_TTL, broken_after: int = BROKEN_AFTER,
                 broken_ttl: float = BROKEN_TTL, first_wait: float = BLOCK_FIRST_WAIT,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time,
                 sleep: Callable | None = None, **config):
        self.config = HTTPConfig(**config)
        self._limiter = RateLimiter(self.config.rate_limits) if self.config.rate_limits else None
        self._lock, self._waiting, self.ahead = threading.Lock(), 0, 1
        self._clock, self._wall, self._sleep = clock, wall_clock, sleep or asyncio.sleep
        self.breaker = Breaker(in_a_row=self.config.max_retries + 1)      # as many as a request's attempts
        self.stop_on = frozenset(stop_on or ())
        self.block_on = frozenset(BLOCK_ON if block_on is None else block_on) - self.stop_on
        self.block_ttl, self.broken_after, self.broken_ttl = block_ttl, broken_after, broken_ttl
        self.first_wait, self.max_pause = first_wait, max_pause
        self._pauses: dict[str, Pause] = {}                 # host -> its pause (direct)
        self._totals: dict[str, PauseTotal] = {}            # host -> what counts toward its max_pause
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="linecaster-http", daemon=True)
        self._thread.start()

        async def client():
            return self._new_client(self.config.proxy)

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()
        self._proxies: ProxyPool | None = None
        self._proxy_clients: dict[str, object] = {}
        self._no_proxy_since: dict[str, float] = {}        # host -> since when no proxy is usable there (``clock``)
        if proxy_file:
            from .. import broker as brokers
            from .proxies import shared_pool

            self._proxies = shared_pool(brokers.shared(broker or default_broker, run=broker_run),
                                        read_proxies(proxy_file), per_worker)

    def _new_client(self, proxy: str | None, rate_limited: bool = True):
        """An httpx client for ``proxy`` (None: the environment's settings) with linecaster's hooks: before a request
        the pause and the breaker (``_turn``), this fetcher's rate limits unless ``rate_limited`` is False (a proxy's
        client: the proxy pool spaces its requests, ``ProxyPool.pick``), a pause begun meanwhile (``_hold``), then the
        attempt's deadline starts; after its headers the statuses that pause or stop (``_headers``), the body read
        within the deadline, the trace (``_read``)."""
        import httpx

        config, limiter = self.config, self._limiter if rate_limited else None
        if config.use_fake_user_agent:
            from fake_useragent import UserAgent

            agent = UserAgent().random
        else:
            agent = config.user_agent
        request, response = [_before, _turn], [_headers]
        if limiter is not None:
            async def _rate_limits(_request) -> None:
                await limiter.acquire()

            request.append(_rate_limits)
        request.append(_hold)
        if config.attempt_timeout is not None:
            request.append(_attempt_started(config.attempt_timeout))
            response.append(_attempt_finished(config.attempt_timeout, config.attempt_min_rate))
        request.append(_after)
        response.append(_read)
        return httpx.AsyncClient(headers={"User-Agent": agent}, timeout=config.timeout, verify=config.verify_ssl,
                                 follow_redirects=True, http2=True, proxy=proxy, trust_env=config.trust_env,
                                 limits=httpx.Limits(max_keepalive_connections=config.max_keepalive_connections),
                                 event_hooks={"request": request, "response": response})

    def total_for(self, host: str) -> PauseTotal:
        """What counts toward ``host``'s ``max_pause`` (``PauseTotal``), on either path; changed in the event loop
        only."""
        total = self._totals.get(host)
        if total is None:
            with self._lock:
                total = self._totals.setdefault(host, PauseTotal(self.max_pause))
        return total

    def pause_for(self, host: str) -> Pause:
        """``host``'s pause (``Pause``; direct, a block pauses only the requests to its host); changed in the event
        loop only."""
        pause = self._pauses.get(host)
        if pause is None:
            total = self.total_for(host)
            with self._lock:
                pause = self._pauses.setdefault(host, Pause(self.first_wait, clock=self._clock, wall_clock=self._wall,
                                                            sleep=self._sleep, total=total))
        return pause

    def pauses(self) -> list[Pause]:
        """The pauses of the hosts this fetcher has sent requests to (direct)."""
        return list(self._pauses.values())

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
        record = {"start": time.time_ns(), "host": urlsplit(url).hostname or "", "attempts": 0, "wait_seconds": 0.0,
                  "tries": []}
        token, ticket_token = _FETCH.set(record), _TICKET.set(ticket)
        try:
            waits = 0
            while True:
                openings = self.breaker.openings
                try:
                    response = await self._attempts(url, fallback_url, ticket.expect)
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
                        await self._sleep(wait)
                        if record is not None:
                            record["wait_seconds"] = round(record["wait_seconds"] + wait, 4)
                    if not pool.usable(proxy, host):           # blocked by another request meanwhile
                        continue
                    self._proxy_usable(host)
                    pool.tick()
                    return proxy
                if await asyncio.to_thread(pool.fill, host) or pool.has_usable(host):
                    continue                                   # claimed (here or by a request alongside)
                started = self._clock()
                await self._sleep(self._no_proxy(host))
                _paused_for(self._clock() - started)
        finally:
            if ticket is not None:
                ticket.queue(False)

    def _no_proxy(self, host: str) -> float:
        """No proxy is usable for ``host``: the wait begins (one warning) or goes on; returns how long to sleep before
        looking again. ``StopRequests`` when the wait would take the host's ``PauseTotal`` past ``max_pause``: when no
        proxy that other workers hold is usable there and the first block ends too late (or none ends), or once it
        has."""
        now = self._clock()
        first, others, free = self._proxies.outlook(host)
        if free:                                         # one to claim at the next fill: no pause
            return FILL_WAIT
        since = self._no_proxy_since.get(host)
        if since is None:
            since = self._no_proxy_since[host] = now
            log = logger.warning if first is not None else logger.info
            log("no proxy usable for {host}: {why}; its requests wait{until}", host=host,
                why=(f"{others} held by other workers" if first is None else
                     f"the others blocked or held by other workers ({others})"),
                until=f", the first block ends in {_duration(first)}" if first is not None else "")
        total, waited = self.total_for(host), now - since
        if others == 0 and first is None:
            raise StopRequests(f"no proxy left for {host}: every one is left out and none returns; the run stops "
                               "instead of failing every item that follows")
        if others == 0:                                  # the wait still to come: until the first block ends
            ahead, why = first, f"no proxy left for {host}: every one is left out (the first returns in " \
                                f"{_duration(first)})"
        else:
            ahead, why = 0.0, f"no proxy usable for {host}: the others are held by other workers ({others})"
        total.check(waited + ahead, why, host)
        return max(0.05, min(PROXY_POLL, first if first is not None else PROXY_POLL))

    def _proxy_usable(self, host: str) -> None:
        since = self._no_proxy_since.pop(host, None)
        if since is not None:
            waited = self._clock() - since
            self.total_for(host).add(waited)
            logger.warning("a proxy is usable for {host} again after {paused}: its requests go on", host=host,
                           paused=_duration(waited))

    def _backoff(self, failed: int, error: BaseException | None) -> float:
        """The wait after the ``failed``-th failed attempt: ``retry_wait_min * 2**(failed-1)``, at most
        ``retry_wait_max``; with ``error`` (a status's, on a direct connection) at least its ``Retry-After``, at most
        ``retry_after_max``."""
        c = self.config
        wait = min(c.retry_wait_max, c.retry_wait_min * 2 ** (failed - 1))
        response = getattr(error, "response", None)
        if response is not None and (asked := retry_after(response.headers.get("retry-after"), self._wall())) is not None:
            wait = max(wait, min(asked, c.retry_after_max))
        return wait

    async def _attempts(self, url: str, fallback_url: str | None, expect: str | None = None):
        """``url``'s response, tried up to ``max_retries + 1`` times; on 404 ``fallback_url`` instead, with attempts
        of its own. Without a proxy list through the fetcher's client; with one, each attempt through this worker's
        proxy whose turn comes next (``ProxyPool``).

        A block (a status in ``block_on``; with ``html`` there an HTML page where ``expect`` was expected) does not
        count as an attempt: through proxies it marks the proxy blocked for the host (``ProxyPool.block``, for as
        long as ``block_wait`` says, at most ``block_ttl`` without ``Retry-After``) and goes on through another at
        once; on the direct path it pauses the fetcher (``Pause``; the status's in the response hook) and the request
        is tried again after the pause. What is in ``stop_on`` raises ``StopRequests``. A broken proxy
        (``PROXY_ERRORS``) counts toward its ``broken_after``. A transport error, a status in
        ``RETRYABLE_STATUS_CODES`` and an HTML page where ``expect`` was expected (``UnexpectedHTML``) are failed
        attempts, tried again after ``_backoff`` (a ``Retry-After`` counts on the direct path only: through proxies
        the next attempt goes out through another one). A status that is not retried (404, 403, ...) raises
        ``httpx.HTTPStatusError``; attempts used up raise the last error, through proxies ``MaxRetriesExceeded``
        naming it; no proxy usable within ``max_pause`` raises ``StopRequests`` (the run stops)."""
        import httpx

        pool, host, ticket = self._proxies, urlsplit(url).hostname or "", _TICKET.get()
        broken = tuple(getattr(httpx, name) for name in PROXY_ERRORS)
        target, attempts, last, fell_back = url, 0, None, False
        while True:
            proxy = await self._proxy_turn(host) if pool is not None else None
            client = self._proxy_client(proxy) if proxy is not None else self._client
            try:
                response = await client.get(target)
            except httpx.TransportError as e:
                if proxy is not None and isinstance(e, broken):
                    pool.broken(proxy, self.broken_after, self.broken_ttl, self.block_ttl)
                last = e
            else:
                status, asked = response.status_code, response.headers.get("retry-after")
                if proxy is not None:
                    if status in self.block_on:
                        pool.block(proxy, host, retry_after(asked, self._wall()), cap=self.block_ttl,
                                   first=self.first_wait, status=status)
                        continue
                    pool.answered(proxy)
                # once; through proxies only when it is another URL (a direct connection asks again for the same)
                if status == 404 and fallback_url and not fell_back and (proxy is None or fallback_url != url):
                    logger.warning("{url}: 404, trying the fallback {fallback}", url=url, fallback=fallback_url)
                    target, attempts, fell_back = fallback_url, 0, True
                    continue
                if _unexpected_html(response, expect):
                    _trace(f"{status}-html")
                    html = UnexpectedHTML(str(response.url), expect, response.headers.get("content-type"),
                                          len(response.content))
                    if "html" in self.stop_on:
                        raise StopRequests(f"{html}: its policy stops the run here (stop_on: html), without a retry")
                    if "html" in self.block_on:
                        if proxy is not None:
                            pool.block(proxy, host, retry_after(asked, self._wall()), cap=self.block_ttl,
                                       first=self.first_wait, status="html")
                            continue
                        where = response.request.url.host
                        pause = self.pause_for(where)
                        generation = ticket.generations.get(where, pause.generation) if ticket else pause.generation
                        pause.hit("html", asked, generation, where)
                        raise Paused(f"an HTML page from {where}: its requests pause")
                    last = html
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if status not in RETRYABLE_STATUS_CODES:
                            raise
                        last = e
                    else:
                        if proxy is not None:
                            pool.answered(proxy, host)         # the doubling of its blocks there starts again
                            self.total_for(host).answered()
                        elif ticket is not None:               # every host that answered on the way (redirects)
                            for r in (*response.history, response):
                                where = r.request.url.host
                                self.pause_for(where).answered(ticket.generations.get(where, -1))
                        return response
            attempts += 1
            if attempts > self.config.max_retries:
                if proxy is None:
                    raise last
                raise MaxRetriesExceeded(f"after {attempts} attempts: {last_error(last)}") from last
            wait = self._backoff(attempts, last if proxy is None else None)
            if wait > 0:
                await self._sleep(wait)

    def submit(self, url: str, fallback_url: str | None = None, expect: str | None = None) -> Future:
        """A future of ``url``'s response. ``expect``: the format it should have (``image``, ``xml``, ``json``,
        ``manifest``; ``EXPECTED``): an HTML page instead is a failed attempt (``UnexpectedHTML``), or a block or a
        stop where the host's policy has ``html`` in ``block_on`` or ``stop_on``; None: any format."""
        ticket = _Ticket(self, expect)
        ticket.queue(True)
        future = asyncio.run_coroutine_threadsafe(self._fetch(url, fallback_url, ticket), self._loop)
        future.add_done_callback(lambda _: ticket.queue(False))      # also when cancelled before it started
        return future

    def get(self, url: str, fallback_url: str | None = None, expect: str | None = None):
        return self.submit(url, fallback_url, expect).result()

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


def pause_left() -> tuple[float, str] | None:
    """(seconds until it ends, what began it: ``HTTP 429``, ``an HTML page``) of the pause of this process's fetchers that ends first (``Pause``); None
    when none is paused."""
    with _SHARED_LOCK:
        pauses = [(p.remaining(), _what(p.status)) for f in _SHARED.values() for p in f.pauses() if p.paused]
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
