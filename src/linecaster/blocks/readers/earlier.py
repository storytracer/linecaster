"""Page images that earlier harvests' folders already hold (``harvest.py --reuse-from DIR`` with ``--parquet`` or
``--manifests``): a harvest into a new folder reads them from there instead of fetching them, so a changed page list
gets one complete folder of its own.

An earlier harvest's page records (``DIR/pages/**/*.jsonl.gz``) can be large (a manifest's data, a table's columns,
with ``--existing-ocr`` the library's OCR), and a harvest has millions of pages, so they are read once per launch, not
per task or worker: ``build_index`` writes, for each page image's source URL (``image.extra.source_uri``, the URL that
was fetched), where its copy is (``<item>/<page>.<ext>`` under ``DIR/images``) and its ``sha256``, sorted by URL, to
one Parquet file in the new run's folder (``INDEX``). A record with errors, without a copy or without a source URL
gives nothing. With several folders the newest one holding a URL wins (its newest run record's ``created``; a folder
without one counts as the oldest, and among equals the one named first). A task asks for its own URLs only
(``EarlierImages.lookup``: a read of the index between the smallest and the largest of them, which Parquet narrows to
the row groups in that range), and ``EarlierImages.read`` reads a copy and checks it against its ``sha256``: a copy that
differs or cannot be read is fetched (stats ``reuse_from_mismatch``, ``reuse_from_unreadable``). The URL is the key,
not the item or the page id, which can differ between versions of a list; a page that came through a redirect or its
fallback URL has another URL in its record, and is fetched.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable

from datatrove.io import get_datafolder
from loguru import logger

#: where a run keeps the index of its earlier folders' page images (relative to its folder)
INDEX = "logs/reuse-from.parquet"
#: rows per row group of the index: what one lookup reads at least
ROW_GROUP = 16_384


class Earlier:
    """A page image read from an earlier harvest's folder: the folder, its copy there (URI), the bytes."""

    def __init__(self, folder: str, uri: str, data: bytes):
        self.folder, self.uri, self.data = folder, uri, data


def _folder_time(folder: str) -> str:
    """The newest ``created`` of the folder's run records (``run.yaml``, ``run-<time>.yaml``), or ``""``."""
    import yaml

    df = get_datafolder(folder)
    newest = ""
    try:
        names = [n for n in df.ls("", detail=False) if n.rsplit("/", 1)[-1].startswith("run") and n.endswith(".yaml")]
    except FileNotFoundError:
        return ""
    for name in names:
        try:
            with df.open(name.rsplit("/", 1)[-1], "rt") as f:
                created = str((yaml.safe_load(f) or {}).get("created") or "")
        except Exception:  # noqa: BLE001 - a run record that cannot be read gives no time
            continue
        newest = max(newest, created)
    return newest


def copy_path(page: dict) -> str | None:
    """Where a page record's copy is under its harvest's ``images`` folder: ``<item>/<page>.<ext>`` (``image.uri``'s
    last two parts, an absolute path from where the folder was then), ``<page>.<ext>`` for a page without item."""
    uri = ((page.get("image") or {}).get("uri") or "").rstrip("/")
    if not uri:
        return None
    parts = uri.split("/")
    return "/".join(parts[-2:]) if page.get("item_id") else parts[-1]


def build_index(folders: Iterable[str], path: str, stat: Callable[[str], None] | None = None) -> int:
    """Writes the index of ``folders``' page images to ``path`` (module docstring) and returns how many URLs it holds.

    Args:
        folders: earlier harvests' folders (any fsspec paths), in the order given.
        path: the index file (any fsspec path).
        stat: counts what was read (``reuse_from_records``), optional.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    folders = [str(f).rstrip("/") for f in folders]
    ranked = sorted(folders, key=lambda f: (_folder_time(f), -folders.index(f)))      # oldest first: newer overwrite
    best: dict[str, tuple[str, str, str]] = {}
    for folder in ranked:
        pages = get_datafolder(f"{folder}/pages")
        try:
            files = sorted(pages.list_files(recursive=True, glob_pattern="**/*.jsonl.gz"))
        except FileNotFoundError:
            files = []
        n = 0
        for name in files:
            with pages.open(name, "rt", compression="gzip") as f:
                for line in f:
                    record = json.loads(line)
                    page = record.get("page") or {}
                    image = page.get("image") or {}
                    url = (image.get("extra") or {}).get("source_uri")
                    rel = copy_path(page)
                    if record.get("errors") or not url or not rel or not image.get("sha256"):
                        continue
                    best[url] = (folder, rel, image["sha256"])
                    n += 1
        logger.info("--reuse-from {folder}: {n} page images in its records", folder=folder, n=f"{n:,}")
        if stat is not None:
            stat("reuse_from_records")
    urls = sorted(best)
    table = pa.table({"url": urls, "folder": [best[u][0] for u in urls], "path": [best[u][1] for u in urls],
                      "sha256": [best[u][2] for u in urls]})
    folder, _, name = path.rstrip("/").rpartition("/")
    out = get_datafolder(folder or ".")
    with out.open(name, "wb") as f:
        pq.write_table(table, f, row_group_size=ROW_GROUP)
    return len(urls)


class EarlierImages:
    """The index of earlier harvests' page images (``build_index``), asked per task.

    Args:
        index: the index file (``<run folder>/INDEX``).
    """

    def __init__(self, index: str):
        self.index = index
        self._found: dict[str, tuple[str, str, str]] = {}

    def __getstate__(self):                      # a task's lookup belongs to that task
        return {"index": self.index, "_found": {}}

    def lookup(self, urls: Iterable[str]) -> int:
        """Reads the index for ``urls`` (a task's, or an item's), replacing the last lookup; returns how many it holds."""
        import pyarrow.parquet as pq

        wanted = sorted({u for u in urls if u})
        self._found = {}
        if not wanted:
            return 0
        keep, lo, hi = set(wanted), wanted[0], wanted[-1]
        folder, _, name = self.index.rstrip("/").rpartition("/")
        df = get_datafolder(folder or ".")
        with df.open(name, "rb") as f, pq.ParquetFile(f) as pqf:
            column = pqf.schema_arrow.get_field_index("url")
            for i in range(pqf.num_row_groups):
                stats = pqf.metadata.row_group(i).column(column).statistics
                if stats is not None and stats.has_min_max and (stats.max < lo or stats.min > hi):
                    continue                     # sorted by URL: the group holds none of the task's
                group = pqf.read_row_group(i, columns=["url", "folder", "path", "sha256"]).to_pydict()
                for url, folder_, path, sha in zip(group["url"], group["folder"], group["path"], group["sha256"],
                                                   strict=True):
                    if url in keep:
                        self._found[url] = (folder_, path, sha)
        return len(self._found)

    def read(self, url: str, stat: Callable[[str], None] | None = None) -> Earlier | None:
        """The earlier copy of ``url`` (from the last ``lookup``), read and checked against its ``sha256``; None when
        there is none, or it cannot be read or differs (then the page is fetched, and ``stat`` counts it)."""
        import hashlib

        found = self._found.get(url)
        if found is None:
            return None
        folder, path, sha = found
        images = get_datafolder(f"{folder}/images")
        try:
            with images.open(path, "rb") as f:
                data = f.read()
        except Exception:  # noqa: BLE001 - a copy that cannot be read is fetched from the source
            if stat is not None:
                stat("reuse_from_unreadable")
            return None
        if hashlib.sha256(data).hexdigest() != sha:
            if stat is not None:
                stat("reuse_from_mismatch")
            return None
        return Earlier(folder, images.resolve_paths(path), data)


def mark_reused_from(doc, earlier: Earlier) -> None:
    """Marks a page read from an earlier harvest's copy (``image.extra``: ``reused_from``, the folder;
    ``reused_from_uri``, the copy there): ``ImageFilesWriter`` writes it into this run's folder, and the console counts
    it apart from the downloads."""
    from ..base.page import page_of, set_page

    page = page_of(doc)
    extra = {**page.image.extra, "reused_from": earlier.folder, "reused_from_uri": earlier.uri}
    set_page(doc, page.model_copy(update={"image": page.image.model_copy(update={"extra": extra})}))
