"""``PageRecordReader``: page records written by an earlier linecaster pipeline (JSONL or Parquet), of any format
version: each row's ``schema`` says which, and ``UPGRADES`` brings an older row to today's on read."""
from __future__ import annotations

from datatrove.io import DataFolder, DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...data.page import PAGE_KEY, PAGE_SCHEMA
from ...data.upgrade import OLD, page_2_to_3
from ...errors import PageError, PipelineConfigError
from ..base.block import reported_file
from ..base.contract import Contract, Contracted, Part
from ..base.page import error_entry, record_error
from .fragments import read_image
from .images import _Opener
from .sampling import Sampled

#: the folder page records had before phase 1 (``OUT/rows``; today ``OUT/pages``)
OLD_FOLDER = "rows"


def _from_before_phase_1(row: dict) -> dict:
    """A row written before phase 1 (no ``schema``): linecaster's transcription was ``ocr``, today ``ocr_new``."""
    transcriptions = (row.get(PAGE_KEY) or {}).get("transcriptions") or {}
    if "ocr" in transcriptions and "ocr_new" not in transcriptions:
        transcriptions["ocr_new"] = transcriptions.pop("ocr")
    return row


def _from_page_1(row: dict) -> dict:
    """A ``linecaster.page/1`` row: a transcription's steps were ``model`` (one ``ModelInfo`` each), today
    ``steps`` (``StepInfo``, the same fields plus ``engine``)."""
    for t in ((row.get(PAGE_KEY) or {}).get("transcriptions") or {}).values():
        if "model" in t and "steps" not in t:
            t["steps"] = t.pop("model")
    return row


#: a stored row's ``schema`` (``None``: none, the rows before phase 1) -> the function that brings it to the next
#: version, and that version
UPGRADES = {None: (_from_before_phase_1, "linecaster.page/1"), "linecaster.page/1": (_from_page_1, OLD),
            OLD: (page_2_to_3, PAGE_SCHEMA)}


def upgrade(row: dict) -> dict:
    """``row`` in today's format (``PAGE_SCHEMA``), through ``UPGRADES``; an unknown format is an error."""
    seen = set()
    while row.get("schema") != PAGE_SCHEMA:
        version = row.get("schema")
        if version not in UPGRADES or version in seen:
            raise PipelineConfigError(f"page record {row.get('id')}: unknown format {version!r} (this linecaster reads "
                                      f"{PAGE_SCHEMA} and earlier)")
        seen.add(version)
        fn, to = UPGRADES[version]
        row = {**fn(row), "schema": to}
    return row


class PageRecordReader(Sampled, Contracted, PipelineStep):
    """Reads the page records an earlier run wrote (JSON Lines or Parquet), so a pipeline can add one more part.

    Each pipeline of a workflow reads the previous one's ``pages/`` folder (linecaster's page writers) and adds its
    part. The records bring ``metadata`` and, with ``fetch_images``, ``image``: page records never carry the image
    bytes, so they are read again from ``page.image.uri`` through datatrove ``DataFolder``s (``http(s)://``
    through ``linecaster.net.http``); a URI with a fragment names a part of its file (``file.pdf#page=<n>``: that page rendered,
    ``file.parquet#<page_id>``: that row's image, ``linecaster.blocks.readers.fragments``), and one that cannot be
    resolved is the page's error (field ``image``, stat ``image_errors``), never the whole file. A page's errors
    come back as ``doc.metadata["errors"]``, so later model blocks pass it by.

    Rows of an earlier format are read as today's (``upgrade``, by the row's ``schema``): rows without ``schema``
    name linecaster's transcription ``ocr`` (read as ``ocr_new``), ``linecaster.page/1`` rows a transcription's
    steps ``model`` (read as ``steps``), ``linecaster.page/2`` rows in the annotation model
    (``linecaster.data.upgrade.page_2_to_3``); a folder ``.../pages`` that holds no records but has a sibling ``rows``
    (the folder's earlier name) is read from there.

    Files are distributed over tasks in turn. With ``item_shards`` the page records were written into item shards
    (``PageJsonlWriter(item_shards=N)``): the shard folders are distributed instead, each read whole, so a task
    sees every page of its items (``whole_items``). No shard folder is a ``PipelineConfigError``.

    Args:
        data_folder: the folder (local path, fsspec URI or ``DataFolder``) of the page records.
        glob_pattern: the record files to read; default JSON Lines (``**/*.jsonl*``), ``**/*.parquet`` for Parquet.
        fetch_images: read each page's image again (the part ``image``); without it the pages carry no image.
        uri_map: image URI prefixes rewritten before reading (e.g. a Hub path to a local copy of the same files).
        item_shards: the records are item shards (``<shard>/<rank>...``), each read whole by one task.
        http: ``linecaster.net.http.HTTPConfig`` fields for ``http(s)://`` image URIs.
        http_policy: an HTTP policy file (``linecaster.net.policy``): settings per host for those URIs, with ``http``
            between its root and its hosts.
        provides: the parts the records carry (``"ocr_new:lines"``, ``"ocr_original:*"``, or ``Part``s), for the
            builder's checks; default: anything (``*``; reads after this reader are not checked). The builder sets it
            when it starts a stage from the page records of an earlier one.
        sample: only the pages of this ``linecaster.data.sample.SampleRule``, chosen from the records' ids
            (``page.item_id`` or ``""``, ``id``), read from every record file before any image is fetched; each task
            reads its files as without it (only those holding sample pages) and passes on their sample pages alone
            (the first record of an id that is listed twice). Default: every record.
    """

    type = "📖 - READER"
    name = "📄 page records"
    role = "reader"
    live_params = ("provides",)          # the builder declares what an earlier stage wrote
    docs_args = {"data_folder": "out/pages"}

    def __init__(self, data_folder: DataFolderLike, glob_pattern: str = "**/*.jsonl*", fetch_images: bool = True,
                 uri_map: dict[str, str] | None = None, item_shards: bool = False, http: dict | None = None,
                 provides=None, http_policy: str | None = None, sample=None):
        super().__init__()
        self._set_sample(sample)
        self._sample_rows: dict[str, list[int]] | None = None   # file -> the indices of its sample records
        self.data_folder, self.glob_pattern, self.fetch_images = get_datafolder(data_folder), glob_pattern, fetch_images
        self.uri_map, self.item_shards = uri_map or {}, item_shards
        self.provides = None if provides is None else frozenset(Part.parse(p) for p in provides)
        self._opener = _Opener(http, http_policy)

    @property
    def whole_items(self) -> bool:
        """Whether each task reads whole items (item shards): a binder after it needs no second stage."""
        return self.item_shards

    def contract(self) -> Contract:
        """The page record and image (``fetch_images``) and what ``provides`` declares; every part (``*``) when it
        declares nothing."""
        given = frozenset({Part("*")}) if self.provides is None else self.provides
        own = {Part("metadata")} | ({Part("image")} if self.fetch_images else set())
        return Contract(unit="page", role=self.role, adds=frozenset(own) | (given - {Part("image")}))

    def _records(self, path: str):
        import gzip
        import json

        if path.endswith(".parquet"):
            import pyarrow.parquet as pq

            with self.data_folder.open(path, "rb") as f:
                for row in pq.read_table(f).to_pylist():
                    for key in ("page", "errors"):     # PageParquetWriter stores both as JSON strings
                        if isinstance(row.get(key), str):
                            row[key] = json.loads(row[key])
                    yield row
            return
        with self.data_folder.open(path, "rb") as f:
            stream = gzip.open(f, "rt") if path.endswith(".gz") else (line.decode() for line in f)
            for line in stream:
                if line.strip():
                    yield json.loads(line)

    def _old_folder(self) -> list[str]:
        """The records of the folder's sibling ``rows`` (the name before phase 1) when this one is ``pages`` and
        holds none: the reader then reads from there."""
        path = self.data_folder.path.rstrip("/")
        parent, _, name = path.rpartition("/")
        if name != "pages":
            return []
        old = DataFolder(f"{parent}/{OLD_FOLDER}", fs=self.data_folder.fs)
        files = sorted(old.glob(self.glob_pattern)) if old.exists("") else []
        if files:
            logger.warning("{folder} holds no page records; reading {old}, their folder before phase 1",
                           folder=path, old=old.path)
            self.data_folder = old
        return files

    def _files(self) -> list[str]:
        files = sorted(self.data_folder.glob(self.glob_pattern))
        return files or self._old_folder()

    def _compute_sample(self, save: bool):
        from ...data.sample import sample_pairs

        where, pairs = [], []
        for path in self._files():
            for i, row in enumerate(self._records(path)):
                item = (row.get("page") or {}).get("item_id")
                pairs.append(("" if item is None else str(item), str(row["id"])))
                where.append((path, i))
        sample = sample_pairs(pairs, self.sample)
        keys, rows = sample.keys(), {}
        for key, (path, i) in zip(pairs, where):
            if key in keys:
                keys.discard(key)                     # an id listed twice: its first record
                rows.setdefault(path, []).append(i)
        self._sample_rows = rows
        return sample

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        if data:
            yield from data
        files = self._files()
        chosen = None
        if self.sample is not None:
            self.sampled()
            chosen = {path: set(rows) for path, rows in self._sample_rows.items()}
            files = [f for f in files if f in chosen]
        if self.item_shards:
            shards = sorted({f.split("/", 1)[0] for f in files if "/" in f})
            if not shards:
                raise PipelineConfigError(f"No item shards (<shard>/...) under {self.data_folder.path}")
            mine = set(shards[rank::world_size])
            files = [f for f in files if f.split("/", 1)[0] in mine]
        else:
            files = files[rank::world_size]
        for path in files:
            yield from reported_file(self, path, self._documents(path, None if chosen is None else chosen[path]))

    def _mapped(self, src: str) -> str:
        """``src`` with the first matching prefix of ``uri_map`` rewritten."""
        for prefix, repl in self.uri_map.items():
            if src.startswith(prefix):
                return repl + src[len(prefix):]
        return src

    def _documents(self, path: str, rows: set[int] | None = None):
        from datatrove.data import Document, Media, MediaType

        for i, row in enumerate(self._records(path)):
            if rows is not None and i not in rows:
                continue
            row = upgrade(row)
            page = row["page"]
            media, fetches, failure = [], [], None
            uri = (page.get("image") or {}).get("uri")
            if self.fetch_images and uri:
                try:
                    data = read_image(uri, lambda src: self._opener.read(self._mapped(src), fetches), row["id"],
                                      page.get("metadata"))
                except PageError as e:          # a fragment that names nothing it can fetch: the page's error
                    failure = e
                else:
                    media = [Media(id=row["id"], type=MediaType.IMAGE, url=uri, media_bytes=data)]
            doc = Document(text=row.get("text") or "", id=row["id"], media=media, metadata={"page": page})
            if row.get("errors"):
                doc.metadata["errors"] = row["errors"]
            if failure is not None:
                record_error(doc, error_entry(self, failure, field="image", raw_value=uri))
                self.stat_update("image_errors")
            if fetches:
                doc.metadata["trace"] = {"fetch": fetches}
            self.stat_update("pages")
            yield doc
