"""``PageRecordReader``: page records written by an earlier linecaster pipeline (JSONL or Parquet)."""
from __future__ import annotations

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ...errors import PipelineConfigError
from ..base.contract import Contract, Contracted, Part
from .images import _Opener


class PageRecordReader(Contracted, PipelineStep):
    """Page records written by a previous pipeline (linecaster's page writers: JSONL or Parquet), for the
    enrichment chain: each pipeline reads the previous one's folder and adds one part. With
    ``fetch_images`` the image bytes are read again from ``page.image.uri`` (page records never carry them), through
    datatrove ``DataFolder``s.

    Files are distributed over tasks in turn. With ``item_shards`` the page records were written into item shards
    (``PageJsonlWriter(item_shards=N)``): the shard folders are distributed instead, each read whole, so a task
    sees every page of its items.

    ``provides`` declares the parts the records carry (``"ocr_new:lines"``, ``"ocr_original:*"``, or ``Part``s), for
    the builder's checks; without it the records may carry anything (reads after this reader are not checked). The
    builder sets it when it starts a stage from the page records of an earlier one."""

    type = "📖 - READER"
    name = "📄 page records"
    role = "reader"

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

    def run(self, data=None, rank: int = 0, world_size: int = 1):
        from datatrove.data import Document, Media, MediaType

        if data:
            yield from data
        files = sorted(self.data_folder.glob(self.glob_pattern))
        if self.item_shards:
            shards = sorted({f.split("/", 1)[0] for f in files if "/" in f})
            if not shards:
                raise PipelineConfigError(f"No item shards (<shard>/...) under {self.data_folder.path}")
            mine = set(shards[rank::world_size])
            files = [f for f in files if f.split("/", 1)[0] in mine]
        else:
            files = files[rank::world_size]
        for path in files:
            for row in self._records(path):
                page = row["page"]
                media = []
                uri = (page.get("image") or {}).get("uri")
                if self.fetch_images and uri:
                    src = uri.split("#", 1)[0]
                    for prefix, repl in self.uri_map.items():
                        if src.startswith(prefix):
                            src = repl + src[len(prefix):]
                    media = [Media(id=row["id"], type=MediaType.IMAGE, url=uri, media_bytes=self._opener.read(src))]
                doc = Document(text=row.get("text") or "", id=row["id"], media=media, metadata={"page": page})
                if row.get("errors"):
                    doc.metadata["errors"] = row["errors"]
                self.stat_update("pages")
                yield doc
