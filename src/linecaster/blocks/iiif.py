"""IIIF: page images from IIIF manifests, fetched over HTTP with pybookget (``linecaster[pybookget]``).

* ``IIIFManifestReader``: one page per canvas of each manifest. A manifest is a reader entry the way a file is
  one for datatrove's readers (manifest files under a folder, or a ``paths_file`` listing manifest files or
  URLs), distributed over tasks in turn; an item's pages therefore stay in one task.
* ``HTTPFetcher``: pybookget's HTTP layer (rate limits, retries that honour ``Retry-After``, the fallback URL
  on 404) on an event loop in a background thread, for blocking callers such as datatrove blocks.

Rate limits hold per task (one ``HTTPFetcher`` each): 16 tasks at 5 requests per second can send a server 80.
Choose ``rate_limits`` and the number of tasks running at once (``workers``) together.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections import deque

from datatrove.io import DataFileLike, DataFolderLike, get_shard_from_paths_file
from datatrove.pipeline.readers.base import BaseDiskReader

from .base import new_page_document

logger = logging.getLogger(__name__)

USER_AGENT = "linecaster (+https://github.com/storytracer/linecaster)"
#: pybookget ``Config`` settings for bulk work: an honest user agent, reused connections, patient retries
HTTP_DEFAULTS = dict(use_fake_user_agent=False, user_agent=USER_AGENT, max_keepalive_connections=16,
                     max_retries=5, retry_wait_min=2.0, retry_wait_max=60.0, show_progress=False)
#: characters an item id keeps (it names a folder); others become "_"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MANIFEST_NAMES = {"manifest", "manifest.json", "iiif-manifest", "iiif-manifest.json"}


def _pybookget():
    try:
        import pybookget  # noqa: F401
    except ImportError as e:
        raise ImportError("IIIF and http(s) images need pybookget: install linecaster[pybookget]") from e


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


def manifest_item_id(entry: str, pattern: str | None = None) -> str:
    """The item id of a manifest entry (a URL or a file path): the first group of ``pattern`` when given,
    else the last path segment that is not a generic manifest name, without ``.json``
    (``https://www.loc.gov/item/ltf90007547/manifest.json`` → ``ltf90007547``). Characters other than
    letters, digits, ``.``, ``_`` and ``-`` become ``_`` (the id names the item's folder)."""
    if pattern:
        m = re.search(pattern, entry)
        if not m:
            raise ValueError(f"item_id_pattern {pattern!r} does not match {entry!r}")
        raw = m.group(1)
    else:
        path = entry.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if is_url(path):
            path = path.split("://", 1)[1].split("/", 1)[-1]
        segments = [s for s in path.split("/") if s and s.lower() not in _MANIFEST_NAMES]
        if not segments:
            raise ValueError(f"no item id in manifest entry {entry!r}; give item_id_pattern")
        raw = segments[-1]
        raw = raw[:-5] if raw.lower().endswith(".json") else raw
    return _UNSAFE.sub("_", raw).strip("_") or "_"


class IIIFManifestReader(BaseDiskReader):
    """One page per canvas with an image, from IIIF Presentation manifests (v2 and v3, parsed by pybookget).

    Entries are manifests, read the way datatrove reads files: the manifest files under ``data_folder``
    matching ``glob_pattern``, or the entries of ``paths_file`` (one per line: a path relative to
    ``data_folder``, or an absolute manifest URL), distributed over tasks in turn (``[rank::world_size]``).
    Every page of an item is read by the task that reads its manifest.

    Pages: ``item_id`` from the entry (``manifest_item_id``; ``item_id_pattern`` overrides the rule),
    ``sequence`` the canvas's 1-based position among the canvases with an image, ``page_id``
    ``<item_id>_<sequence:04d>``, ``image.uri`` the URL the image came from. ``metadata["iiif"]`` keeps the
    manifest, its label, rights and required statement, the canvas and its label, and the Image API request.
    Images are requested at full size through the image service (pybookget's ``canvas_images``: ``max`` for
    Image API 3, ``full`` for 2; ``iiif_format``/``iiif_quality`` in ``http``), falling back to the image's own
    URL on 404. ``prefetch`` images are requested ahead, across manifests, while the pipeline works.

    ``limit`` and ``skip`` count canvases per task (as datatrove's count documents) and apply before
    downloading. A manifest that cannot be read or parsed, an image that fails after pybookget's retries, or a
    response that is not an image is logged and counted (``manifests_failed``, ``pages_failed``,
    ``pages_not_images``), and the task goes on. ``http`` sets pybookget ``Config``
    fields over ``HTTP_DEFAULTS`` (``rate_limits`` per task, ``timeout``, ``proxy``, ``header_file``, ...)."""

    name = "🏛️ iiif manifests"

    def __init__(self, data_folder: DataFolderLike = ".", paths_file: DataFileLike | None = None,
                 glob_pattern: str = "**/*.json", recursive: bool = True, limit: int = -1, skip: int = 0,
                 item_id_pattern: str | None = None, prefetch: int = 8, http: dict | None = None,
                 file_progress: bool = False, doc_progress: bool = False, default_metadata: dict | None = None,
                 shuffle_files: bool = False):
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        _pybookget()
        if prefetch < 1:
            raise ValueError("prefetch must be at least 1")
        self.item_id_pattern, self.prefetch, self.http = item_id_pattern, prefetch, dict(http or {})

    def _entries(self, rank: int, world_size: int) -> list[str]:
        if self.paths_file:
            return [e for e in get_shard_from_paths_file(self.paths_file, rank, world_size) if e]
        entries = sorted(self.data_folder.glob(self.glob_pattern))
        if not entries:
            raise RuntimeError(f"No manifests found on {self.data_folder.path} matching {self.glob_pattern!r}")
        return entries[rank::world_size]

    def _manifest(self, fetcher: HTTPFetcher, entry: str) -> tuple[dict, str]:
        if is_url(entry):
            response = fetcher.get(entry)
            return response.json(), str(response.url)
        with self.data_folder.open(entry, "rt") as f:
            return json.load(f), self.data_folder.resolve_paths(entry)

    def _canvases(self, fetcher: HTTPFetcher, entries: list[str]):
        """(item_id, item metadata, CanvasImage) for each page of the entries, in order."""
        from pybookget.formats.iiif import canvas_images, parse_iiif_manifest
        from pybookget.models.iiif import label_text

        for entry in entries:
            self.stat_update("input_files")
            try:
                item_id = manifest_item_id(entry, self.item_id_pattern)
                data, uri = self._manifest(fetcher, entry)
                manifest = parse_iiif_manifest(data)
                images = canvas_images(manifest, fetcher.config)
            except Exception as e:  # noqa: BLE001 - a broken manifest must not stop the task
                logger.warning(f"manifest {entry}: {type(e).__name__}: {e}")
                self.stat_update("manifests_failed")
                continue
            if not images:
                self.stat_update("manifests_without_images")
                continue
            item = {"manifest": uri, "label": label_text(manifest.label), "rights": manifest.rights,
                    "required_statement": manifest.required_statement}
            self.stat_update("canvases", value=len(images), unit="input_file")
            for image in images:
                yield item_id, item, image

    def _page(self, item_id: str, item: dict, image, future):
        try:
            response = future.result()
        except Exception as e:  # noqa: BLE001 - logged and counted; the task goes on
            logger.warning(f"page {item_id} {image.index}: {image.url}: {type(e).__name__}: {e}")
            self.stat_update("pages_failed")
            return None
        iiif = {**item, "canvas": image.canvas.id, "canvas_label": image.canvas.label or None,
                "request": image.url}
        metadata = {**(self.default_metadata or {}), "iiif": iiif}
        try:
            doc = new_page_document(f"{item_id}_{image.index:04d}", response.content, uri=str(response.url),
                                    item_id=item_id, sequence=image.index, metadata=metadata)
        except Exception as e:  # noqa: BLE001 - e.g. an HTML error page sent with status 200
            logger.warning(f"page {item_id} {image.index}: {response.url}: not an image: {type(e).__name__}: {e}")
            self.stat_update("pages_not_images")
            return None
        self.stat_update("pages")
        self.update_media_stats(doc.media[0])
        return doc

    def _fetched(self, fetcher: HTTPFetcher, canvases):
        """The pages of ``canvases`` in order, ``prefetch`` images requested ahead."""
        window: deque = deque()
        try:
            for item_id, item, image in canvases:
                window.append((item_id, item, image, fetcher.submit(image.url, image.fallback_url)))
                if len(window) >= self.prefetch:
                    doc = self._page(*window.popleft())
                    if doc is not None:
                        yield doc
            while window:
                doc = self._page(*window.popleft())
                if doc is not None:
                    yield doc
        finally:
            for *_, future in window:
                future.cancel()

    def read_file(self, filepath: str):
        """The pages of one manifest (``run`` reads a task's manifests in one stream instead)."""
        own = HTTPFetcher(**self.http)
        try:
            yield from self._fetched(own, self._canvases(own, [filepath]))
        finally:
            own.close()

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        if data:
            yield from data
        entries = self._entries(rank, world_size)
        self._log_limit_scope(rank, world_size)
        if self.shuffle_files:
            import random

            random.shuffle(entries)
        fetcher = HTTPFetcher(**self.http)

        def selected():                    # skip and limit before anything is downloaded
            for i, canvas in enumerate(self._canvases(fetcher, entries)):
                if i < self.skip:
                    continue
                if self.limit != -1 and i - self.skip >= self.limit:
                    return
                yield canvas

        try:
            for doc in self._fetched(fetcher, selected()):
                self.update_doc_stats(doc)
                yield doc
        finally:
            fetcher.close()
