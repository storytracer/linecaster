"""Item writers: ``BindItem``'s documents (``ItemExportsWriter``) and ``ItemTexts``' texts
(``ItemTextJsonlWriter``: one folder per variant; ``ItemTextFilesWriter``: ``<variant>/<item_id>.txt|.md``)."""
from __future__ import annotations

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep
from datatrove.pipeline.writers import JsonlWriter

from ...formats.docling import EXPORT_FORMATS, export


class ItemExportsWriter(PipelineStep):
    """Write ``BindItem``'s documents as ``<item id><suffix>.<ext>``: ``md``, ``txt``,
    ``html``, ``doclang``, ``json`` (``linecaster.formats.docling.export``). ``furniture`` keeps page headers
    and footers in md, txt and html; ``dividers`` puts ``---`` between the items of consecutive layout
    regions in md. Documents pass through."""

    type = "💽 - WRITER"
    name = "📝 item exports"

    def __init__(self, output_folder: DataFolderLike, formats: tuple[str, ...] = ("md", "txt"), suffix: str = "",
                 furniture: bool = False, dividers: bool = False):
        super().__init__()
        unknown = set(formats) - set(EXPORT_FORMATS)
        if unknown:
            raise ValueError(f"unknown formats {sorted(unknown)}; choose from {', '.join(EXPORT_FORMATS)}")
        self.folder, self.formats, self.suffix = get_datafolder(output_folder), tuple(formats), suffix
        self.furniture, self.dividers = furniture, dividers

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
                    with self.folder.open(f"{meta['item_id']}{self.suffix}.{EXPORT_FORMATS[fmt]}", "wt",
                                          encoding="utf-8") as f:
                        f.write(export(content, fmt, self.furniture, region_of))
                    self.stat_update(fmt)
            yield doc


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
