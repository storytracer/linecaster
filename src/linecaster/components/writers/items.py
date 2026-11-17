"""Item writers, from item records (``linecaster.core.item``): the item's document written by transcription
strategies, a file per item and text (``ItemDocumentWriter``: ``<strategy>/<item_id>.<ext>``), or as JSON Lines, a row
per item and text (``ItemTextWriter``). A text is ``<strategy>:<format>``: ``literal`` or a strategy of the catalog
(``linecaster.catalog``: ``Catalog.strategy``; normalizations joined by ``+`` too), in ``md``, ``txt``, ``html`` or
``json`` (``linecaster.document.export``). Nothing is normalized unless a text names a strategy."""
from __future__ import annotations

from collections.abc import Callable

from datatrove.data import Document
from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from datatrove.pipeline.writers import JsonlWriter

from linecaster.catalog.registry import DEFAULT_POLICY_REF, catalog, rendering_policy
from linecaster.errors import CatalogError, PipelineConfigError
from linecaster.document import DOCUMENT_KEY, EXPORT_FORMATS, export, load_document
from linecaster.document.strategy import apply
from linecaster.core.contract import Contract, Contracted, Part
from linecaster.core.item import ITEM_KEY, item_pages

#: what a run writes unless it names texts: the document as the builder made it
DEFAULT_TEXTS = ("literal:json",)


def parse_texts(texts) -> tuple[tuple[str, str], ...]:
    """Text specs (``<strategy>:<format>``, a sequence or comma-separated) as (strategy, format) pairs, each checked:
    a known output strategy, a known format; anything else is a ``PipelineConfigError``."""
    specs = [x.strip() for x in (texts.split(",") if isinstance(texts, str) else texts) if x and x.strip()]
    out = []
    for spec in specs:
        strategy, sep, fmt = spec.rpartition(":")
        if not sep or not strategy or fmt not in EXPORT_FORMATS:
            raise PipelineConfigError(f"text {spec!r}: <strategy>:<format>, the format one of "
                                      f"{', '.join(EXPORT_FORMATS)} (e.g. literal:txt, latin-historic+flow:md)")
        try:
            catalog().strategy(strategy, use="output")
        except CatalogError as e:
            raise PipelineConfigError(f"text {spec!r}: {e.args[0]}") from None
        out.append((strategy, fmt))
    return tuple(out)


class _Written:
    """An item's document written by each strategy at most once."""

    def __init__(self, doc):
        self.doc, self.by = doc, {}

    def __call__(self, strategy: str):
        if strategy not in self.by:
            self.by[strategy] = apply(self.doc, strategy)
        return self.by[strategy]


class ItemDocumentWriter(Contracted, PipelineStep):
    """Writes the document of each item record by transcription strategies, one file per item and text.

    It reads the item's ``document`` (an item-level ``DocumentComposer``'s, ``doc.metadata["document"]``: the literal
    document), writes it by each text's strategy (``linecaster.document.strategy``) in the text's format
    (``linecaster.document.export``) to ``<strategy>/<item id><suffix>.<ext>``; an item record without a document is
    counted (``no_document``). Item records pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the documents go to.
        texts: the texts, ``<strategy>:<format>`` (default the literal document as JSON); an unknown strategy or
            format is a ``PipelineConfigError``.
        suffix: added to each file's stem, before the extension.
        furniture: keep page headers and footers in md, txt and html.
        dividers: put ``---`` between the components of consecutive layout regions in md.
        policy: the rendering policy whose Markdown rules the md is written by.
    """

    type = "💽 - WRITER"
    name = "📝 item documents"
    unit, kind = "item", "writer"
    docs_args = {"output_folder": "out/documents"}

    def contract(self) -> Contract:
        return Contract(unit=self.unit, kind=self.kind, reads=frozenset({Part("document")}))

    def __init__(self, output_folder: DataFolderLike, texts=DEFAULT_TEXTS, suffix: str = "", furniture: bool = False,
                 dividers: bool = False, policy: str = DEFAULT_POLICY_REF):
        super().__init__()
        self.texts = parse_texts(texts)
        self.folder, self.suffix = get_datafolder(output_folder), suffix
        self.furniture, self.dividers, self.policy = furniture, dividers, policy
        rendering_policy(policy)                      # an unknown policy fails at construction

    def run(self, data, rank: int = 0, world_size: int = 1):
        rules = rendering_policy(self.policy).markdown
        for doc in data:
            meta = doc.metadata
            if DOCUMENT_KEY not in meta:
                self.stat_update("no_document")
                yield doc
                continue
            with self.track_time():
                written = _Written(load_document(meta[DOCUMENT_KEY]))
                for strategy, fmt in self.texts:
                    name = f"{strategy}/{meta['item_id']}{self.suffix}.{EXPORT_FORMATS[fmt]}"
                    with self.folder.open(name, "wt", encoding="utf-8") as f:
                        f.write(export(written(strategy), fmt, self.furniture, self.dividers, rules))
                    self.stat_update(f"{strategy}:{fmt}")
            yield doc


def item_text_row(self, doc) -> dict:
    """datatrove adapter for one text of an item: ``id`` (item), ``text`` and the metadata columns."""
    return {"id": doc.id, "text": doc.text, **doc.metadata}


def item_texts(doc: Document, texts=(("literal", "txt"),), token_counter=None, policy=None) -> list[Document]:
    """One datatrove document per text of the item record ``doc`` (``(strategy, format)`` pairs, ``parse_texts``):
    ``text`` the item's document written by the strategy in the format, the metadata the columns ``ItemTextWriter``
    writes (item id, strategy, its hash and normalizations, format, page ids, page count, and the token count with a
    ``token_counter``). For a downstream project writing the texts in a format of its own."""
    pages = item_pages(doc)
    item = doc.metadata[ITEM_KEY]["item_id"]
    ids = [p.page_id for p in pages]
    rules = (policy or rendering_policy(DEFAULT_POLICY_REF)).markdown
    written = _Written(load_document(doc.metadata[DOCUMENT_KEY]))
    out = []
    for strategy, fmt in texts:
        s = catalog().strategy(strategy, use="output")
        text = export(written(strategy), fmt, rules=rules)
        meta = {"item_id": item, "spec": f"{strategy}:{fmt}", "strategy": s.id, "strategy_sha256": s.sha256,
                "normalizations": [n.id for n in s.normalizations], "format": fmt, "page_ids": ids,
                "pages": len(pages)}
        if token_counter is not None:
            meta["token_count"] = token_counter(text)
        out.append(Document(text=text, id=item, metadata=meta))
    return out


class ItemTextWriter(Contracted, JsonlWriter):
    """Writes the texts of each item record as JSON Lines, a row per item and text.

    Each text (``<strategy>:<format>``) is the item's document (an item-level ``DocumentComposer``'s) written by the strategy
    in the format (``item_texts``); a row holds ``id`` (the item), ``text`` and ``item_id``, ``strategy``,
    ``strategy_sha256``, ``normalizations``, ``format``, ``page_ids``, ``pages`` (count) and ``token_count`` with a
    ``token_counter``, in ``<strategy>.<format>/<rank>.jsonl.gz``. A stream entry that is no item record, or one
    without a document, is counted (``no_item``, ``no_document``). Item records pass through.

    Args:
        output_folder: the folder (local path, fsspec URI or ``DataFolder``) the texts go to.
        texts: the texts, ``<strategy>:<format>``; an unknown strategy or format is a ``PipelineConfigError``.
        token_counter: counts a text's tokens for ``token_count`` (e.g. the length of a tiktoken encoding's
            ``encode``); default: no count.
        policy: the rendering policy whose Markdown rules the md texts are written by.
        output_filename: the JSON Lines file name, datatrove's template.
        **kwargs: datatrove's ``JsonlWriter`` arguments (``compression``, ``max_file_size``, ...).
    """

    unit, kind = "item", "writer"
    name = "📚 item texts"
    docs_args = {"output_folder": "out/texts", "texts": ("literal:txt",)}

    def contract(self) -> Contract:
        return Contract(unit=self.unit, kind=self.kind, reads=frozenset({Part("document")}))

    def __init__(self, output_folder: DataFolderLike, texts=("literal:txt",),
                 token_counter: Callable[[str], int] | None = None,
                 output_filename: str = "${strategy}.${format}/${rank}.jsonl.gz", policy: str = DEFAULT_POLICY_REF,
                 **kwargs):
        self.texts = parse_texts(texts)
        if not self.texts:
            raise PipelineConfigError("ItemTextWriter: name the texts to write (<strategy>:<format>)")
        super().__init__(output_folder, output_filename, adapter=item_text_row, **kwargs)
        self.token_counter, self.policy = token_counter, policy
        rendering_policy(policy)                      # an unknown policy fails at construction

    def run(self, data, rank: int = 0, world_size: int = 1):
        with self:
            for doc in data:
                if ITEM_KEY not in doc.metadata:
                    self.stat_update("no_item")
                    yield doc
                    continue
                if DOCUMENT_KEY not in doc.metadata:
                    self.stat_update("no_document")
                    yield doc
                    continue
                with self.track_time():
                    for text in item_texts(doc, self.texts, self.token_counter, rendering_policy(self.policy)):
                        self.write(text, rank)
                        self.stat_update(text.metadata["spec"])
                        self.stat_update(f"{text.metadata['spec']}_chars", value=len(text.text))
                self.stat_update("items")
                yield doc
