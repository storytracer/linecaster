"""``PageRecordReader``: page records written by an earlier linecaster pipeline (JSONL or Parquet), of any format
version: each row's ``schema`` says which, and ``UPGRADES`` brings an older row to today's on read."""
from __future__ import annotations

from datatrove.io import DataFolder, DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...data.page import PAGE_KEY, PAGE_SCHEMA
from ...errors import PipelineConfigError
from ..base.block import reported_file
from ..base.contract import Contract, Contracted, Part
from .images import _Opener

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
UPGRADES = {None: (_from_before_phase_1, "linecaster.page/1"), "linecaster.page/1": (_from_page_1, PAGE_SCHEMA)}


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


class PageRecordReader(Contracted, PipelineStep):
    """Page records written by a previous pipeline (linecaster's page writers: JSONL or Parquet), for the
    enrichment chain: each pipeline reads the previous one's folder and adds one part. With
    ``fetch_images`` the image bytes are read again from ``page.image.uri`` (page records never carry them), through
    datatrove ``DataFolder``s.

    Rows of an earlier format are read as today's (``upgrade``): records written before phase 1 (no ``schema``)
    name linecaster's transcription ``ocr`` (now ``ocr_new``), ``linecaster.page/1`` records a transcription's steps
    ``model`` (now ``steps``); a folder ``.../pages`` that holds no records but has
    a sibling ``rows`` (the folder's name before phase 1) is read from there.

    Files are distributed over tasks in turn. With ``item_shards`` the page records were written into item shards
    (``PageJsonlWriter(item_shards=N)``): the shard folders are distributed instead, each read whole, so a task
    sees every page of its items.

    ``provides`` declares the parts the records carry (``"ocr_new:lines"``, ``"ocr_original:*"``, or ``Part``s), for
    the builder's checks; without it the records may carry anything (reads after this reader are not checked). The
    builder sets it when it starts a stage from the page records of an earlier one."""

    type = "📖 - READER"
    name = "📄 page records"
    role = "reader"
    live_params = ("provides",)          # the builder declares what an earlier stage wrote

    def __init__(self, data_folder: DataFolderLike, glob_pattern: str = "**/*.jsonl*", fetch_images: bool = True,
                 uri_map: dict[str, str] | None = None, item_shards: bool = False, http: dict | None = None,
                 provides=None):
        """``uri_map`` rewrites image URI prefixes (e.g. a Hub path to a local copy of the same files); ``http``
        sets pybookget ``Config`` fields for ``http(s)://`` image URIs."""
        super().__init__()
        self.data_folder, self.glob_pattern, self.fetch_images = get_datafolder(data_folder), glob_pattern, fetch_images
        self.uri_map, self.item_shards = uri_map or {}, item_shards
        self.provides = None if provides is None else frozenset(Part.parse(p) for p in provides)
        self._opener = _Opener(http)

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

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        if data:
            yield from data
        files = sorted(self.data_folder.glob(self.glob_pattern))
        if not files:
            files = self._old_folder()
        if self.item_shards:
            shards = sorted({f.split("/", 1)[0] for f in files if "/" in f})
            if not shards:
                raise PipelineConfigError(f"No item shards (<shard>/...) under {self.data_folder.path}")
            mine = set(shards[rank::world_size])
            files = [f for f in files if f.split("/", 1)[0] in mine]
        else:
            files = files[rank::world_size]
        for path in files:
            yield from reported_file(self, path, self._documents(path))

    def _documents(self, path: str):
        from datatrove.data import Document, Media, MediaType

        for row in self._records(path):
            row = upgrade(row)
            page = row["page"]
            media, fetches = [], []
            uri = (page.get("image") or {}).get("uri")
            if self.fetch_images and uri:
                src = uri.split("#", 1)[0]
                for prefix, repl in self.uri_map.items():
                    if src.startswith(prefix):
                        src = repl + src[len(prefix):]
                media = [Media(id=row["id"], type=MediaType.IMAGE, url=uri,
                               media_bytes=self._opener.read(src, fetches))]
            doc = Document(text=row.get("text") or "", id=row["id"], media=media, metadata={"page": page})
            if row.get("errors"):
                doc.metadata["errors"] = row["errors"]
            if fetches:
                doc.metadata["trace"] = {"fetch": fetches}
            self.stat_update("pages")
            yield doc
