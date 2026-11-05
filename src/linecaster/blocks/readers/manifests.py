"""Manifests: page images (and a library's own OCR) from items' manifests, fetched with pybookget
(``linecaster[pybookget]``).

A manifest lists an item's pages and their files, in order: an IIIF Presentation manifest (2 or 3) or a METS
document with MODS (also inside an OAI-PMH response), read by pybookget's ``read_manifest`` and told apart by their
content. ``ManifestReader`` turns each into one page per image. Its entries are manifests the way a file is an entry
for datatrove's readers (manifest files under a folder, a ``paths_file`` of manifest URLs or paths), or Parquet item
tables with one manifest link per row (``manifest_key``); entries are distributed over tasks in turn, so an item's
pages stay in one task.
"""
from __future__ import annotations

import logging
import posixpath
import re
from collections import deque

from datatrove.io import DataFileLike, DataFolderLike, get_datafolder, get_shard_from_paths_file
from datatrove.pipeline.readers.base import BaseDiskReader

from ...errors import PipelineConfigError
from ...net.http import HTTPFetcher, _pybookget, is_url
from ..base.contract import Contract, Contracted, Part
from ..base.page import new_page_document

logger = logging.getLogger(__name__)

#: characters an item id keeps (it names a folder); others become "_"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MANIFEST_NAMES = {"manifest", "manifest.json", "manifest.xml", "mets", "mets.xml", "iiif-manifest",
                   "iiif-manifest.json"}
#: the transcription a library's own OCR becomes (``Page.transcriptions``)
OCR_ORIGINAL = "ocr_original"
#: file extension of a saved manifest / OCR file by format
MANIFEST_EXTENSIONS = {"iiif": "json", "mets": "xml"}
OCR_EXTENSIONS = {"alto": "xml", "hocr": "html"}


def manifest_item_id(entry: str, pattern: str | None = None) -> str:
    """The item id of a manifest entry (a URL or a file path): the first group of ``pattern`` when given,
    else the last path segment that is not a generic manifest name, without ``.json``/``.xml``
    (``https://www.loc.gov/item/ltf90007547/manifest.json`` → ``ltf90007547``). Characters other than
    letters, digits, ``.``, ``_`` and ``-`` become ``_`` (the id names the item's folder)."""
    if pattern:
        m = re.search(pattern, entry)
        if not m:
            raise PipelineConfigError(f"item_id_pattern {pattern!r} does not match {entry!r}")
        raw = m.group(1)
    else:
        path = entry.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if is_url(path):
            path = path.split("://", 1)[1].split("/", 1)[-1]
        segments = [s for s in path.split("/") if s and s.lower() not in _MANIFEST_NAMES]
        if not segments:
            raise PipelineConfigError(f"no item id in manifest entry {entry!r}; give item_id_pattern")
        raw = segments[-1]
        for ext in (".json", ".xml"):
            raw = raw[: -len(ext)] if raw.lower().endswith(ext) else raw
    return safe_id(raw)


def safe_id(raw: str) -> str:
    return _UNSAFE.sub("_", str(raw)).strip("_") or "_"


def resolve(href: str, base: str) -> str:
    """``href`` as given when absolute (a URL, an fsspec URI, ``/...``), else relative to the manifest's location
    ``base`` (METS keeps file locations as written; packages often use paths next to the METS file)."""
    if is_url(href) or "://" in href or href.startswith("/"):
        return href
    if is_url(base):
        from urllib.parse import urljoin

        return urljoin(base, href)
    folder = base.rsplit("/", 1)[0] if "/" in base else "."
    return posixpath.normpath(f"{folder}/{href}") if "://" not in folder else f"{folder}/{href}"


class _Local:
    """What ``_page`` needs of a response, for a file read from a folder."""

    def __init__(self, content: bytes, url: str):
        self.content, self.url = content, url


class ManifestReader(Contracted, BaseDiskReader):
    """One page per image of each item's manifest (IIIF Presentation 2/3, or METS with MODS, also inside an
    OAI-PMH response; ``manifest_format`` forces one, else pybookget tells them apart by content).

    Entries, distributed over tasks in turn (``[rank::world_size]``) the way datatrove distributes files:

    * without ``manifest_key``: manifests: the files under ``data_folder`` matching ``glob_pattern``, or the
      lines of ``paths_file`` (a manifest URL, or a path relative to ``data_folder``);
    * with ``manifest_key``: Parquet item tables (``glob_pattern`` default ``**/*.parquet``, or a ``paths_file``
      listing them), one item per row: its manifest link in ``manifest_key`` (a URL, an absolute fsspec path, or a
      path relative to ``data_folder``), its id in ``item_key`` (optional), and, with ``read_metadata`` (the
      default), every other column in the metadata of each of its pages.

    Pages: ``item_id`` from ``item_key``, else from the manifest entry (``manifest_item_id``;
    ``item_id_pattern`` overrides the rule); ``sequence`` the page's 1-based position among the manifest's pages
    with an image; ``page_id`` ``<item_id>_<sequence:04d>``; ``image.uri`` the URL the image came from.
    ``metadata["manifest"]`` keeps the format, the manifest's URL, id, label, rights, required statement,
    identifiers and descriptive metadata, the page's own id and label, and the image request. Images are
    requested at full size (IIIF through the image service, ``iiif_format``/``iiif_quality`` in ``http``; METS
    from the first image file group in ``mets_image_groups``), with the fallback URL on 404. ``prefetch`` pages are
    requested ahead, across manifests, while the pipeline works.

    With ``existing_ocr``, a page's own OCR (ALTO or hOCR the manifest links: METS ``FULLTEXT``, IIIF ``seeAlso``
    / ``rendering``) is fetched too, read with linecaster's ``from_alto`` / ``from_hocr`` at the image's size and
    stored as the transcription ``ocr_original`` (source ``converted``); its bytes travel as a second media of the
    document (``ImageFilesWriter(ocr_folder=...)`` writes them). With ``manifest_folder``, every manifest read is
    saved there as fetched, ``<item_id>.json`` / ``.xml``.

    ``limit`` and ``skip`` count pages per task (as datatrove's count documents) and apply before downloading.
    A manifest that cannot be read or parsed, an image or OCR file that fails after pybookget's retries, or a
    response that is not an image is logged and counted (``manifests_failed``, ``pages_failed``,
    ``pages_not_images``, ``ocr_failed``), and the task goes on. ``http`` sets pybookget ``Config`` fields over
    ``linecaster.net.http.HTTP_DEFAULTS`` (``rate_limits`` per task, ``timeout``, ``proxy``, ...)."""

    name = "📜 manifests"
    role = "reader"
    whole_items = True          # a manifest is one entry, so an item's pages stay in one task

    def contract(self) -> Contract:
        """The page image and record, and with ``existing_ocr`` whatever the library's OCR holds."""
        adds = {Part("image"), Part("metadata")} | ({Part("*", OCR_ORIGINAL)} if self.existing_ocr else set())
        return Contract(unit="page", role=self.role, adds=frozenset(adds))

    def __init__(self, data_folder: DataFolderLike = ".", paths_file: DataFileLike | None = None,
                 glob_pattern: str | None = None, recursive: bool = True, limit: int = -1, skip: int = 0,
                 manifest_key: str | None = None, item_key: str | None = None, read_metadata: bool = True,
                 manifest_format: str | None = None, item_id_pattern: str | None = None,
                 existing_ocr: bool = False, manifest_folder: DataFolderLike | None = None, prefetch: int = 8,
                 http: dict | None = None, file_progress: bool = False, doc_progress: bool = False,
                 default_metadata: dict | None = None, shuffle_files: bool = False):
        if glob_pattern is None:
            glob_pattern = "**/*.parquet" if manifest_key else "**/*.{json,xml}"
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        _pybookget()
        if prefetch < 1:
            raise PipelineConfigError("prefetch must be at least 1")
        if manifest_format not in (None, "iiif", "mets"):
            raise PipelineConfigError(f"manifest_format is iiif or mets, not {manifest_format!r}")
        if item_key and not manifest_key:
            raise PipelineConfigError("item_key names a column of an item table: give manifest_key too")
        self.manifest_key, self.item_key, self.read_metadata = manifest_key, item_key, read_metadata
        self.manifest_format, self.item_id_pattern, self.existing_ocr = manifest_format, item_id_pattern, existing_ocr
        self.manifest_folder, self.prefetch, self.http = manifest_folder, prefetch, dict(http or {})

    # ------------------------------------------------------------------ entries and items

    def _glob(self) -> list[str]:
        pattern = self.glob_pattern
        if "{" in pattern:
            head, _, rest = pattern.partition("{")
            alts, _, tail = rest.partition("}")
            return sorted({p for alt in alts.split(",") for p in self.data_folder.glob(f"{head}{alt}{tail}")})
        return sorted(self.data_folder.glob(pattern))

    def _entries(self, rank: int, world_size: int) -> list[str]:
        if self.paths_file:
            return [e for e in get_shard_from_paths_file(self.paths_file, rank, world_size) if e]
        entries = self._glob()
        if not entries:
            what = "item tables" if self.manifest_key else "manifests"
            raise PipelineConfigError(f"No {what} found on {self.data_folder.path} matching {self.glob_pattern!r}")
        return entries[rank::world_size]

    def _items(self, entries: list[str]):
        """(item_id or None, manifest reference, table metadata) per item of the entries."""
        for entry in entries:
            self.stat_update("input_files")
            if not self.manifest_key:
                yield None, entry, {}
                continue
            import pyarrow.parquet as pq

            with self.data_folder.open(entry, "rb") as f, pq.ParquetFile(f) as pqf:
                keys = None if self.read_metadata else [k for k in (self.manifest_key, self.item_key) if k]
                for batch in pqf.iter_batches(columns=keys):
                    for row in batch.to_pylist():
                        ref = row.pop(self.manifest_key, None)
                        item = row.pop(self.item_key, None) if self.item_key else None
                        if not ref:
                            self.stat_update("items_without_manifest")
                            continue
                        extra = {k: v for k, v in row.items() if not isinstance(v, bytes | dict | list)}
                        yield None if item is None else safe_id(item), str(ref), extra

    def _read(self, fetcher: HTTPFetcher, ref: str) -> tuple[bytes, str]:
        if is_url(ref):
            response = fetcher.get(ref)
            return response.content, str(response.url)
        if "://" in ref or ref.startswith("/"):
            folder, name = ref.rsplit("/", 1)
            df = get_datafolder(folder)
            with df.open(name, "rb") as f:
                return f.read(), df.resolve_paths(name)
        with self.data_folder.open(ref, "rb") as f:
            return f.read(), self.data_folder.resolve_paths(ref)

    def _pages(self, fetcher: HTTPFetcher, entries: list[str]):
        """(item_id, item metadata, table metadata, ManifestPage) for each page of the entries' items, in order."""
        from pybookget.formats.manifest import read_manifest

        saved = get_datafolder(self.manifest_folder) if self.manifest_folder is not None else None
        for item_id, ref, extra in self._items(entries):
            try:
                item_id = item_id or manifest_item_id(ref, self.item_id_pattern)
                data, uri = self._read(fetcher, ref)
                manifest = read_manifest(data, fetcher.config, format=self.manifest_format)
            except Exception as e:  # noqa: BLE001 - a broken manifest must not stop the task
                logger.warning(f"manifest {ref}: {type(e).__name__}: {e}")
                self.stat_update("manifests_failed")
                continue
            self.stat_update(f"manifests_{manifest.format}")
            if saved is not None:
                with saved.open(f"{item_id}.{MANIFEST_EXTENSIONS.get(manifest.format, 'bin')}", "wb") as f:
                    f.write(data)
            if not manifest.pages:
                self.stat_update("manifests_without_images")
                continue
            item = {"format": manifest.format, "url": uri, "id": manifest.id, "label": manifest.label,
                    "rights": manifest.rights, "required_statement": manifest.required_statement,
                    "identifiers": dict(manifest.identifiers), "metadata": dict(manifest.metadata)}
            self.stat_update("manifest_pages", value=len(manifest.pages), unit="input_file")
            for page in manifest.pages:
                yield item_id, item, extra, page

    # ------------------------------------------------------------------ pages

    def _submit(self, fetcher: HTTPFetcher, entry):
        item_id, item, extra, page = entry
        base = item["url"]
        image = self._get(fetcher, resolve(page.url, base), page.fallback_url and resolve(page.fallback_url, base))
        ocr = self._get(fetcher, resolve(page.ocr_url, base)) if self.existing_ocr and page.ocr_url else None
        return entry, image, ocr

    @staticmethod
    def _get(fetcher: HTTPFetcher, url: str, fallback_url: str | None = None):
        """A future of the response: over http(s) with pybookget, else read at once from its folder (a METS
        package with local files)."""
        if is_url(url):
            return fetcher.submit(url, fallback_url)
        from concurrent.futures import Future

        future: Future = Future()
        try:
            folder, name = url.rsplit("/", 1) if "/" in url else (".", url)
            with get_datafolder(folder).open(name, "rb") as f:
                future.set_result(_Local(f.read(), url))
        except Exception as e:  # noqa: BLE001 - reported when the page is taken from the window
            future.set_exception(e)
        return future

    def _page(self, entry, image, ocr):
        from datatrove.data import Media, MediaType

        from ..base.page import page_of, set_page

        item_id, item, extra, page = entry
        try:
            response = image.result()
        except Exception as e:  # noqa: BLE001 - logged and counted; the task goes on
            logger.warning(f"page {item_id} {page.index}: {page.url}: {type(e).__name__}: {e}")
            self.stat_update("pages_failed")
            if ocr is not None:
                ocr.cancel()
            return None
        manifest = {**item, "page_id": page.id, "page_label": page.label, "request": page.url}
        metadata = {**(self.default_metadata or {}), **extra, "manifest": manifest}
        page_id = f"{item_id}_{page.index:04d}"
        try:
            doc = new_page_document(page_id, response.content, uri=str(response.url), item_id=item_id,
                                    sequence=page.index, metadata=metadata)
        except Exception as e:  # noqa: BLE001 - e.g. an HTML error page sent with status 200
            logger.warning(f"page {item_id} {page.index}: {response.url}: not an image: {type(e).__name__}: {e}")
            self.stat_update("pages_not_images")
            if ocr is not None:
                ocr.cancel()
            return None
        if ocr is not None:
            try:
                raw = ocr.result()
                p = page_of(doc)
                p.transcriptions[OCR_ORIGINAL] = self._transcription(raw.content, str(raw.url), page.ocr_format, p)
                set_page(doc, p)
                doc.media.append(Media(id=f"{page_id}.{page.ocr_format}", type=MediaType.DOCUMENT,
                                       url=str(raw.url), media_bytes=raw.content))
                self.stat_update("ocr")
            except Exception as e:  # noqa: BLE001 - the page goes on without it
                logger.warning(f"ocr {item_id} {page.index}: {page.ocr_url}: {type(e).__name__}: {e}")
                self.stat_update("ocr_failed")
        self.stat_update("pages")
        self.update_media_stats(doc.media[0])
        return doc

    @staticmethod
    def _transcription(data: bytes, uri: str, fmt: str | None, page):
        from ...formats import from_alto, from_hocr

        if fmt == "hocr":
            t = from_hocr(data, uri=uri)
        else:
            t = from_alto(data, image_width=page.image.width, image_height=page.image.height, uri=uri)
        t.source.image_sha256 = page.image.sha256
        t.source.image_width, t.source.image_height = page.image.width, page.image.height
        return t

    def _fetched(self, fetcher: HTTPFetcher, pages):
        """The documents of ``pages`` in order, ``prefetch`` pages requested ahead."""
        window: deque = deque()
        try:
            for entry in pages:
                window.append(self._submit(fetcher, entry))
                if len(window) >= self.prefetch:
                    doc = self._page(*window.popleft())
                    if doc is not None:
                        yield doc
            while window:
                doc = self._page(*window.popleft())
                if doc is not None:
                    yield doc
        finally:
            for _, image, ocr in window:
                image.cancel()
                if ocr is not None:
                    ocr.cancel()

    def read_file(self, filepath: str):
        """The pages of one entry (a manifest, or an item table); ``run`` reads a task's entries in one stream."""
        own = HTTPFetcher(**self.http)
        try:
            yield from self._fetched(own, self._pages(own, [filepath]))
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
            for i, entry in enumerate(self._pages(fetcher, entries)):
                if i < self.skip:
                    continue
                if self.limit != -1 and i - self.skip >= self.limit:
                    return
                yield entry

        try:
            for doc in self._fetched(fetcher, selected()):
                self.update_doc_stats(doc)
                yield doc
        finally:
            fetcher.close()
