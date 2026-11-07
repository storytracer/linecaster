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
``PROXY_BLACKLIST_THRESHOLD`` failures, the retries resilient-httpx's (pybookget's counts and waits; no
``Retry-After``: the next attempt goes out through another proxy). Each proxy's client is made by pybookget's
``create_client``, so the rate limits (shared by all proxies), the deadline per attempt and the records below hold
as without. Proxy URLs are never logged with their credentials (``redact``).

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

T = TypeVar("T")
S = TypeVar("S")

USER_AGENT = "linecaster (+https://github.com/storytracer/linecaster)"
#: pybookget ``Config`` settings for bulk work: an honest user agent, reused connections, patient retries, and a
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


def _proxy_client(fetcher: HTTPFetcher, proxies: list[str], threshold: int, ttl: float):
    """resilient-httpx's ``AsyncProxyHttpClient`` over ``proxies`` whose per-proxy clients are pybookget's
    ``create_client`` (with ``fetcher``'s hooks and its shared rate limiter), retrying as pybookget's ``Config``
    says."""
    try:
        import httpx
        from resilient_httpx import AsyncProxyHttpClient, RetryPolicy
    except ImportError as e:
        raise ImportError("a proxy list needs resilient-httpx: install linecaster[resilient-httpx]") from e
    from pybookget.http.client import RETRYABLE_STATUS_CODES

    config = fetcher.config
    total = len(proxies)

    def blacklisted(pool: str, proxy: str) -> None:
        left = sum(1 for p in client.blacklist_snapshot().get(pool, ()) if p["in_rotation"])
        log = logger.warning if left < max(1, total // 10) else logger.debug
        log("proxy {proxy} left out for {ttl:.0f} s; {left} of {total} in rotation", proxy=redact(proxy), ttl=ttl,
            left=left, total=total)

    class Client(AsyncProxyHttpClient):
        def _get_client(self, proxy, impersonate=False):
            if proxy not in self._clients:
                self._clients[proxy] = fetcher._new_client(proxy)
            return self._clients[proxy]

    client = Client(proxies=proxies, retry=RetryPolicy(
        max_attempts=config.max_retries, backoff="exponential", min_wait=config.retry_wait_min,
        max_wait=config.retry_wait_max, retry_on=sorted(RETRYABLE_STATUS_CODES),
        retry_on_exception=[httpx.TransportError]),
        timeout=config.timeout, blacklist_threshold=threshold, blacklist_ttl=ttl, on_blacklist=blacklisted)
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


def fetch_record(response) -> dict | None:
    """What fetching ``response`` took: ``{"start", "end"}`` (ns since the epoch), ``host``, ``status``, ``attempts``,
    ``wait_seconds`` (rate limits); None for a response that was not fetched here."""
    return getattr(response, "extensions", {}).get(FETCH_KEY) if response is not None else None


#: the ticket of the fetch running in this task of the event loop: whether it waits for the rate limits
_TICKET: contextvars.ContextVar[_Ticket | None] = contextvars.ContextVar("linecaster_ticket", default=None)


class _Ticket:
    """A fetch's place in ``HTTPFetcher.waiting``: queued from its submission until its first attempt has passed the
    rate limits, and again for each retry until it has passed them."""

    def __init__(self, fetcher: HTTPFetcher):
        self.fetcher, self.queued = fetcher, False

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


async def _headers(response) -> None:          # the first response hook: the headers are in
    record = _FETCH.get()
    if record is not None and record["tries"]:
        record["tries"][-1] = f"{response.status_code}-cut"


async def _read(response) -> None:             # the last response hook: read whole (the deadline did not cut it)
    record = _FETCH.get()
    if record is not None and record["tries"]:
        record["tries"][-1] = str(response.status_code)


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
                 proxy_blacklist_ttl: float = PROXY_BLACKLIST_TTL, **config):
        _pybookget()
        from pybookget.config import Config

        self.config = Config(**{**HTTP_DEFAULTS, **config})
        self._lock, self._waiting, self.ahead = threading.Lock(), 0, 1
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="linecaster-http", daemon=True)
        self._thread.start()

        async def client():
            return self._new_client(self.config.proxy)

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()
        self._proxies = None
        if proxy_file:
            proxies = read_proxies(proxy_file)
            self._proxies = _proxy_client(self, proxies, proxy_blacklist_threshold, proxy_blacklist_ttl)

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
        hooks["request"] = [_before, *hooks.get("request", []), _after]
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
            if self._proxies is None:
                response = await fetch(self._client, url, self.config, fallback_url=fallback_url)
            else:
                response = await self._through_proxies(url, fallback_url)
            record["status"] = response.status_code
            response.extensions[FETCH_KEY] = record
            return response
        except Exception as e:
            record["error"] = type(e).__name__
            raise
        finally:
            record["end"] = time.time_ns()
            record.pop("_t", None)
            ticket.queue(False)
            _FETCH.reset(token)
            _TICKET.reset(ticket_token)

    async def _through_proxies(self, url: str, fallback_url: str | None):
        """``url`` through the proxy list (resilient-httpx's retries and blacklist); on 404 ``fallback_url``, as
        pybookget's ``fetch`` does. A status that is not retried (404, 403, ...) raises ``httpx.HTTPStatusError``."""
        response = await self._proxies.get(url)
        if response.status_code == 404 and fallback_url:
            logger.warning("{url}: 404, trying the fallback {fallback}", url=url, fallback=fallback_url)
            response = await self._proxies.get(fallback_url)
        response.raise_for_status()
        return response

    def submit(self, url: str, fallback_url: str | None = None) -> Future:
        ticket = _Ticket(self)
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


def close_shared() -> None:
    """Close the fetchers ``HTTPFetcher.shared`` keeps (they are daemon threads, so a process may also just end)."""
    with _SHARED_LOCK:
        fetchers = list(_SHARED.values())
        _SHARED.clear()
    for fetcher in fetchers:
        fetcher.close()
