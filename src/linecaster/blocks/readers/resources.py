"""``ResourceReader``: remote files of items (a catalogue record, an API's item JSON, a manifest, a page's OCR), fetched
as they are served, so a later stage can link to the reference copy and parse it again whenever its mapping changes.

A resource is a remote file of an item (or of one of its pages): its ``kind`` (``marcxml``, ``item-json``, ...), its
URL and a name for its copy. They come from a Parquet table, either one row per resource (``url_key``, ``kind_key``,
optionally ``name_key``) or one row (or more) per item and URL templates per kind (``templates``:
``{"marcxml": "https://catalog.example.org/{item}/marcxml"}``). One item per task (``auto_tasks``), the items grouped by
their ``item_key`` value wherever their rows are (``tables.item_runs``), so a task that fails costs one item.

Each resource becomes one datatrove document (unit ``item``: the stream carries resources, not pages): its bytes as
a media, and its fetch record in ``doc.metadata["resource"]``: ``item``, ``kind``, ``name``, ``ext``, ``source_uri``,
``final_uri``, ``status``, ``content_type``, ``bytes``, ``sha256``, ``etag``, ``last_modified``, ``fetched`` (UTC),
``attempts``, ``reused``, and ``warnings`` for an image kept with image warnings (faults it is read around, e.g. a
PNG's damaged optional chunk, corrupt EXIF: ``linecaster.images.image_warnings``), also logged as a WARNING.
``ResourceFilesWriter`` writes the copy, unchanged, and ``ResourceRecordWriter`` the records.

A response is checked before it counts (``check``): XML must parse, JSON must parse, an image must be readable (its
image warnings do not fail it), a DjVu file
must start with its signature (DjVu is served as ``image/vnd.djvu`` but is no image an image library opens). An HTML page
where another format was expected (an error page, a CAPTCHA sent with 200) is a failed attempt of the fetch, retried
(``linecaster.net.http.UnexpectedHTML``); a resource that fails with it also counts toward the host's breaker as a server
error. Where the HTTP policy has ``html`` in ``block_on`` it is a block instead, in ``stop_on`` it stops the run. A
failed resource is the item's error (``doc.metadata["errors"]``, rejects), within the error budget, as for pages.

Requests go out per host (``http_policy``: a ``linecaster.net.policy`` file), each with its own fetcher, rate limits,
breaker and pause; a status in a host's ``block_on`` (429 by default) pauses its requests until the server's
``Retry-After`` has passed (direct; through proxies the proxy is left out there) and the resource is then fetched
again, a status in its ``stop_on`` stops the run (a ``ServerError``) without a retry. With ``reuse_folder`` a
resource whose copy is there already (one listing of ``<kind>/<item>/`` per item) is read back instead of fetched.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from datetime import datetime, timezone

from datatrove.io import DataFileLike, DataFolderLike, get_datafolder, get_shard_from_paths_file
from datatrove.pipeline.readers.base import BaseDiskReader
from loguru import logger

from ...errors import PipelineConfigError, ServerError
from ...net.http import prefetched
from ..base.contract import Contracted
from ..base.page import NOT_THE_PAGES, ErrorBudget, error_entry, record_error
from .existing import ExistingImages, Reused
from .tables import item_ranges, item_runs, rows_between, slice_batches, table_rows

#: where a resource's record is kept in its document
RESOURCE_KEY = "resource"
#: file extensions by content type (the first part, before ``;``)
EXTENSIONS = {"application/xml": "xml", "text/xml": "xml", "application/marcxml+xml": "xml",
              "application/mods+xml": "xml", "application/json": "json", "application/ld+json": "json",
              "text/html": "html", "text/plain": "txt", "application/pdf": "pdf", "image/jpeg": "jpg",
              "image/png": "png", "image/jp2": "jp2", "image/tiff": "tif", "image/webp": "webp",
              "image/vnd.djvu": "djvu", "image/x-djvu": "djvu", "image/x.djvu": "djvu"}
#: DjVu's content types: documents an image library does not open, checked by their signature instead
DJVU_TYPES = frozenset({"image/vnd.djvu", "image/x-djvu", "image/x.djvu"})
#: the first bytes of every DjVu file (an IFF container: ``AT&T`` then a ``FORM`` chunk)
DJVU_SIGNATURE = b"AT&TFORM"


def expected_format(kind: str, url: str) -> str | None:
    """The format a resource should have, from its kind or URL: ``djvu``, ``xml``, ``json``, ``image``, or None
    (any)."""
    text = f"{kind} {posixpath.splitext(url.split('?')[0])[1]}".lower()
    if "djvu" in text:
        return "djvu"
    if any(k in text for k in ("xml", "marc", "mods", "mets", "alto", "rdf")):
        return "xml"
    if any(k in text for k in ("json", "manifest")):
        return "json"
    if any(k in text for k in ("image", ".jpg", ".jpeg", ".png", ".jp2", ".tif", ".webp")):
        return "image"
    return None


def check(data: bytes, content_type: str, expected: str | None) -> str | None:
    """What is wrong with a response (``html`` first for an HTML page where another format was expected), or None."""
    return inspect(data, content_type, expected)[0]


def inspect(data: bytes, content_type: str, expected: str | None) -> tuple[str | None, list[str]]:
    """(``check``'s problem or None, an image's image warnings: ``linecaster.images.image_warnings``)."""
    from ...net.http import is_html

    ctype = (content_type or "").split(";")[0].strip().lower()
    if expected and is_html(data, content_type):     # data a server labels text/html is read as what it is
        return f"html: an HTML page ({len(data)} bytes) where {expected} was expected", []
    fmt = expected or ("xml" if ctype.endswith("xml") else "json" if ctype.endswith("json")
                       else "djvu" if ctype in DJVU_TYPES else "image" if ctype.startswith("image/") else None)
    if fmt == "djvu":
        return (None if data.startswith(DJVU_SIGNATURE) else "not djvu: no DjVu signature (AT&TFORM)"), []
    found: list[str] = []
    try:
        if fmt == "xml":
            from xml.etree import ElementTree

            ElementTree.fromstring(data)
        elif fmt == "json":
            json.loads(data)
        elif fmt == "image":
            from ...images import image_warnings

            found = image_warnings(data)
    except Exception as e:  # noqa: BLE001 - what the parser says is the problem
        return f"not {fmt}: {type(e).__name__}: {str(e)[:120]}", []
    if not data:
        return "empty response", []
    return None, found


def extension(content_type: str, url: str, expected: str | None) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in EXTENSIONS:
        return EXTENSIONS[ctype]
    ext = posixpath.splitext(url.split("?")[0])[1].lstrip(".").lower()
    if ext and len(ext) <= 5:
        return ext
    return {"xml": "xml", "json": "json"}.get(expected or "", "bin")


class ResourceReader(Contracted, BaseDiskReader):
    """Fetches the remote files of items as they are served, one document per resource, one item per task.

    The input is Parquet (``data_folder``): one row per resource (``url_key`` and ``kind_key``, optionally
    ``name_key``), or rows naming items and ``templates`` that give each item's URL per kind (``{item}`` is replaced
    by the item id). The copy's name is ``name_key``'s value, else the item id (with ``templates``) or the URL's last
    path segment. ``auto_tasks`` is the number of items. See the module docstring for the record, the checks, the
    HTTP policy and the reuse.

    Args:
        data_folder: the Parquet files (a folder, or the folder of ``glob_pattern``'s file).
        item_key: the column with each row's item id.
        templates: kind -> URL template with ``{item}``; default: the table names its resources (``url_key``).
        url_key, kind_key, name_key: the table's columns for a resource's URL, kind and copy name (without
            ``templates``; ``name_key`` optional).
        http: ``linecaster.net.http.HTTPFetcher`` settings for every host (rate limits, proxies, ...).
        http_policy: an HTTP policy file (``linecaster.net.policy``): settings for every host under ``http``'s, a
            host's own over both.
        reuse_folder: where ``ResourceFilesWriter`` writes (``OUT``): a resource whose copy is there is read back
            (one listing per item and kind, ``linecaster.blocks.readers.existing``; one that takes over
            ``LISTING_TIMEOUT``, 60 s, or fails is a warning and a stat, ``reuse_listing_timeouts`` or
            ``reuse_listing_errors``, and the item's resources are fetched again).
        max_items: only the first ``max_items`` items of the input, for the whole run (a smoke test).
        limit, skip: resources per task, as datatrove's count documents; they apply before anything is fetched.
        paths_file, glob_pattern, recursive, file_progress, doc_progress, default_metadata, shuffle_files:
            datatrove's ``BaseDiskReader`` arguments.
    """

    name = "🌐 resources"
    role = "reader"
    unit = "item"
    parts_added = ("metadata",)
    docs_args = {"data_folder": "items/", "item_key": "lccn",
                 "templates": {"marcxml": "https://catalog.example.org/{item}/marcxml"}}
    #: the share of a task's resources that may fail (None: no limit; the builder sets it)
    max_page_errors: float | None = 0.01
    #: what the console counts
    unit_label = "files"

    def __init__(self, data_folder: DataFolderLike, item_key: str, templates: dict[str, str] | None = None,
                 url_key: str = "url", kind_key: str = "kind", name_key: str | None = None, http: dict | None = None,
                 http_policy: str | None = None, reuse_folder: DataFolderLike | None = None, max_items: int | None = None,
                 paths_file: DataFileLike | None = None, glob_pattern: str = "**/*.parquet", recursive: bool = True,
                 limit: int = -1, skip: int = 0, file_progress: bool = False, doc_progress: bool = False,
                 default_metadata: dict | None = None, shuffle_files: bool = False):
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        for kind, template in (templates or {}).items():
            if "{item}" not in template:
                raise PipelineConfigError(f"the URL template of {kind!r} has no {{item}}: {template}")
        if max_items is not None and max_items < 1:
            raise PipelineConfigError("max_items must be at least 1")
        self.item_key, self.templates = item_key, dict(templates or {})
        self.url_key, self.kind_key, self.name_key = url_key, kind_key, name_key
        from ...net.policy import Fetchers

        self.http, self.http_policy = dict(http or {}), http_policy
        self.reuse_folder, self.max_items = reuse_folder, max_items
        self._layout = self._items = None
        self._fetchers = Fetchers(self.http, http_policy)      # pickled without its fetchers
        self._existing: dict[str, ExistingImages] = {}

    def __getstate__(self):                      # listings belong to the task using them
        return {**self.__dict__, "_existing": {}}

    @property
    def _last(self):
        """The fetcher of the latest request (``prefetched``'s window), or None."""
        return self._fetchers.last

    # ---------------------------------------------------------------- the input and the tasks

    def layout(self):
        if self._layout is None:
            files = (list(get_shard_from_paths_file(self.paths_file, 0, 1)) if self.paths_file
                     else self.data_folder.list_files(recursive=self.recursive, glob_pattern=self.glob_pattern))
            if not files:
                raise PipelineConfigError(f"No Parquet files found on {self.data_folder.path} matching "
                                          f"{self.glob_pattern!r}")
            self._layout = table_rows(self.data_folder, files)
        return self._layout

    def items(self) -> tuple:
        """The input's items and their rows (``tables.item_runs``), the first ``max_items`` of them; kept."""
        if self._items is None:
            starts, order, offsets = item_runs(self.data_folder, self.layout(), self.item_key)
            if self.max_items is not None and len(offsets) - 1 > self.max_items:
                offsets = offsets[:self.max_items + 1]
                order = order[:offsets[-1]]
            self._items = (starts, order, offsets)
        return self._items

    def auto_tasks(self) -> int:
        """One task per item."""
        return max(1, len(self.items()[2]) - 1)

    def task_pages(self, rank: int, world_size: int) -> int:
        """The resources task ``rank`` of ``world_size`` fetches (the console's total; "pages" in its interface)."""
        if self.templates:
            count = len(self._item_count(rank, world_size)) * len(self.templates)
        else:
            count = sum(hi - lo for lo, hi in item_ranges(self.items(), rank, world_size))
        count = max(0, count - self.skip)
        return count if self.limit == -1 else min(count, self.limit)

    def _item_count(self, rank: int, world_size: int) -> range:
        offsets = self.items()[2]
        n = len(offsets) - 1
        return range(rank * n // world_size, (rank + 1) * n // world_size)

    def _task_slices(self, rank: int, world_size: int) -> list:
        return [s for lo, hi in item_ranges(self.items(), rank, world_size)
                for s in rows_between(self.layout(), lo, hi)]

    def _entries(self, slices: list):
        """``(item, kind, name, url)`` for each resource of ``slices`` (``tables.row_slices``'), in order."""
        import pyarrow.parquet as pq

        columns = [self.item_key] if self.templates else [c for c in (self.item_key, self.kind_key, self.url_key,
                                                                       self.name_key) if c]
        seen_items: set[str] = set()
        names: dict[tuple[str, str], int] = {}
        for path in dict.fromkeys(s[0] for s in slices):
            with self.data_folder.open(path, "rb") as f, pq.ParquetFile(f) as pqf:
                missing = [c for c in columns if c not in pqf.schema_arrow.names]
                if missing:
                    raise PipelineConfigError(f"{path}: no column {', '.join(missing)} (item_key, url_key, kind_key)")
                for batch in slice_batches(pqf, [s for s in slices if s[0] == path], columns, 4096):
                    for row in batch.to_pylist():
                        item = str(row[self.item_key])
                        if self.templates:
                            if item in seen_items:
                                continue
                            seen_items.add(item)
                            for kind, template in self.templates.items():
                                yield item, kind, item, template.replace("{item}", item)
                            continue
                        url, kind = str(row[self.url_key]), str(row[self.kind_key])
                        if self.name_key and row.get(self.name_key):
                            name = str(row[self.name_key])
                        else:
                            name = posixpath.splitext(posixpath.basename(url.split("?")[0]))[0] or item
                        k = names[(kind, name)] = names.get((kind, name), 0) + 1
                        yield item, kind, (name if k == 1 else f"{name}_{k:04d}"), url

    # ---------------------------------------------------------------- fetching

    def _fetcher(self, url: str):
        return self._fetchers.for_url(url)

    def _copy(self, item: str, kind: str, name: str):
        if self.reuse_folder is None:
            return None
        if kind not in self._existing:
            self._existing[kind] = ExistingImages(posixpath.join(str(self.reuse_folder).rstrip("/"), kind))
        return self._existing[kind].get(item, name, self.stat_update)

    def _submit(self, entry):
        from concurrent.futures import Future

        item, kind, name, url = entry
        copy = self._copy(item, kind, name)
        if copy is not None:                         # its copy is there: read back, not fetched
            done: Future = Future()
            try:
                folder, file = copy[0].rsplit("/", 1)
                with get_datafolder(folder).open(file, "rb") as f:
                    done.set_result(Reused(copy, f.read()))
                return entry, done, None
            except Exception:  # noqa: BLE001 - a copy that cannot be read is fetched again
                pass
        fetcher = self._fetcher(url)
        return entry, fetcher.submit(url, expect=expected_format(kind, url)), fetcher

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        if data:
            yield from data
        self._log_limit_scope(rank, world_size)
        yield from self._fetched(self._task_slices(rank, world_size))

    def read_file(self, filepath: str):
        """The resources of one whole file (datatrove's reader interface; ``run`` reads a task's item)."""
        import pyarrow.parquet as pq

        from .tables import whole_file

        with self.data_folder.open(filepath, "rb") as f, pq.ParquetFile(f) as pqf:
            slices = whole_file(pqf, filepath)
        yield from self._fetched(slices)

    def _fetched(self, slices: list):
        budget = ErrorBudget(self, self.max_page_errors)
        self._fetchers.start_task()

        def selected():
            for i, entry in enumerate(self._entries(slices)):
                if i < self.skip:
                    continue
                if self.limit != -1 and i - self.skip >= self.limit:
                    return
                yield entry

        for entry, future, fetcher in prefetched(selected(), self._submit, lambda s: s[1].cancel(),
                                                 future=lambda s: s[1], fetcher=lambda: self._last, ordered=False):
            budget.page()
            with self.track_time():
                doc, error = self._document(entry, future, fetcher)
            if error is not None:
                self.stat_update("resource_errors")
                budget.failed(doc, record_error(doc, error_entry(self, error, field="resource", raw_value=entry[3])),
                              error)
            else:
                self.stat_update("resources", "reused" if doc.metadata[RESOURCE_KEY]["reused"] else "fetched")
                self.update_media_stats(doc.media[0])
            yield doc

    def _document(self, entry, future, fetcher):
        """The resource's document, and the error that failed it (None)."""
        from datatrove.data import Document, Media, MediaType

        from ...net.http import StopRequests, UnexpectedHTML, failed_fetch, fetch_record

        item, kind, name, url = entry
        expected = expected_format(kind, url)
        record = {"item": item, "kind": kind, "name": name, "source_uri": url, "reused": False,
                  "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        doc = Document(text="", id=f"{item}/{kind}/{name}", media=[], metadata={RESOURCE_KEY: record})
        try:
            raw = future.result()
            if isinstance(raw, Reused):
                data, ctype = raw.data, ""
                record.update(reused=True, ext=raw.copy[2], uri=raw.copy[0])
            else:
                data, ctype = raw.content, raw.headers.get("content-type", "")
                fetch = fetch_record(raw) or {}
                record.update(final_uri=str(raw.url), status=raw.status_code, etag=raw.headers.get("etag"),
                              last_modified=raw.headers.get("last-modified"), attempts=fetch.get("attempts"))
            problem, found = inspect(data, ctype or EXTENSIONS_REVERSE.get(record.get("ext", ""), ""), expected)
            if problem is not None:
                if fetcher is not None:
                    fetcher._loop.call_soon_threadsafe(fetcher.breaker.record, 520)   # counts like a server error
                raise ValueError(problem)
            record.update(content_type=ctype or None, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            record.setdefault("ext", extension(ctype, url, expected))
            is_image = (ctype or "").startswith("image/") or expected == "image"
            if found:
                record["warnings"] = found
                logger.warning("file {id}: kept, with image warnings: {warnings}", id=doc.id,
                               warnings="; ".join(found))
            doc.media.append(Media(id=doc.id, type=MediaType.IMAGE if is_image else MediaType.DOCUMENT, url=url,
                                   media_bytes=data))
            return doc, None
        except NOT_THE_PAGES:
            raise
        except StopRequests as e:
            raise ServerError(str(e)) from e
        except Exception as e:  # noqa: BLE001 - the resource's error; the task goes on within its budget
            if fetcher is not None and isinstance(e.__cause__ or e, UnexpectedHTML):
                fetcher._loop.call_soon_threadsafe(fetcher.breaker.record, 520)   # counts like a server error
            if (fetch := failed_fetch(e)) is not None:
                record["attempts"] = fetch.get("attempts")
            record["error"] = f"{type(e).__name__}: {e}"
            return doc, e


#: content types by extension, for a copy read back (its own type is not stored with it)
EXTENSIONS_REVERSE = {"xml": "application/xml", "json": "application/json", "html": "text/html",
                      "jpg": "image/jpeg", "png": "image/png", "jp2": "image/jp2", "tif": "image/tiff"}


def is_resource(doc) -> bool:
    return RESOURCE_KEY in getattr(doc, "metadata", {})


def resource_of(doc) -> dict:
    return doc.metadata[RESOURCE_KEY]
