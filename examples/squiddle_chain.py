"""The squiddle combination as a linecaster pipeline: PP-DocLayoutV3 layout, PP-OCRv6 line detection on
the whole page, lines assigned to regions, kraken's PP-OCRv6 recogniser, PaddleX's table structure for
table regions (filled with the recognised lines), then the retyper (Typography) and document assembly
(AssembleDocument; with --exports also per-page md/txt/json as squiddleocr writes them).

    # in-process (the parity reference), in the engine environment:
    envs/kraken-paddlex/.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend in-process
    # through saturate against `linecaster serve` (the integration):
    envs/kraken-paddlex/.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend served --endpoint http://127.0.0.1:8100/v1
"""
from __future__ import annotations

import argparse

from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import InProcess, Served
from linecaster.blocks.document import AssembleDocument, PageExportsWriter, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.writers import PageJsonlWriter

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
             text: str = "lines"):
    b = backends(kind, endpoint, endpoints)
    return [
        ImageFolderReader(images),
        LayoutStep(b["layout"], transcription),
        LinesStep(b["lines"], transcription),
        AssignLinesToRegions(transcription),
        RecognitionStep(b["recognition"], transcription),
        *([TablesStep(b["tables"], transcription)] if tables else []),
        Typography(transcription),
        AssembleDocument(transcription, text=text),
        *([PageExportsWriter(exports, formats=("md", "txt", "json"), suffix=".paddle", furniture=True,
                             transcription=transcription)] if exports else []),
        PageJsonlWriter(out, output_filename="${rank}.jsonl", compression=None),
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
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL", help="a different server for one step")
    a = ap.parse_args()
    eps = dict(e.split("=", 1) for e in a.endpoint_for)
    LocalPipelineExecutor(pipeline(a.images, a.out, a.backend, a.endpoint, tables=not a.no_tables, endpoints=eps,
                                   exports=a.exports, text=a.text),
                          tasks=a.tasks, workers=a.tasks,
                          logging_dir=a.logs or f"{a.out}/logs").run()
