"""Per-page files: ``PageFileWriter``, one file per page and format (hOCR, ALTO, PAGE, txt, md, HTML, the document's
JSON, Transcription JSON, layout plots), ``<item_id>/<page_id><suffix>.<ext>`` or flat.
"""
from __future__ import annotations

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep

from linecaster.catalog.registry import DEFAULT_POLICY_REF, rendering_policy
from linecaster.errors import PipelineConfigError
from linecaster.core.contract import Contract, Contracted, parts

#: format -> file extension
PAGE_FILE_EXTENSIONS = {
    "hocr": "hocr",                       # hOCR 1.2 (linecaster's serializer)
    "alto": "alto.xml",                   # ALTO 4.4
    "page": "page.xml",                   # PAGE-XML 2019
    "txt": "txt",                         # the document's text, else the page's literal text
    "md": "md",                           # the document's Markdown, else the page's literal text
    "html": "html",                       # the document's HTML
    "json": "json",                       # the document (linecaster.document/1)
    "transcription": "transcription.json",  # the Transcription as linecaster JSON (as page records hold it)
    "plot": "layout.jpg",                 # the page image with regions and lines drawn in (linecaster.images.plots)
}
#: depth of hocr/alto/page: ``word`` (lines and words; linecaster has no glyph level) or ``line`` (text per line)
DETAILS = ("word", "line")
DOCUMENT_FORMATS = ("md", "txt", "html", "json")
#: the part each format is written from (md and txt: the document when there is one, else the page text)
FORMAT_PARTS = {"hocr": "lines", "alto": "lines", "page": "lines", "txt": "text", "md": "text", "html": "document",
                "json": "document", "transcription": None, "plot": "image"}


class PageFileWriter(Contracted, PipelineStep):
    """Writes one file per page and format: ALTO, PAGE-XML, hOCR, text, Markdown, HTML, JSON and more.

    Files go to ``<output_folder>/<item_id>/<page_id><suffix>.<ext>`` (any fsspec folder: local, ``s3://``,
    ``hf://buckets/...``). It reads the parts its formats are written from (``FORMAT_PARTS``: ``lines`` for hOCR,
    ALTO and PAGE, ``text`` for md and txt, ``document`` for HTML and JSON, ``image`` for plots) and adds
    nothing; pages pass through, so writers can be chained. A page without the transcription is counted
    (``no_transcription``) and passed on; with ``skip_failed``, so is a page an earlier component failed on
    (``skipped_failed``): its files would hold what the components before the failure made of it, while the
    ``RejectWriter`` lists it and the page records keep it with its errors.

    * ``hocr``, ``alto``, ``page``: linecaster's serializers (``to_hocr``/``to_alto``/``to_page``) at the
      page image's size; ``detail="line"`` leaves the words out (text per line);
    * ``md``, ``txt``, ``html``, ``json``: the document's serializations (``linecaster.document.export``), written
      by the transcription ``strategy`` (``literal`` by default: as read; ``linecaster.document.strategy``): the
      document a ``DocumentComposer`` composed for the page (``doc.metadata["document"]``), else the transcription rendered
      with the default options (``linecaster.document.build_document``) when it has regions or paragraphs; for a
      page of lines only, md and txt fall back to its literal text (``linecaster.text.page.page_text``: lines in
      reading order, tables as Markdown/HTML, the regions the policy puts nowhere left out; counted as
      ``<format>_from_page_text``; only a strategy of character rules applies to it, others write none) and the
      others are skipped (counted as ``no_document``);
    * ``transcription``: the ``Transcription`` itself as JSON;
    * ``plot``: a JPEG of the page image with the regions and lines drawn in (``linecaster.images.plots``).

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the files go to.
        formats: the formats to write, keys of ``PAGE_FILE_EXTENSIONS``; an unknown one is a
            ``PipelineConfigError``.
        transcription: the transcription written.
        suffix: added to each file's stem, before the extension (``".paddle"``: ``<page_id>.paddle.md``).
        furniture: keep page headers and footers in md, txt and html.
        bucket_by_item: one folder per item; ``False`` writes ``<page_id><suffix>.<ext>`` flat, in one folder.
            Pages without ``item_id`` are always written flat.
        detail: ``word`` (lines and words) or ``line`` (text per line) for hOCR, ALTO and PAGE.
        dividers: put ``---`` between layout regions in md.
        text_fallback: a page without a document (lines only) still gets md and txt from ``Transcription.text``;
            ``False`` writes them only from a document (the component then reads ``document``).
        skip_failed: write no files for a page that carries errors (``doc.metadata["errors"]``); the default writes
            them as for any page.
        policy: the rendering policy (a catalog ``policy``) of every file it writes: the layers of a rendered
            document, the regions left out of the page files.
        strategy: the transcription strategy md, txt, html and json are written by: ``literal`` (the default), a
            catalog strategy, or normalizations joined by ``+``.
    """

    type = "💽 - WRITER"
    name = "🗂️ page files"
    kind = "writer"
    docs_args = {"output_folder": "out/files"}

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("hocr", "alto", "page", "txt"),
                 transcription: str = "ocr_new", suffix: str = "", furniture: bool = False, bucket_by_item: bool = True,
                 detail: str = "word", dividers: bool = False, text_fallback: bool = True, skip_failed: bool = False,
                 policy: str = DEFAULT_POLICY_REF, strategy: str = "literal"):
        super().__init__()
        rendering_policy(policy)                      # an unknown policy fails at construction
        from linecaster.catalog.registry import catalog
        from linecaster.errors import CatalogError

        try:
            catalog().strategy(strategy, use="output")
        except CatalogError as e:
            raise PipelineConfigError(f"strategy {strategy!r}: {e.args[0]}") from None
        self.strategy = strategy
        unknown = set(formats) - set(PAGE_FILE_EXTENSIONS)
        if unknown:
            raise PipelineConfigError(f"unknown formats {sorted(unknown)}; choose from {sorted(PAGE_FILE_EXTENSIONS)}")
        if detail not in DETAILS:
            raise PipelineConfigError(f"unknown detail {detail!r}; choose from {', '.join(DETAILS)}")
        self.output_folder, self.formats, self.transcription = output_folder, tuple(formats), transcription
        self.suffix, self.furniture, self.bucket_by_item = suffix, furniture, bucket_by_item
        self.detail, self.dividers, self.text_fallback = detail, dividers, text_fallback
        self.skip_failed, self.policy = skip_failed, policy

    def contract(self) -> Contract:
        """It reads what its formats are written from (``FORMAT_PARTS``)."""
        names = {FORMAT_PARTS[f] for f in self.formats} - {None}
        if not self.text_fallback and names & {"text"} and {"md", "txt"} & set(self.formats):
            names = (names - {"text"}) | {"document"}
        return Contract(unit="page", kind=self.kind, reads=parts(names, self.transcription))

    def path(self, page) -> str:
        stem = f"{page.page_id}{self.suffix}"
        return f"{page.item_id}/{stem}" if self.bucket_by_item and page.item_id else stem

    @staticmethod
    def wordless(t):
        """A copy of ``t`` whose readings have no words (``detail="line"``)."""
        return t.model_copy(update={"lines": [
            ln if ln.reading is None else ln.model_copy(update={"reading": ln.reading.model_copy(update={"words": []})})
            for ln in t.lines]})

    def composed(self, doc, page, t):
        """The page's document: the ``DocumentComposer``'s for this transcription, else ``t`` rendered (``build_document``,
        default options) when it has regions or paragraphs; None for a page of lines only."""
        from linecaster.document import COMPOSED_KEY, DOCUMENT_KEY, build_document, load_document

        meta = doc.metadata
        if meta.get(COMPOSED_KEY) == self.transcription and meta.get(DOCUMENT_KEY) is not None:
            return load_document(meta[DOCUMENT_KEY])
        if not (t.regions or t.paragraphs):
            return None
        w, h = (page.image.width, page.image.height) if page.image else (None, None)
        return build_document(t, name=page.page_id, width=w, height=h, policy=rendering_policy(self.policy))

    def render(self, page, t, fmt: str, document=None, doc=None) -> str | bytes | None:
        from linecaster.formats import to_alto, to_hocr, to_page

        if fmt in ("hocr", "alto", "page"):
            uri = page.image.uri.rsplit("/", 1)[-1] if page.image and page.image.uri else None
            size = dict(image_width=page.image.width, image_height=page.image.height, image_uri=uri)
            src = self.wordless(t) if self.detail == "line" else t
            return {"hocr": to_hocr, "alto": to_alto, "page": to_page}[fmt](src, **size,
                                                                             policy=rendering_policy(self.policy))
        if fmt == "transcription":
            return t.model_dump_json(indent=1, by_alias=True, exclude_defaults=True)
        if fmt == "plot":
            from linecaster.images.plots import plot_layout
            from linecaster.core.page import decode_rgb, image_bytes

            return plot_layout(decode_rgb(image_bytes(doc)), t)
        if document is not None:
            from linecaster.document import export
            from linecaster.document.strategy import apply

            written = apply(document, self.strategy) if self.strategy != "literal" else document
            return export(written, fmt, self.furniture, self.dividers, rendering_policy(self.policy).markdown)
        if fmt == "json":
            return None
        if fmt in ("md", "txt") and self.text_fallback:
            from linecaster.catalog.registry import catalog

            s = catalog().strategy(self.strategy, use="output")
            if not all(n.text_rule for n in s.normalizations):
                return None                    # its structure rules need a document: a page of lines has none
            from linecaster.text.page import page_text

            return s.text(page_text(t, rendering_policy(self.policy)))
        return None

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.io import get_datafolder

        from linecaster.core.page import failed, page_of

        out = get_datafolder(self.output_folder)
        for doc in data:
            if self.skip_failed and failed(doc):
                self.stat_update("skipped_failed")
                yield doc
                continue
            page = page_of(doc)
            t = page.transcriptions.get(self.transcription)
            if t is None:
                self.stat_update("no_transcription")
                yield doc
                continue
            document = self.composed(doc, page, t) if set(DOCUMENT_FORMATS) & set(self.formats) else None
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

