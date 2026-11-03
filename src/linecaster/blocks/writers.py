"""Writers on top of datatrove's.

* page rows (everything but the image bytes, plus id and text): ``PageJsonlWriter``,
  ``PageParquetWriter``, one file per task (``${rank}``) or per item (``${item_id}``);
* per-page files (hOCR, ALTO, PAGE, txt, md, DoclingDocument JSON, Transcription JSON):
  ``PageFilesWriter``, ``<item_id>/<page_id>.<ext>``;
* per-item texts from ``ItemTexts``: ``ItemTextJsonlWriter`` (one folder per variant) and
  ``ItemTextFilesWriter`` (``<variant>/<item_id>.txt|.md``).
"""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep
from datatrove.pipeline.writers import JsonlWriter, ParquetWriter

from ..page import PAGE_KEY


def page_row(self, doc) -> dict:
    """datatrove adapter: ``id``, ``text`` and the page row; errors recorded on the way are kept."""
    row = {"id": doc.id, "text": doc.text, PAGE_KEY: doc.metadata.get(PAGE_KEY)}
    if doc.metadata.get("errors"):
        row["errors"] = doc.metadata["errors"]
    return row


def page_row_json(self, doc) -> dict:
    """Parquet-friendly: the page row as a JSON string (its nested structure varies between steps)."""
    row = page_row(self, doc)
    row[PAGE_KEY] = json.dumps(row[PAGE_KEY], ensure_ascii=False)
    if "errors" in row:
        row["errors"] = json.dumps(row["errors"], ensure_ascii=False)
    return row


class PageJsonlWriter(JsonlWriter):
    name = "🐿 page rows (jsonl)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.jsonl.gz", **kwargs):
        super().__init__(output_folder, output_filename, adapter=page_row, **kwargs)


class PageParquetWriter(ParquetWriter):
    name = "📒 page rows (parquet)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${rank}.parquet", **kwargs):
        super().__init__(output_folder, output_filename, adapter=page_row_json, **kwargs)


# ------------------------------------------------------------------ per-page files

#: format -> file extension
PAGE_FILE_EXTENSIONS = {
    "hocr": "hocr",                       # hOCR 1.2 (linecaster's serialiser)
    "alto": "alto.xml",                   # ALTO 4.4
    "page": "page.xml",                   # PAGE-XML 2019
    "txt": "txt",                         # the DoclingDocument's text export, else the page text
    "md": "md",                           # the DoclingDocument's Markdown export, else the page text
    "json": "json",                       # the DoclingDocument (from AssembleDocument)
    "transcription": "transcription.json",  # the Transcription as linecaster JSON
}


class PageFilesWriter(PipelineStep):
    """One file per page and format: ``<output_folder>/<item_id>/<page_id><suffix>.<ext>`` (any fsspec
    folder: local, ``s3://``, ``hf://buckets/...``). Pages pass through, so writers can be chained.

    * ``hocr``, ``alto``, ``page``: linecaster's serialisers (``to_hocr``/``to_alto``/``to_page``) at the
      page image's size;
    * ``md``, ``txt``, ``json``: the DoclingDocument's exports when the transcription has one
      (``AssembleDocument``; ``furniture`` keeps page headers and footers in md and txt); without one,
      md and txt fall back to ``Transcription.text`` (lines in reading order, tables as Markdown/HTML)
      and json is skipped (counted as ``no_document``);
    * ``transcription``: the ``Transcription`` itself as JSON.

    ``bucket_by_item=False`` writes ``<page_id><suffix>.<ext>`` flat (as squiddleocr and
    ``PageExportsWriter`` name their files); pages without ``item_id`` are always written flat."""

    type = "💽 - WRITER"
    name = "🗂️ page files"

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("hocr", "alto", "page", "txt"),
                 transcription: str = "ocr", suffix: str = "", furniture: bool = False, bucket_by_item: bool = True):
        super().__init__()
        unknown = set(formats) - set(PAGE_FILE_EXTENSIONS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {sorted(PAGE_FILE_EXTENSIONS)}")
        self.output_folder, self.formats, self.transcription = output_folder, tuple(formats), transcription
        self.suffix, self.furniture, self.bucket_by_item = suffix, furniture, bucket_by_item

    def path(self, page) -> str:
        stem = f"{page.page_id}{self.suffix}"
        return f"{page.item_id}/{stem}" if self.bucket_by_item and page.item_id else stem

    def render(self, page, t, fmt: str, document=None) -> str | bytes | None:
        from ..transcription import to_alto, to_hocr, to_page

        if fmt in ("hocr", "alto", "page"):
            uri = page.image.uri.rsplit("/", 1)[-1] if page.image and page.image.uri else None
            size = dict(image_width=page.image.width, image_height=page.image.height, image_uri=uri)
            return {"hocr": to_hocr, "alto": to_alto, "page": to_page}[fmt](t, **size)
        if fmt == "transcription":
            return t.model_dump_json(indent=1)
        if fmt == "json":
            return json.dumps(t.docling, ensure_ascii=False, indent=2) if t.docling is not None else None
        if document is not None:
            from ..document import to_markdown, to_text

            return to_markdown(document, self.furniture) if fmt == "md" else to_text(document, self.furniture)
        return t.text

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        from .base import page_of

        out = get_datafolder(self.output_folder)
        for doc in data:
            page = page_of(doc)
            t = page.transcriptions.get(self.transcription)
            if t is None:
                self.stat_update("no_transcription")
                yield doc
                continue
            document = None
            if t.docling is not None and {"md", "txt"} & set(self.formats):
                from ..document import load_docling

                document = load_docling(t)
            stem = self.path(page)
            for fmt in self.formats:
                with self.track_time(fmt):
                    content = self.render(page, t, fmt, document)
                if content is None:
                    self.stat_update("no_document")
                    continue
                if document is None and fmt in ("md", "txt"):
                    self.stat_update(f"{fmt}_from_page_text")
                data_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
                with out.open(f"{stem}.{PAGE_FILE_EXTENSIONS[fmt]}", "wb") as f:
                    f.write(data_bytes)
                self.stat_update(fmt)
            yield doc


# ------------------------------------------------------------------ item texts

def item_text_row(self, doc) -> dict:
    """datatrove adapter for ``ItemTexts`` documents: ``id`` (item), ``text`` and the metadata columns."""
    return {"id": doc.id, "text": doc.text, **{k: v for k, v in doc.metadata.items()}}


class ItemTextJsonlWriter(JsonlWriter):
    """``ItemTexts`` documents as JSONL, one folder per variant (``<variant>/<rank>.jsonl.gz``)."""

    name = "📚 item texts (jsonl)"

    def __init__(self, output_folder: DataFolderLike, output_filename: str = "${variant}/${rank}.jsonl.gz", **kwargs):
        super().__init__(output_folder, output_filename, adapter=item_text_row, **kwargs)


class ItemTextFilesWriter(PipelineStep):
    """``ItemTexts`` documents as files: ``<output_folder>/<variant>/<item_id>.<txt|md>``."""

    type = "💽 - WRITER"
    name = "📚 item text files"

    def __init__(self, output_folder: DataFolderLike):
        super().__init__()
        self.output_folder = output_folder

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        out = get_datafolder(self.output_folder)
        for doc in data:
            variant = doc.metadata.get("variant", "text")
            ext = "md" if doc.metadata.get("format") == "text/markdown" else "txt"
            with out.open(f"{variant}/{doc.id}.{ext}", "wb") as f:
                f.write(doc.text.encode("utf-8"))
            self.stat_update(variant)
            yield doc
