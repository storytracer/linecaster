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
    """Writes the document of each item record, one file per format: Markdown, text, HTML, DocLang, JSON.

    It reads the item's ``document`` (an item-level ``Composer``'s) and writes ``<item id><suffix>.<ext>``
    (``linecaster.formats.docling.export``); an item record without a document is counted (``no_document``). Item
    records pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the documents go to.
        formats: the formats to write: ``md``, ``txt``, ``html``, ``doclang``, ``json``; an unknown one is a
            ``PipelineConfigError``.
        suffix: added to each file's stem, before the extension.
        furniture: keep page headers and footers in md, txt and html.
        dividers: put ``---`` between the items of consecutive layout regions in md.
        by_format: one folder per format, ``<format>/<item id><suffix>.<ext>``.
    """

    type = "💽 - WRITER"
    name = "📝 item documents"
    unit, role = "item", "writer"
    docs_args = {"output_folder": "out/documents"}

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


def item_texts(doc: Document, variants_: tuple[str, ...] = tuple(VARIANTS), transcription: str = "ocr_new",
               token_counter=None) -> list[Document]:
    """One datatrove document per text variant of the item record ``doc``: ``text`` the variant, the metadata the
    columns ``ItemTextWriter`` writes (item id, variant, its dimensions and format, page ids, page count, and the
    token count with a ``token_counter``). For a derivative writing the texts in a format of its own."""
    pages = item_pages(doc)
    item = doc.metadata[ITEM_KEY]["item_id"]
    ids = [p.page_id for p in pages]
    texts = variants([p.transcription(transcription) for p in pages], ids)
    out = []
    for variant in variants_:
        fidelity, flow, scope, fmt = VARIANTS[variant]
        meta = {"item_id": item, "variant": variant, "fidelity": fidelity, "flow": flow, "scope": scope,
                "format": fmt, "page_ids": ids, "pages": len(pages)}
        if token_counter is not None:
            meta["token_count"] = token_counter(texts[variant])
        out.append(Document(text=texts[variant], id=item, metadata=meta))
    return out


class ItemTextWriter(Contracted, JsonlWriter):
    """Writes the text variants of each item record as JSON Lines or as files.

    The variants (``linecaster.text.variants``): ``verbatim_txt`` from its pages' lines as laid out (pages joined
    with a form feed; reads ``lines``), ``readable_txt`` and ``readable_md`` from the paragraphs of the item's
    recomposition (``Recomposer(unit="item")``), normalized (``CharacterNormalizer``), body only (reads
    ``paragraphs`` and ``normalized``). A JSON Lines row per item and variant holds ``id`` (the item), ``text`` and
    ``item_id``, ``variant``, ``fidelity``, ``flow``, ``scope``, ``format``, ``page_ids``, ``pages`` (count) and
    ``token_count`` with a ``token_counter``. A stream entry that is no item record is counted (``no_item``). Item
    records pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the texts go to.
        format: ``jsonl`` (one folder per variant, ``<variant>/<rank>.jsonl.gz``) or ``files`` (one file per item
            and variant, ``<variant>/<item_id>.<txt|md>``).
        variants: the variants to write, names of ``VARIANTS``; an unknown one is a ``PipelineConfigError``.
        transcription: the transcription the texts are made from.
        token_counter: counts a text's tokens for ``token_count`` (e.g. the length of a tiktoken encoding's
            ``encode``); default: no count.
        output_filename: the JSON Lines file name (``jsonl``), datatrove's template.
        **kwargs: datatrove's ``JsonlWriter`` arguments (``compression``, ``max_file_size``, ...).
    """

    unit, role = "item", "writer"
    docs_args = {"output_folder": "out/texts"}

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
        """One datatrove document per variant of the item record ``doc`` (``item_texts``)."""
        return item_texts(doc, self.variants, self.transcription, self.token_counter)

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
