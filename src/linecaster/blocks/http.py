"""HTTP for linecaster's readers: pybookget's HTTP layer (``linecaster[pybookget]``: rate limits, retries that honour
``Retry-After``, the fallback URL on 404, the environment's proxy settings) on an event loop in a background thread,
for blocking callers such as datatrove blocks.

Rate limits hold per ``HTTPFetcher``, so per task: 16 tasks at 5 requests per second can send a server 80. Choose
``rate_limits`` and the number of tasks running at once (``workers``) together.
"""
from __future__ import annotations

import asyncio
import threading

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
            return create_client(self.config)

        self._client = asyncio.run_coroutine_threadsafe(client(), self._loop).result()

    def submit(self, url: str, fallback_url: str | None = None):
        from pybookget.http import fetch

        return asyncio.run_coroutine_threadsafe(fetch(self._client, url, self.config, fallback_url=fallback_url),
                                                self._loop)

    def get(self, url: str, fallback_url: str | None = None):
        return self.submit(url, fallback_url).result()

    def close(self) -> None:
        if self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()
