"""HTTP for linecaster's readers: pybookget's HTTP layer (``linecaster[pybookget]``: rate limits, retries that honor
``Retry-After``, the fallback URL on 404, the environment's proxy settings) on an event loop in a background thread,
for blocking callers such as datatrove blocks.

Rate limits hold per ``HTTPFetcher``, so per task: 16 tasks at 5 requests per second can send a server 80. Choose
``rate_limits`` and the number of tasks running at once (``workers``) together.

Every fetch records what it took (``fetch_record``): start and end, the host, the status, the attempts (retries and
redirects count) and the time spent waiting for the rate limits. Readers put the records on the page they fetched
(``doc.metadata["trace"]["fetch"]``), which the tracing turns into ``linecaster.http.fetch`` spans.
"""
from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from urllib.parse import urlsplit

USER_AGENT = "linecaster (+https://github.com/storytracer/linecaster)"
#: pybookget ``Config`` settings for bulk work: an honest user agent, reused connections, patient retries
HTTP_DEFAULTS = dict(use_fake_user_agent=False, user_agent=USER_AGENT, max_keepalive_connections=16,
                     max_retries=5, retry_wait_min=2.0, retry_wait_max=60.0, show_progress=False)


def _pybookget():
    try:
        import pybookget  # noqa: F401
    except ImportError as e:
        raise ImportError("manifests and http(s) images need pybookget: install linecaster[pybookget]") from e


def is_url(path: str) -> bool:
    return path.startswith(("http://", "https://"))


#: the record of the fetch running in this task of the event loop (httpx calls its hooks in the request's task)
_FETCH: contextvars.ContextVar[dict | None] = contextvars.ContextVar("linecaster_fetch", default=None)
#: where a response carries its fetch's record (``response.extensions``)
FETCH_KEY = "linecaster.fetch"


def fetch_record(response) -> dict | None:
    """What fetching ``response`` took: ``{"start", "end"}`` (ns since the epoch), ``host``, ``status``, ``attempts``,
    ``wait_seconds`` (rate limits); None for a response that was not fetched here."""
    return getattr(response, "extensions", {}).get(FETCH_KEY) if response is not None else None


async def _before(request) -> None:
    record = _FETCH.get()
    if record is not None:
        record["attempts"] += 1
        record["_t"] = time.perf_counter()


async def _after(request) -> None:              # after the rate limits' hook: the time they made it wait
    record = _FETCH.get()
    if record is not None and "_t" in record:
        record["wait_seconds"] = round(record["wait_seconds"] + time.perf_counter() - record.pop("_t"), 4)


class HTTPFetcher:
    """GETs with pybookget's ``fetch`` from blocking code: ``submit`` returns a ``concurrent.futures.Future``
    of the read ``httpx.Response``, ``get`` waits for it. ``config`` overrides ``HTTP_DEFAULTS`` (any field of
    pybookget's ``Config``, e.g. ``rate_limits=[(5, 1), (200, 60)]``, ``iiif_format="png"``)."""

    def __init__(self, **config):
        _pybookget()
        from pybookget.config import Config
        from pybookget.http import create_client

        self.config = Config(**{**HTTP_DEFAULTS, **config})
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="linecaster-http", daemon=True)
        self._thread.start()

        async def client():
            c = create_client(self.config)
            hooks = dict(c.event_hooks)
            hooks["request"] = [_before, *hooks.get("request", []), _after]
            c.event_hooks = hooks
            return c

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()

    async def _fetch(self, url: str, fallback_url: str | None):
        from pybookget.http import fetch

        record = {"start": time.time_ns(), "host": urlsplit(url).hostname or "", "attempts": 0, "wait_seconds": 0.0}
        token = _FETCH.set(record)
        try:
            response = await fetch(self._client, url, self.config, fallback_url=fallback_url)
            record["status"] = response.status_code
            response.extensions[FETCH_KEY] = record
            return response
        except Exception as e:
            record["error"] = type(e).__name__
            raise
        finally:
            record["end"] = time.time_ns()
            record.pop("_t", None)
            _FETCH.reset(token)

    def submit(self, url: str, fallback_url: str | None = None):
        return asyncio.run_coroutine_threadsafe(self._fetch(url, fallback_url), self._loop)

    def get(self, url: str, fallback_url: str | None = None):
        return self.submit(url, fallback_url).result()

    def close(self) -> None:
        if self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()
