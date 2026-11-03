"""The squiddle combination as a linecaster pipeline: PP-DocLayoutV3 layout, PP-OCRv6 line detection on
the whole page, lines assigned to regions, kraken's PP-OCRv6 recogniser, PaddleX's table structure for
table regions (filled with the recognised lines), then the retyper (Typography) and document assembly
(AssembleDocument). Outputs: page rows (OUT); with --files per-page hOCR/ALTO/PAGE/txt/md/json
(``<item>/<page>.<ext>``); with --exports per-page md/txt/json named as squiddleocr writes them; with
--texts one text per item in the three variants (verbatim_txt, readable_txt, readable_md).

    # in-process (the parity reference), in the engine environment:
    envs/kraken-paddlex/.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend in-process
    # through saturate against `linecaster serve` (the integration):
    envs/kraken-paddlex/.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend served --endpoint http://127.0.0.1:8100/v1
    # everything at once, books = image subfolders:
    ... examples/squiddle_chain.py BOOKS/ OUT --item-from-parent --files OUT/files --texts OUT/texts
"""
from __future__ import annotations

import argparse

from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import InProcess, Served
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.writers import ItemTextFilesWriter, ItemTextJsonlWriter, PageFilesWriter, PageJsonlWriter

ENGINES = {
    "layout": ("linecaster_paddlex:PaddleLayoutModel", {"model_name": "PP-DocLayoutV3"}),
    "lines": ("linecaster_paddlex:PaddleLineModel", {"model_name": "PP-OCRv6_medium_det"}),
    "recognition": ("linecaster_kraken:KrakenRecognitionModel", {"model": "medium", "batch_size": 8}),
    "tables": ("linecaster_paddlex:PaddleTableModel", {}),
}


def backends(kind: str, endpoint: str | None, endpoints: dict | None = None):
    if kind == "in-process":
        return {step: InProcess(spec, **kw) for step, (spec, kw) in ENGINES.items()}
    return {step: Served((endpoints or {}).get(step, endpoint), model=step) for step in ENGINES}


def pipeline(images: str, out: str, kind: str = "in-process", endpoint: str | None = None, transcription: str = "ocr",
             tables: bool = True, endpoints: dict | None = None, exports: str | None = None,
             text: str = "lines", files: str | None = None, formats=("hocr", "alto", "page", "txt", "md", "json"),
             texts: str | None = None, item_from_parent: bool = False):
    b = backends(kind, endpoint, endpoints)
    return [
        ImageFolderReader(images, item_from_parent=item_from_parent),
        LayoutStep(b["layout"], transcription),
        LinesStep(b["lines"], transcription),
        AssignLinesToRegions(transcription),
        RecognitionStep(b["recognition"], transcription),
        *([TablesStep(b["tables"], transcription)] if tables else []),
        Typography(transcription),
        AssembleDocument(transcription, text=text),
        *([PageFilesWriter(files, formats=tuple(formats), transcription=transcription)] if files else []),
        *([PageFilesWriter(exports, formats=("md", "txt", "json"), suffix=".paddle", furniture=True,
                           bucket_by_item=False, transcription=transcription)] if exports else []),
        PageJsonlWriter(out, output_filename="${rank}.jsonl", compression=None),
        # after the page writers: ItemTexts consumes the pages and emits one document per item and variant
        *([ItemTexts(transcription), ItemTextFilesWriter(texts),
           ItemTextJsonlWriter(texts, output_filename="${variant}/${rank}.jsonl", compression=None)] if texts else []),
    ]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images"); ap.add_argument("out")
    ap.add_argument("--backend", choices=["in-process", "served"], default="in-process")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8100/v1")
    ap.add_argument("--tasks", type=int, default=1); ap.add_argument("--logs", default=None)
    ap.add_argument("--no-tables", action="store_true", help="skip the tables step")
    ap.add_argument("--exports", default=None, metavar="DIR",
                    help="also write <page>.paddle.md/.txt/.json (squiddleocr's --text lines --furniture) here")
    ap.add_argument("--text", choices=["lines", "reflow"], default="lines", help="document text mode")
    ap.add_argument("--files", default=None, metavar="DIR", help="per-page files <item>/<page>.<ext> here")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json", help="formats for --files")
    ap.add_argument("--texts", default=None, metavar="DIR",
                    help="per-item texts here: <variant>/<item>.txt|.md and <variant>/<rank>.jsonl")
    ap.add_argument("--item-from-parent", action="store_true", help="item id = the image's parent folder")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL", help="a different server for one step")
    a = ap.parse_args()
    eps = dict(e.split("=", 1) for e in a.endpoint_for)
    LocalPipelineExecutor(pipeline(a.images, a.out, a.backend, a.endpoint, tables=not a.no_tables, endpoints=eps,
                                   exports=a.exports, text=a.text, files=a.files, formats=a.formats.split(","),
                                   texts=a.texts, item_from_parent=a.item_from_parent),
                          tasks=a.tasks, workers=a.tasks,
                          logging_dir=a.logs or f"{a.out}/logs").run()
