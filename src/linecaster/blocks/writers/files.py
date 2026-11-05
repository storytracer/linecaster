"""Per-page files: ``PageFileWriter``, one file per page and format (hOCR, ALTO, PAGE, txt, md, HTML, DocLang,
DoclingDocument JSON, Transcription JSON, layout plots), ``<item_id>/<page_id><suffix>.<ext>`` or flat.
"""
from __future__ import annotations

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep

#: format -> file extension
PAGE_FILE_EXTENSIONS = {
    "hocr": "hocr",                       # hOCR 1.2 (linecaster's serialiser)
    "alto": "alto.xml",                   # ALTO 4.4
    "page": "page.xml",                   # PAGE-XML 2019
    "txt": "txt",                         # the DoclingDocument's text export, else the page text
    "md": "md",                           # the DoclingDocument's Markdown export, else the page text
    "html": "html",                       # the DoclingDocument's HTML export
    "doclang": "doclang.xml",             # the DoclingDocument's DocLang export
    "json": "json",                       # the DoclingDocument (from Composer)
    "transcription": "transcription.json",  # the Transcription as linecaster JSON
    "plot": "layout.jpg",                 # the page image with regions and lines drawn in (linecaster.images.plots)
}
#: depth of hocr/alto/page: ``word`` (lines and words; linecaster has no glyph level) or ``line`` (text per line)
DETAILS = ("word", "line")
DOCUMENT_FORMATS = ("md", "txt", "html", "doclang", "json")


class PageFileWriter(PipelineStep):
    """One file per page and format: ``<output_folder>/<item_id>/<page_id><suffix>.<ext>`` (any fsspec
    folder: local, ``s3://``, ``hf://buckets/...``). Pages pass through, so writers can be chained.

    * ``hocr``, ``alto``, ``page``: linecaster's serialisers (``to_hocr``/``to_alto``/``to_page``) at the
      page image's size; ``detail="line"`` leaves the words out (text per line);
    * ``md``, ``txt``, ``html``, ``doclang``, ``json``: the DoclingDocument's exports
      (``linecaster.formats.docling.export``) when the transcription has one (``Composer``;
      ``furniture`` keeps page headers and footers in md, txt and html; ``dividers`` puts ``---``
      between layout regions in md); without one, md and txt fall back to ``Transcription.text`` (lines
      in reading order, tables as Markdown/HTML) and the others are skipped (counted as ``no_document``);
    * ``transcription``: the ``Transcription`` itself as JSON;
    * ``plot``: a JPEG of the page image with the regions and lines drawn in (``linecaster.images.plots``).

    ``bucket_by_item=False`` writes ``<page_id><suffix>.<ext>`` flat, as squiddleocr names its files (with
    ``suffix=".paddle"``); pages without ``item_id`` are always written flat. ``text_fallback=False`` writes md and
    txt only from a document, so a page without one gets no files of the document formats."""

    type = "💽 - WRITER"
    name = "🗂️ page files"

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("hocr", "alto", "page", "txt"),
                 transcription: str = "ocr", suffix: str = "", furniture: bool = False, bucket_by_item: bool = True,
                 detail: str = "word", dividers: bool = False, text_fallback: bool = True):
        super().__init__()
        unknown = set(formats) - set(PAGE_FILE_EXTENSIONS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {sorted(PAGE_FILE_EXTENSIONS)}")
        if detail not in DETAILS:
            raise ValueError(f"unknown detail {detail!r}; choose from {', '.join(DETAILS)}")
        self.output_folder, self.formats, self.transcription = output_folder, tuple(formats), transcription
        self.suffix, self.furniture, self.bucket_by_item = suffix, furniture, bucket_by_item
        self.detail, self.dividers, self.text_fallback = detail, dividers, text_fallback

    def path(self, page) -> str:
        stem = f"{page.page_id}{self.suffix}"
        return f"{page.item_id}/{stem}" if self.bucket_by_item and page.item_id else stem

    @staticmethod
    def wordless(t):
        """A copy of ``t`` without words (``detail="line"``)."""
        return t.model_copy(update={"lines": [ln.model_copy(update={"words": []}) for ln in t.lines]})

    def render(self, page, t, fmt: str, document=None, doc=None) -> str | bytes | None:
        from ...formats import to_alto, to_hocr, to_page

        if fmt in ("hocr", "alto", "page"):
            uri = page.image.uri.rsplit("/", 1)[-1] if page.image and page.image.uri else None
            size = dict(image_width=page.image.width, image_height=page.image.height, image_uri=uri)
            src = self.wordless(t) if self.detail == "line" else t
            return {"hocr": to_hocr, "alto": to_alto, "page": to_page}[fmt](src, **size)
        if fmt == "transcription":
            return t.model_dump_json(indent=1)
        if fmt == "plot":
            from ...images.plots import plot_layout
            from ..base.page import decode_rgb, image_bytes

            return plot_layout(decode_rgb(image_bytes(doc)), t)
        if fmt == "json":
            from ...formats.docling import to_json

            return to_json(t.docling) if t.docling is not None else None
        if document is not None:
            from ...formats.docling import REGION_MAP_KEY, export

            region_of = t.extra.get(REGION_MAP_KEY) if self.dividers else None
            return export(document, fmt, self.furniture, region_of)
        return t.text if fmt in ("md", "txt") and self.text_fallback else None

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        from ..base.page import page_of

        out = get_datafolder(self.output_folder)
        for doc in data:
            page = page_of(doc)
            t = page.transcriptions.get(self.transcription)
            if t is None:
                self.stat_update("no_transcription")
                yield doc
                continue
            document = None
            if t.docling is not None and {"md", "txt", "html", "doclang"} & set(self.formats):
                from ...formats.docling import load_docling

                document = load_docling(t)
            stem = self.path(page)
            for fmt in self.formats:
                with self.track_time(fmt):
                    content = self.render(page, t, fmt, document, doc)
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

