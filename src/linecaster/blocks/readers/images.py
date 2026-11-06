"""Readers for page images, on datatrove's reader conventions (``BaseDiskReader``: ``data_folder``, ``paths_file``,
``glob_pattern``, ``recursive``, ``limit`` and ``skip`` per task, entries distributed over tasks in turn):

* ``ImageFolderReader``: image files (found by ``glob_pattern`` or listed in a ``paths_file``), one page each.
* ``ImageParquetReader``: Parquet files with an image column (the bytes, or a path to the image), e.g. an image
  dataset on the Hub (``hf://datasets/<repo>@<revision>/data``), one page per row.

Entries are distributed as datatrove distributes files, so an item's pages can land in different tasks;
item-level steps run in a later stage over item shards (``linecaster.blocks.writers.shards``). Page records of an
earlier run: ``linecaster.blocks.readers.records``.

Images are opened through datatrove's ``DataFolder``, so any fsspec path works (local, ``s3://``, ``hf://``);
fsspec's settings apply (e.g. ``FSSPEC_S3_ANON=true`` for a public bucket). Absolute ``http(s)://`` image URLs
(in a Parquet image column or a page record) are fetched with pybookget (``linecaster[pybookget]``), politely:
rate limits per task, retries that honor ``Retry-After``. Manifests (IIIF, METS): ``linecaster.blocks.readers.manifests``.
"""
from __future__ import annotations

import posixpath
from collections.abc import Callable
from concurrent.futures import Future

from datatrove.io import DataFileLike, DataFolderLike, get_datafolder, get_shard_from_paths_file
from datatrove.pipeline.readers.base import BaseDiskReader
from datatrove.pipeline.readers.parquet import ParquetReader

from ...errors import PageError, PipelineConfigError
from ...net.http import prefetched
from ..base.block import reported_file
from ..base.contract import Contracted
from ...data.page import Page, PageImage
from ..base.page import NOT_THE_PAGES, ErrorBudget, error_entry, new_page_document, record_error, set_page

IMAGE_EXTENSIONS = ("webp", "jpg", "jpeg", "png", "tif", "tiff", "jp2")
IMAGE_GLOB = "**/*.{" + ",".join(IMAGE_EXTENSIONS) + "}"


def _stem(path: str) -> str:
    return posixpath.basename(path).rsplit(".", 1)[0]


class _Opener:
    """Opens absolute URIs through datatrove ``DataFolder``s, one per folder (``hf://``, ``s3://``, local), and
    ``http(s)://`` URLs through pybookget (``linecaster[pybookget]``: rate limits, retries that honor
    ``Retry-After``; ``http`` sets its ``Config`` fields, ``linecaster.net.http.HTTPFetcher``)."""

    def __init__(self, http: dict | None = None):
        self._folders: dict = {}
        self.http, self._fetcher = dict(http or {}), None

    def __getstate__(self):                      # pipelines are pickled for their executors; the fetcher's
        return {**self.__dict__, "_fetcher": None}   # thread and event loop are made again where it runs

    def read(self, uri: str, fetches: list | None = None) -> bytes:
        """The bytes at ``uri``; an http(s) fetch's record (``linecaster.net.http.fetch_record``) is appended to
        ``fetches``."""
        return self.result(self.submit(uri), fetches)

    def submit(self, uri: str) -> Future:
        """A future of what ``uri`` holds, for ``result``: an http(s) request starts at once (``HTTPFetcher.submit``,
        within its rate limits), anything else is read now."""
        if uri.startswith(("http://", "https://")):
            from ...net.http import HTTPFetcher

            if self._fetcher is None:
                self._fetcher = HTTPFetcher(**self.http)
            return self._fetcher.submit(uri)
        return _future(lambda: self._read_local(uri))

    @staticmethod
    def result(future: Future, fetches: list | None = None) -> bytes:
        """The bytes of a ``submit`` future (waiting for it); an http(s) fetch's record is appended to ``fetches``."""
        value = future.result()
        if isinstance(value, bytes):
            return value
        from ...net.http import fetch_record

        if fetches is not None and (record := fetch_record(value)) is not None:
            fetches.append({**record, "what": "image"})
        return value.content

    def _read_local(self, uri: str) -> bytes:
        folder, name = uri.rsplit("/", 1) if "/" in uri else (".", uri)
        df = self._folders.get(folder)
        if df is None:
            df = self._folders[folder] = get_datafolder(folder)
        with df.open(name, "rb") as f:
            return f.read()


def _future(read: Callable[[], bytes]) -> Future:
    """A finished future of ``read()``, or of the exception it raised (reported when the page is taken)."""
    future: Future = Future()
    try:
        future.set_result(read())
    except Exception as e:  # noqa: BLE001 - raised by Future.result() for that page, in order
        future.set_exception(e)
    return future


class ImageFolderReader(Contracted, BaseDiskReader):
    """Reads one page per image file of a folder or bucket.

    The image files under ``data_folder`` matching ``glob_pattern``, or the files listed in ``paths_file`` (one per
    line, relative to ``data_folder``), are distributed over tasks in turn (``[rank::world_size]``, as
    ``DataFolder.get_shard``). Each page adds ``image`` (the file's bytes) and ``metadata`` (the page record:
    ``page_id`` is the file name without extension, the image's URI). ``limit`` and ``skip`` count pages per task,
    as in datatrove. An item's pages can land in different tasks: item-level steps run in a later stage over item
    shards (``linecaster.blocks.writers.shards``). No matching file fails the task with a ``PipelineConfigError``.

    Args:
        data_folder: the folder (local path, fsspec URI or ``DataFolder``) the images are read from.
        paths_file: a file listing the images to read, one path per line relative to ``data_folder``; default: every
            file matching ``glob_pattern``.
        glob_pattern: the image files to read; ``{a,b}`` alternatives are expanded. Default: WebP, JPEG, PNG, TIFF and
            JPEG 2000 files at any depth.
        item_from_parent: the parent folder's name is each page's ``item_id``; excludes ``item_id``.
        item_id: every page belongs to this one item; excludes ``item_from_parent``. Default: pages without item.
        sequence: sets ``Page.sequence`` to the file's 1-based position among its item's files in sorted order;
            needs ``glob_pattern`` (every file of an item), not ``paths_file``.
        default_metadata: goes into every page's metadata.
        recursive, limit, skip, file_progress, doc_progress, shuffle_files: datatrove's ``BaseDiskReader`` arguments.
    """

    name = "🖼️ image folder"
    role = "reader"
    parts_added = ("image", "metadata")
    docs_args = {"data_folder": "scans/"}

    def __init__(self, data_folder: DataFolderLike, paths_file: DataFileLike | None = None,
                 glob_pattern: str = IMAGE_GLOB, recursive: bool = True, limit: int = -1, skip: int = 0,
                 item_from_parent: bool = False, item_id: str | None = None, sequence: bool = False,
                 file_progress: bool = False, doc_progress: bool = False, default_metadata: dict | None = None,
                 shuffle_files: bool = False):
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        if item_id is not None and item_from_parent:
            raise PipelineConfigError("item_id and item_from_parent exclude each other")
        if sequence and paths_file:
            raise PipelineConfigError("sequence needs every file of an item, so it works with glob_pattern, not paths_file")
        self.item_from_parent, self.item_id, self.sequence = item_from_parent, item_id, sequence
        self._positions: dict[str, int] = {}

    def _item(self, path: str) -> str | None:
        if self.item_id is not None:
            return self.item_id
        return path.rsplit("/", 2)[-2] if self.item_from_parent and "/" in path else None

    def _glob(self) -> list[str]:
        """The matching files, sorted (``{a,b}`` alternatives expanded, which fsspec's glob does not do)."""
        pattern = self.glob_pattern
        if "{" in pattern:
            head, _, rest = pattern.partition("{")
            exts, _, tail = rest.partition("}")
            return sorted({p for ext in exts.split(",") for p in self.data_folder.glob(f"{head}{ext}{tail}")})
        return sorted(self.data_folder.glob(pattern))

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        if data:
            yield from data
        if self.paths_file:
            files = list(get_shard_from_paths_file(self.paths_file, rank, world_size))
        else:
            all_files = self._glob()
            if not all_files:
                raise PipelineConfigError(f"No images found on {self.data_folder.path} matching {self.glob_pattern!r}")
            if self.sequence:
                counts: dict[str | None, int] = {}
                for path in all_files:
                    item = self._item(path)
                    counts[item] = counts.get(item, 0) + 1
                    self._positions[path] = counts[item]
            files = all_files[rank::world_size]
        self._log_limit_scope(rank, world_size)
        if self.shuffle_files:
            import random

            random.shuffle(files)
        for doc in self.read_files_shard(files):
            self.update_doc_stats(doc)
            yield doc

    def read_file(self, filepath: str):
        with self.track_time():
            with self.data_folder.open(filepath, "rb") as f:
                raw = f.read()
            doc = new_page_document(_stem(filepath), raw, uri=self.data_folder.resolve_paths(filepath),
                                    item_id=self._item(filepath), sequence=self._positions.get(filepath),
                                    metadata=dict(self.default_metadata or {}))
        self.stat_update("pages")
        self.update_media_stats(doc.media[0])
        yield doc


class ImageParquetReader(Contracted, ParquetReader):
    """Reads one page per row of Parquet files with an image column.

    The files are read through datatrove's ``ParquetReader`` and distributed over tasks in turn, so a file should
    hold whole items. Each row adds ``image`` and ``metadata`` (the page record). The image column holds the image
    as Hugging Face's ``Image`` feature stores it (``{"bytes", "path"}``: the bytes when present, else the path), as
    plain bytes, or as a path: absolute (any fsspec URI, ``http(s)://`` through pybookget) or relative to
    ``image_folder``. A row with neither bytes nor a path fails the task (a ``PageError``: the table is wrong).

    An image that cannot be read (an http(s) error after pybookget's retries, a missing file, bytes that are not an
    image) makes a page without image whose ``doc.metadata["errors"]`` says why (``field`` ``image``, ``raw_value``
    the image's URI), so the task goes on: later model blocks pass the page by, ``ImageFilesWriter`` writes no file
    for it, and the page records and rejects keep it. More such pages than ``max_page_errors`` (a share of the task's
    pages, judged from page 100 on, ``ErrorBudget``) fail the task, so a server that is down does not mark every
    page failed.

    Args:
        data_folder: the folder (local path, fsspec URI or ``DataFolder``) of the Parquet files.
        batch_size: the rows read at once from a file.
        id_key: the column with the page id. A table without it names its pages ``<item>_<0001>`` from ``item_key``
            and ``sequence_key``, which it then needs.
        image_key: the column with the image.
        item_key: the column with the page's ``item_id``; default: pages without item.
        sequence_key: the column with the page's position in its item (``Page.sequence``).
        image_folder: the folder relative image paths are read from; default ``data_folder``.
        read_metadata: the other columns go into the page's metadata; without it only the named columns are read.
        default_metadata: goes into every page's metadata.
        http: pybookget ``Config`` fields (rate limits, retries) for ``http(s)://`` image paths.
        prefetch: ``http(s)://`` images requested ahead of the page being given on, at least 1 (1: one request at a
            time). Pages keep the files' row order; the rate limits in ``http`` hold for all of them together, so one
            task can use its whole rate limit instead of waiting for each image in turn.
        paths_file, glob_pattern, recursive, limit, skip, file_progress, doc_progress, shuffle_files: datatrove's
            ``ParquetReader`` arguments.
    """

    name = "🖼️ image parquet"
    role = "reader"
    parts_added = ("image", "metadata")
    docs_args = {"data_folder": "pages/"}
    #: the share of a task's pages whose image may fail to be read (None: no limit; the builder sets it)
    max_page_errors: float | None = 0.01

    def __init__(self, data_folder: DataFolderLike, paths_file: DataFileLike | None = None,
                 glob_pattern: str | None = "**/*.parquet", recursive: bool = True, limit: int = -1, skip: int = 0,
                 batch_size: int = 64, id_key: str = "id", image_key: str = "image", item_key: str | None = None,
                 sequence_key: str | None = None, image_folder: DataFolderLike | None = None,
                 read_metadata: bool = False, file_progress: bool = False, doc_progress: bool = False,
                 default_metadata: dict | None = None, shuffle_files: bool = False, http: dict | None = None,
                 prefetch: int = 8):
        super().__init__(data_folder, paths_file, limit, skip, batch_size, read_metadata, file_progress,
                         doc_progress, None, "text", id_key, default_metadata, recursive, glob_pattern, shuffle_files)
        if prefetch < 1:
            raise PipelineConfigError("prefetch must be at least 1")
        self.image_key, self.item_key, self.sequence_key = image_key, item_key, sequence_key
        self.image_folder = get_datafolder(image_folder) if image_folder is not None else self.data_folder
        self.prefetch = prefetch
        self._opener = _Opener(http)

    def _request(self, value, filepath: str, page_id: str) -> tuple[Future, str | None]:
        """A future of the page's image (``_Opener.submit``: an http(s) request starts now) and the image's URI."""
        data, path = value, None
        if isinstance(value, dict):
            data, path = value.get("bytes"), value.get("path")
        elif isinstance(value, str):
            data, path = None, value
        if data is not None:
            return _future(lambda: bytes(data)), f"{self.data_folder.resolve_paths(filepath)}#{page_id}"
        if not path:
            def missing() -> bytes:
                raise PageError(page_id, "ImageParquetReader", f"{filepath}: neither image bytes nor an image path")
            return _future(missing), None
        if "://" in path or path.startswith("/"):
            return self._opener.submit(path), path

        def relative() -> bytes:
            with self.image_folder.open(path, "rb") as f:
                return f.read()
        return _future(relative), self.image_folder.resolve_paths(path)

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        self._budget = ErrorBudget(self, self.max_page_errors)          # one per task, over all its files
        yield from super().run(data, rank, world_size)

    def read_file(self, filepath: str):
        yield from reported_file(self, filepath, self._read_file(filepath))

    def _rows(self, filepath: str):
        """``(page_id, item, sequence, image value, other columns)`` for each row of the file, in order."""
        import pyarrow.parquet as pq

        with self.data_folder.open(filepath, "rb") as f, pq.ParquetFile(f) as pqf:
            derive = self.id_key not in pqf.schema_arrow.names
            if derive and not (self.item_key and self.sequence_key):
                raise PipelineConfigError(f"{filepath}: no page id column {self.id_key!r}; give id_key, or item_key and "
                                 "sequence_key to name pages <item>_<0001>")
            keys = [k for k in (None if derive else self.id_key, self.image_key, self.item_key, self.sequence_key)
                    if k]
            for batch in pqf.iter_batches(batch_size=self.batch_size, columns=None if self.read_metadata else keys):
                for row in batch.to_pylist():
                    item = row.pop(self.item_key) if self.item_key else None
                    sequence = row.pop(self.sequence_key) if self.sequence_key else None
                    page_id = (f"{item}_{int(sequence):04d}" if derive else str(row.pop(self.id_key)))
                    yield page_id, item, sequence, row.pop(self.image_key), row

    def _read_file(self, filepath: str):
        def submit(entry):
            return (entry, *self._request(entry[3], filepath, entry[0]))

        budget = getattr(self, "_budget", None) or ErrorBudget(self, self.max_page_errors)
        for entry, future, uri in prefetched(self._rows(filepath), submit, self.prefetch, lambda s: s[1].cancel()):
            page_id, item, sequence, _, row = entry
            item_id = None if item is None else str(item)
            sequence = None if sequence is None else int(sequence)
            budget.page()
            failure = None
            with self.track_time():
                fetches: list = []
                metadata = {**(self.default_metadata or {}),
                            **{k: v for k, v in row.items() if not isinstance(v, bytes | dict)}}
                try:
                    data = self._opener.result(future, fetches)
                    doc = new_page_document(page_id, data, uri=uri, item_id=item_id, sequence=sequence,
                                            metadata=metadata)
                except (*NOT_THE_PAGES, PageError):
                    raise
                except Exception as e:  # noqa: BLE001 - the page's error; the task goes on within its budget
                    doc = _unread_page(page_id, uri, item_id, sequence, metadata)
                    failure = (doc, record_error(doc, error_entry(self, e, field="image", raw_value=uri)), e)
                if fetches:
                    doc.metadata["trace"] = {"fetch": fetches}
            if failure is not None:
                self.stat_update("image_errors")
                budget.failed(*failure)                 # a PageError (the task fails) once the budget is spent
            else:
                self.stat_update("pages")
                self.update_media_stats(doc.media[0])
            yield doc


def _unread_page(page_id: str, uri: str | None, item_id: str | None, sequence: int | None, metadata: dict):
    """A page whose image could not be read: its record without image media (the error goes into its metadata)."""
    from datatrove.data import Document

    doc = Document(text="", id=page_id, media=[])
    set_page(doc, Page(page_id=page_id, item_id=item_id, sequence=sequence, image=PageImage(uri=uri),
                       metadata=metadata))
    return doc


