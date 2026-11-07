"""Readers for page images, on datatrove's reader conventions (``BaseDiskReader``: ``data_folder``, ``paths_file``,
``glob_pattern``, ``recursive``, ``limit`` and ``skip`` per task, entries distributed over tasks in turn):

* ``ImageFolderReader``: image files (found by ``glob_pattern`` or listed in a ``paths_file``), one page each.
* ``ImageParquetReader``: Parquet files with an image column (the bytes, or a path to the image), e.g. an image
  dataset on the Hub (``hf://datasets/<repo>@<revision>/data``), one page per row; the rows, not the files, are
  divided over the tasks (``linecaster.blocks.readers.tables``).

An item's pages can land in different tasks;
item-level steps run in a later stage over item shards (``linecaster.blocks.writers.shards``). Page records of an
earlier run: ``linecaster.blocks.readers.records``.

Images are opened through datatrove's ``DataFolder``, so any fsspec path works (local, ``s3://``, ``hf://``);
fsspec's settings apply (e.g. ``FSSPEC_S3_ANON=true`` for a public bucket). Absolute ``http(s)://`` image URLs
(in a Parquet image column or a page record) are fetched with pybookget (``linecaster[pybookget]``), politely:
rate limits (per worker: one fetcher per process, ``HTTPFetcher.shared``), retries that honor
``Retry-After``, requests ahead in a window that sizes itself (``linecaster.net.http.prefetched``). Manifests (IIIF, METS): ``linecaster.blocks.readers.manifests``.
"""
from __future__ import annotations

import posixpath
import random
from collections.abc import Callable
from concurrent.futures import Future

from datatrove.io import DataFileLike, DataFolderLike, get_datafolder, get_shard_from_paths_file
from datatrove.pipeline.readers.base import BaseDiskReader
from datatrove.pipeline.readers.parquet import ParquetReader

from ...errors import PageError, PipelineConfigError
from ...net.http import prefetched
from .existing import ExistingImages, Reused, mark_reused
from .tables import (PAGES_PER_TASK, first_rows, item_ranges, item_runs, row_slices, rows_between, slice_batches,
                     table_rows, tasks_for, total_rows, whole_file)
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
    ``Retry-After``; ``http`` sets its ``Config`` fields; one ``linecaster.net.http.HTTPFetcher.shared`` per process
    and configuration, so its rate limits hold across a worker's tasks)."""

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
                self._fetcher = HTTPFetcher.shared(**self.http)
                self._fetcher.new_user_agent()            # a task's first request: its own random User-Agent
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
        max_pages: only the first ``max_pages`` files (sorted, or as ``paths_file`` lists them), for the whole run,
            divided over the tasks as all of them would be; default: every file.
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
                 shuffle_files: bool = False, max_pages: int | None = None):
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        if max_pages is not None and max_pages < 1:
            raise PipelineConfigError("max_pages must be at least 1")
        self.max_pages = max_pages
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
        if self.paths_file and self.max_pages is not None:
            files = list(get_shard_from_paths_file(self.paths_file, 0, 1))[:self.max_pages][rank::world_size]
        elif self.paths_file:
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
            files = all_files[:self.max_pages][rank::world_size]
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

    The rows of all files, in order, are divided over the tasks in equal shards, read by row group
    (``linecaster.blocks.readers.tables``), so any table works with any number of tasks; an item's pages can land in
    two tasks where a shard ends. ``auto_tasks`` is the task count for shards of about ``PAGES_PER_TASK`` pages, which
    ``linecaster.runtime.run`` uses for a pipeline without engines. Each row adds ``image`` and ``metadata`` (the page
    record). The image column holds the image
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
        http: pybookget ``Config`` fields (rate limits, retries) for ``http(s)://`` image paths. Their images are
            requested ahead of the page being given on, as many as keep the rate limits busy
            (``linecaster.net.http.prefetched``), and pages go on as their images arrive: a slow request (one being
            retried) delays only its own page. Rows read without a request (bytes, files) keep their order.
        limit, skip: pages per task, as datatrove's count documents; they apply before anything is read or fetched.
        max_pages: only the first ``max_pages`` rows of the input, for the whole run: the tables are read as if they
            ended there, divided over the tasks (and ``auto_tasks`` counted) the same way; default: every row.
        reuse_folder: where ``ImageFilesWriter`` writes the images (``pipelines/harvest.py``: ``OUT/images``): a
            page whose file is already there is read from it instead of from the source
            (``linecaster.blocks.readers.existing``: one listing per item), so a resumed harvest does not fetch it
            again; its record is complete and says ``image.extra["reused"]``. A copy that cannot be read is fetched
            from the source. Default: none.
        task_per_item: the tasks divide the items (the ``item_key`` values, needs it; an item's rows need not be
            together), not the rows, and ``auto_tasks`` is one task per item: each item whole in its task, a task that
            fails costs one item (``pipelines/harvest.py``). Default: rows in equal shards.
        paths_file, glob_pattern, recursive, file_progress, doc_progress: datatrove's ``ParquetReader`` arguments.
        shuffle_files: read the files of a task's shard in random order.
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
                 max_pages: int | None = None, task_per_item: bool = False,
                 reuse_folder: DataFolderLike | None = None):
        super().__init__(data_folder, paths_file, limit, skip, batch_size, read_metadata, file_progress,
                         doc_progress, None, "text", id_key, default_metadata, recursive, glob_pattern, shuffle_files)
        if max_pages is not None and max_pages < 1:
            raise PipelineConfigError("max_pages must be at least 1")
        if task_per_item and not item_key:
            raise PipelineConfigError("task_per_item needs item_key: the items are runs of rows with the same item")
        self.max_pages, self.task_per_item = max_pages, task_per_item
        self.reuse_folder = reuse_folder
        self._existing = ExistingImages(reuse_folder) if reuse_folder is not None else None
        self._starts = None
        self.image_key, self.item_key, self.sequence_key = image_key, item_key, sequence_key
        self.image_folder = get_datafolder(image_folder) if image_folder is not None else self.data_folder
        self._opener = _Opener(http)
        self._layout: list | None = None

    def layout(self) -> list[tuple[str, tuple[int, ...]]]:
        """The input files with the rows of each row group (``tables.table_rows``), read once and kept."""
        if self._layout is None:
            files = (list(get_shard_from_paths_file(self.paths_file, 0, 1)) if self.paths_file
                     else self.data_folder.list_files(recursive=self.recursive, glob_pattern=self.glob_pattern))
            if not files:
                raise PipelineConfigError(f"No Parquet files found on {self.data_folder.path} matching "
                                          f"{self.glob_pattern!r}")
            layout = table_rows(self.data_folder, files)
            self._layout = layout if self.max_pages is None else first_rows(layout, self.max_pages)
        return self._layout

    def items(self) -> tuple:
        """The input's items and their rows (``tables.item_runs``), read once and kept."""
        if self._starts is None:
            self._starts = item_runs(self.data_folder, self.layout(), self.item_key)
        return self._starts

    def auto_tasks(self) -> int:
        """The task count: one per item with ``task_per_item``, else shards of about ``PAGES_PER_TASK`` pages."""
        if self.task_per_item:
            return max(1, len(self.items()[2]) - 1)
        return tasks_for(total_rows(self.layout()), PAGES_PER_TASK)

    def _task_ranges(self, rank: int, world_size: int) -> list[tuple[int, int]]:
        if self.task_per_item:
            return item_ranges(self.items(), rank, world_size)
        total = total_rows(self.layout())
        return [(rank * total // world_size, (rank + 1) * total // world_size)]

    def task_pages(self, rank: int, world_size: int) -> int:
        """The pages task ``rank`` of ``world_size`` reads: its shard's rows, after ``skip``, up to ``limit``."""
        rows = max(0, sum(hi - lo for lo, hi in self._task_ranges(rank, world_size)) - self.skip)
        return rows if self.limit == -1 else min(rows, self.limit)

    def _source(self, value, filepath: str, page_id: str) -> str:
        """The URI the page's image would be read from (``_request``'s), without reading it."""
        path = value.get("path") if isinstance(value, dict) else value if isinstance(value, str) else None
        if isinstance(value, dict) and value.get("bytes") is not None or not path:
            return f"{self.data_folder.resolve_paths(filepath)}#{page_id}"
        return path if "://" in path or path.startswith("/") else self.image_folder.resolve_paths(path)

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
        if data:
            yield from data
        self._budget = ErrorBudget(self, self.max_page_errors)          # one per task, over all its files
        self._opener._fetcher = None                     # taken again (shared) at the task's first request
        slices = ([s for lo, hi in self._task_ranges(rank, world_size) for s in rows_between(self.layout(), lo, hi)]
                  if self.task_per_item else row_slices(self.layout(), rank, world_size))
        self._log_limit_scope(rank, world_size)
        files = list(dict.fromkeys(path for path, *_ in slices))
        if self.shuffle_files:
            random.shuffle(files)
        self._counts = {"skip": self.skip, "limit": self.limit}
        for path in files:
            if self._counts["limit"] == 0:
                break
            self.stat_update("input_files")
            for doc in reported_file(self, path, self._read_file(path, [s for s in slices if s[0] == path])):
                self.update_doc_stats(doc)
                yield doc

    def read_file(self, filepath: str):
        """The pages of one whole file (datatrove's reader interface; ``run`` reads a task's shard of rows)."""
        self._counts = {"skip": 0, "limit": -1}
        yield from reported_file(self, filepath, self._read_file(filepath, None))

    def _rows(self, filepath: str, slices: list | None):
        """``(page_id, item, sequence, image value, other columns)`` for each row of ``slices`` of the file (None:
        every row), in order, after the task's ``skip`` and up to its ``limit``."""
        import pyarrow.parquet as pq

        counts = self._counts
        with self.data_folder.open(filepath, "rb") as f, pq.ParquetFile(f) as pqf:
            derive = self.id_key not in pqf.schema_arrow.names
            if derive and not (self.item_key and self.sequence_key):
                raise PipelineConfigError(f"{filepath}: no page id column {self.id_key!r}; give id_key, or item_key and "
                                 "sequence_key to name pages <item>_<0001>")
            keys = [k for k in (None if derive else self.id_key, self.image_key, self.item_key, self.sequence_key)
                    if k]
            columns = None if self.read_metadata else keys
            for batch in slice_batches(pqf, slices or whole_file(pqf, filepath), columns, self.batch_size):
                for row in batch.to_pylist():
                    if counts["skip"] > 0:
                        counts["skip"] -= 1
                        continue
                    if counts["limit"] == 0:
                        return
                    if counts["limit"] > 0:
                        counts["limit"] -= 1
                    item = row.pop(self.item_key) if self.item_key else None
                    sequence = row.pop(self.sequence_key) if self.sequence_key else None
                    page_id = (f"{item}_{int(sequence):04d}" if derive else str(row.pop(self.id_key)))
                    yield page_id, item, sequence, row.pop(self.image_key), row

    def _read_file(self, filepath: str, slices: list | None):
        def submit(entry):
            page_id, item = entry[0], entry[1]
            copy = self._existing.get(None if item is None else str(item), page_id) if self._existing else None
            if copy is not None:                    # already written by an earlier launch: read, not fetched
                try:
                    data = self._opener.read(copy[0])
                except Exception:  # noqa: BLE001 - a copy that cannot be read is fetched from the source
                    data = None
                if data is not None:
                    return entry, _future(lambda: Reused(copy, data)), self._source(entry[3], filepath, page_id)
            return (entry, *self._request(entry[3], filepath, entry[0]))

        budget = getattr(self, "_budget", None) or ErrorBudget(self, self.max_page_errors)
        rows = self._rows(filepath, slices)
        for entry, future, uri in prefetched(rows, submit, lambda s: s[1].cancel(), future=lambda s: s[1],
                                             fetcher=lambda: self._opener._fetcher, ordered=False):
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
                    raw = future.result() if future.done() and not future.exception() else None
                    reused = isinstance(raw, Reused)
                    data = raw.data if reused else self._opener.result(future, fetches)
                    doc = new_page_document(page_id, data, uri=uri, item_id=item_id, sequence=sequence,
                                            metadata=metadata)
                    if reused:
                        mark_reused(doc)
                        self.stat_update("reused")
                except (*NOT_THE_PAGES, PageError):
                    raise
                except Exception as e:  # noqa: BLE001 - the page's error; the task goes on within its budget
                    from ...net.http import failed_fetch

                    if (record := failed_fetch(e)) is not None:     # its attempts, for the page's trace
                        fetches.append({**record, "what": "image"})
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


