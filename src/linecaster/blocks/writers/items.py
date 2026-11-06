"""Item writers, from item records (``linecaster.blocks.base.item``): the item's document (``ItemDocumentWriter``)
and its text variants (``ItemTextWriter``: JSON Lines, one folder per variant, or files,
``<variant>/<item_id>.txt|.md``)."""
from __future__ import annotations

from collections.abc import Callable

from datatrove.data import Document
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from datatrove.pipeline.writers import JsonlWriter

from ...errors import PipelineConfigError
from ...formats.docling import EXPORT_FORMATS, export
from ...text.variants import VARIANTS, variants
from ..base.contract import Contract, Contracted, Part, parts
from ..base.item import ITEM_KEY, item_pages


class ItemDocumentWriter(Contracted, PipelineStep):
    """Write the item documents of an item-level ``Composer`` as ``<item id><suffix>.<ext>`` (with ``by_format``
    in a folder per format, ``<format>/<item id><suffix>.<ext>``): ``md``, ``txt``, ``html``, ``doclang``, ``json``
    (``linecaster.formats.docling.export``). ``furniture`` keeps page headers and footers in md, txt and html;
    ``dividers`` puts ``---`` between the items of consecutive layout regions in md. Item records pass through."""

    type = "💽 - WRITER"
    name = "📝 item documents"
    unit, role = "item", "writer"

    def contract(self) -> Contract:
        return Contract(unit=self.unit, role=self.role, reads=frozenset({Part("document")}))

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("md", "txt"), suffix: str = "",
                 furniture: bool = False, dividers: bool = False, by_format: bool = False):
        super().__init__()
        unknown = set(formats) - set(EXPORT_FORMATS)
        if unknown:
            raise PipelineConfigError(f"unknown formats {sorted(unknown)}; choose from {', '.join(EXPORT_FORMATS)}")
        self.folder, self.formats, self.suffix = get_datafolder(output_folder), tuple(formats), suffix
        self.furniture, self.dividers, self.by_format = furniture, dividers, by_format

    def run(self, data, rank: int = 0, world_size: int = 1):
        from docling_core.types.doc import DoclingDocument

        for doc in data:
            meta = doc.metadata
            if "docling" not in meta:
                self.stat_update("no_document")
                yield doc
                continue
            with self.track_time():
                d = DoclingDocument.model_validate(meta["docling"])
                region_of = meta.get("region_of") if self.dividers else None
                for fmt in self.formats:
                    content = meta["docling"] if fmt == "json" else d
                    name = f"{meta['item_id']}{self.suffix}.{EXPORT_FORMATS[fmt]}"
                    with self.folder.open(f"{fmt}/{name}" if self.by_format else name, "wt", encoding="utf-8") as f:
                        f.write(export(content, fmt, self.furniture, region_of))
                    self.stat_update(fmt)
            yield doc


#: ``ItemTextWriter``'s formats
ITEM_TEXT_FORMATS = ("jsonl", "files")


def item_text_row(self, doc) -> dict:
    """datatrove adapter for one variant of an item: ``id`` (item), ``text`` and the metadata columns."""
    return {"id": doc.id, "text": doc.text, **doc.metadata}


class ItemTextWriter(Contracted, JsonlWriter):
    """The text variants of each item record (``linecaster.text.variants``): ``verbatim_txt`` from its pages' lines
    as laid out (pages joined with a form feed), ``readable_txt`` and ``readable_md`` from the paragraphs of the
    item's recomposition (``Recomposer(unit="item")``), normalized (``CharacterNormalizer``), body only.

    ``format="jsonl"``: JSON Lines, one folder per variant (``<variant>/<rank>.jsonl.gz``; ``output_filename`` and
    datatrove's ``JsonlWriter`` options apply), a row per item: ``id`` (the item), ``text`` and ``item_id``,
    ``variant``, ``fidelity``, ``flow``, ``scope``, ``format``, ``page_ids``, ``pages`` (count) and ``token_count``
    when a ``token_counter`` is given (e.g. a tiktoken encoding's ``encode`` length); ``format="files"``: one file
    each, ``<output_folder>/<variant>/<item_id>.<txt|md>``. Item records pass through."""

    unit, role = "item", "writer"

    def contract(self) -> Contract:
        names = {"lines"} if "verbatim_txt" in self.variants else set()
        if any(v != "verbatim_txt" for v in self.variants):
            names |= {"paragraphs", "normalized"}
        return Contract(unit=self.unit, role=self.role, reads=parts(sorted(names), self.transcription))

    def __init__(self, output_folder: DataFolderLike, format: str = "jsonl",
                 variants: tuple[str, ...] = tuple(VARIANTS), transcription: str = "ocr_new",
                 token_counter: Callable[[str], int] | None = None,
                 output_filename: str = "${variant}/${rank}.jsonl.gz", **kwargs):
        if format not in ITEM_TEXT_FORMATS:
            raise PipelineConfigError(f"unknown format {format!r}; choose from {', '.join(ITEM_TEXT_FORMATS)}")
        unknown = set(variants) - set(VARIANTS)
        if unknown:
            raise PipelineConfigError(f"unknown variants {sorted(unknown)}; known: {sorted(VARIANTS)}")
        self.name = f"📚 item texts ({format})"     # before the base __init__, which names the stats
        super().__init__(output_folder, output_filename, adapter=item_text_row, **kwargs)
        self.format, self.variants, self.transcription, self.token_counter = \
            format, tuple(variants), transcription, token_counter

    def texts(self, doc: Document) -> list[Document]:
        """One datatrove document per variant of the item record ``doc``: ``text`` the variant, the metadata the
        row's columns."""
        pages = item_pages(doc)
        item = doc.metadata[ITEM_KEY]["item_id"]
        ids = [p.page_id for p in pages]
        texts = variants([p.transcription(self.transcription) for p in pages], ids)
        out = []
        for variant in self.variants:
            fidelity, flow, scope, fmt = VARIANTS[variant]
            meta = {"item_id": item, "variant": variant, "fidelity": fidelity, "flow": flow, "scope": scope,
                    "format": fmt, "page_ids": ids, "pages": len(pages)}
            if self.token_counter is not None:
                meta["token_count"] = self.token_counter(texts[variant])
            out.append(Document(text=texts[variant], id=item, metadata=meta))
        return out

    def run(self, data, rank: int = 0, world_size: int = 1):
        with self:
            for doc in data:
                if ITEM_KEY not in doc.metadata:
                    self.stat_update("no_item")
                    yield doc
                    continue
                with self.track_time():
                    for text in self.texts(doc):
                        variant = text.metadata["variant"]
                        if self.format == "jsonl":
                            self.write(text, rank)
                        else:
                            ext = "md" if text.metadata["format"] == "text/markdown" else "txt"
                            with self.output_folder.open(f"{variant}/{text.id}.{ext}", "wb") as f:
                                f.write(text.text.encode("utf-8"))
                        self.stat_update(variant)
                        self.stat_update(f"{variant}_chars", value=len(text.text))
                self.stat_update("items")
                yield doc
