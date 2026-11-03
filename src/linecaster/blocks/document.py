"""Post-recognition blocks without a model: the retyper (``Typography``), document assembly
(``AssembleDocument``) and per-page export files (``PageExportsWriter``).

In squiddleocr's order: ... recognition -> tables -> ``Typography`` -> ``AssembleDocument`` -> writers.
``Typography`` changes regions and lines (``linecaster.retyper``); ``AssembleDocument`` fills the
transcription's ``docling`` part from them (``linecaster.document``); ``PageExportsWriter`` writes
``<page id><suffix>.md`` / ``.txt`` / ``.json`` (the DoclingDocument) per page.
"""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..document import build_docling, docling_dict, load_docling, to_markdown, to_text
from ..page import Page
from ..retyper import retype
from .base import PageStep, page_of


class Typography(PageStep):
    """squiddleocr's retyper on the named transcription: heading levels from type size, headline
    splits, drop capitals, uncertain page numbers removed (see ``linecaster.retyper``)."""

    name = "typography (retyper)"

    def __init__(self, transcription: str = "ocr"):
        super().__init__()
        self.transcription = transcription

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is None:
            return page
        stats = retype(t)
        for key in ("levelled", "demoted", "split", "drop_capitals", "numbers_dropped"):
            if getattr(stats, key):
                self.stat_update(key, value=getattr(stats, key))
        return page


class AssembleDocument(PageStep):
    """Build the named transcription's ``docling`` part from its regions, lines and tables
    (``linecaster.document.build_docling``; one document per page, named after the page id).
    ``text``: ``lines`` (one row per line) or ``reflow`` (paragraphs; squiddleocr's default)."""

    name = "assemble document"

    def __init__(self, transcription: str = "ocr", text: str = "lines", rtl: bool = False):
        super().__init__()
        from ..document import TEXT_MODES

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.transcription, self.text, self.rtl = transcription, text, rtl

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcriptions.get(self.transcription)
        if t is None:
            return page
        w = page.image.width if page.image else None
        h = page.image.height if page.image else None
        from ..reflow import Stats

        stats = Stats()
        t.docling = docling_dict(build_docling(t, name=page.page_id, width=w, height=h, text=self.text, rtl=self.rtl,
                                               stats=stats))
        self.stat_update("documents")
        if self.text == "reflow":
            for key in ("paragraphs", "continuations", "marks_removed", "marks_kept"):
                if getattr(stats, key):
                    self.stat_update(key, value=getattr(stats, key))
        return page


class PageExportsWriter(PipelineStep):
    """Write each page's document exports as files named ``<page id><suffix>.<ext>`` in
    ``output_folder``: ``md`` (Markdown), ``txt`` (text), ``json`` (the DoclingDocument). ``furniture``
    keeps page headers and footers in md and txt (squiddleocr's ``--furniture``). Pages pass through."""

    type = "💽 - WRITER"
    name = "📝 page exports"

    EXTENSIONS = {"md": "md", "txt": "txt", "json": "json"}

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("md", "txt"), suffix: str = "",
                 furniture: bool = False, transcription: str = "ocr"):
        super().__init__()
        unknown = set(formats) - set(self.EXTENSIONS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {sorted(self.EXTENSIONS)}")
        self.folder, self.formats, self.suffix = get_datafolder(output_folder), tuple(formats), suffix
        self.furniture, self.transcription = furniture, transcription

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            page = page_of(doc)
            t = page.transcriptions.get(self.transcription)
            if t is None or t.docling is None:
                self.stat_update("no_document")
                yield doc
                continue
            with self.track_time():
                d = load_docling(t)
                for fmt in self.formats:
                    if fmt == "md":
                        content = to_markdown(d, self.furniture)
                    elif fmt == "txt":
                        content = to_text(d, self.furniture)
                    else:
                        content = json.dumps(t.docling, ensure_ascii=False, indent=2)
                    with self.folder.open(f"{page.page_id}{self.suffix}.{self.EXTENSIONS[fmt]}", "wt", encoding="utf-8") as f:
                        f.write(content)
                    self.stat_update(fmt)
            yield doc
