# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray]",
#     "linecaster-kraken",
#     "linecaster-paddlex",
#     "linecaster-tesseract",
#     # direct, so the fork in [tool.uv.sources] applies (sources only apply to a script's own dependencies)
#     "kraken",
#     # PaddleX pins OpenCV's GUI build; this stub swaps in the headless build of the same version
#     "opencv-contrib-python",
# ]
#
# [tool.uv]
# # the versions squiddleocr's goldens were recorded with (numerics: recognition, ONNX Runtime, CUDA, decoding);
# # the same list in every script (tests/test_scripts.py)
# constraint-dependencies = [
#     "lightning==2.6.6",
#     "onnxruntime-gpu==1.29.0",
#     "pillow==12.3.0",
#     "transformers==5.12.1",
#     "tokenizers==0.22.2",
#     "nvidia-cublas==13.1.1.3",
#     "nvidia-cuda-nvrtc==13.0.88",
#     "nvidia-cuda-runtime==13.0.96",
#     "nvidia-cudnn-cu13==9.24.0.43",
#     "nvidia-cufft==12.0.0.61",
#     "nvidia-curand==10.4.0.35",
#     "scipy==1.15.3",
#     "scikit-image==0.25.2",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-kraken = { path = "../engines/kraken", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix
# kraken = { git = "https://github.com/storytracer/kraken", rev = "3d235ee8" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""A chain of smaller models: layout (PP-DocLayoutV3), text lines (PP-OCRv6 detection on the whole page),
lines assigned to their regions, a line recogniser (kraken, PaddleX or Tesseract), Unicode NFC, table
structure (PaddleX, cells filled with the recognised lines), formulas as LaTeX, typography, document
assembly. Page rows in OUT/rows; with --files per-page hOCR/ALTO/PAGE/txt/md/json, with --exports the
per-page md/txt/json squiddleocr writes, with --texts one text per item in each text version.

    uv run recipes/chain.py IMAGES OUT                                   # in-process, this machine
    uv run recipes/chain.py IMAGES OUT --recognizer tesseract --rec-model script/Latin
    uv run recipes/chain.py IMAGES OUT --backend served                  # a server in the task
    uv run recipes/chain.py serve                                        # linecaster serve, these models
    uv run recipes/chain.py ray start --head --num-gpus 8                # then --on ray --tasks 64
    uv run recipes/chain.py IMAGES OUT --on hf-jobs --commit <sha> --tasks 64

The defaults are the squiddle combination (kraken PP-OCRv6 medium, batch 8: the settings squiddleocr's
goldens were recorded with). ``linecaster.run`` has the options every recipe shares.
"""
from linecaster import run
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import FormulasStep, LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import ItemTextFilesWriter, ItemTextJsonlWriter, PageFilesWriter

RECOGNIZERS = {   # engine class and the option --rec-model sets
    "kraken": ("linecaster_kraken:KrakenRecognitionModel", "model"),
    "paddlex": ("linecaster_paddlex:PaddleRecognitionModel", "model_name"),
    "tesseract": ("linecaster_tesseract:TesseractRecognitionModel", "lang"),
}


def options(ap):
    ap.add_argument("--recognizer", choices=list(RECOGNIZERS), default="kraken")
    ap.add_argument("--rec-model", help="kraken: tiny, small, medium (default) or a file; PaddleX: "
                                        "PP-OCRv6_{tiny,small,medium}_rec; Tesseract: a language or script")
    ap.add_argument("--tessdata", choices=["best", "fast"], default="best")
    ap.add_argument("--batch-size", type=int, default=8, help="lines per forward pass (kraken, PaddleX)")
    ap.add_argument("--layout-model", default="PP-DocLayoutV3")
    ap.add_argument("--det-model", default="PP-OCRv6_medium_det")
    ap.add_argument("--no-tables", action="store_true")
    ap.add_argument("--no-formulas", action="store_true", help="formula regions are read as text")
    ap.add_argument("--text", choices=["lines", "reflow"], default="lines", help="document text")
    ap.add_argument("--files", metavar="DIR", help="per-page files <item>/<page>.<ext> here")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json", help="formats for --files")
    ap.add_argument("--exports", metavar="DIR", help="<page>.paddle.md/.txt/.json as squiddleocr writes them")
    ap.add_argument("--texts", metavar="DIR", help="per-item texts: <version>/<item>.txt|.md and JSONL")
    ap.add_argument("--window", type=int, default=32, help="pages in flight per served step")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL",
                    help="a different server for one step")


def models(a) -> list[dict]:
    spec, key = RECOGNIZERS[a.recognizer]
    rec = {"tesseract": {"data": a.tessdata}}.get(a.recognizer, {"batch_size": a.batch_size})
    if a.rec_model or a.recognizer == "kraken":
        rec = {key: a.rec_model or "medium", **rec}
    return [
        {"name": "layout", "spec": "linecaster_paddlex:PaddleLayoutModel", "kwargs": {"model_name": a.layout_model}},
        {"name": "lines", "spec": "linecaster_paddlex:PaddleLineModel", "kwargs": {"model_name": a.det_model}},
        {"name": "recognition", "spec": spec, "kwargs": rec},
        *([] if a.no_tables else [{"name": "tables", "spec": "linecaster_paddlex:PaddleTableModel", "kwargs": {}}]),
        *([] if a.no_formulas else [{"name": "formulas", "spec": "linecaster_paddlex:PaddleFormulaModel", "kwargs": {}}]),
    ]


def pipeline(a, script: str) -> list:
    from linecaster.backends import Served

    b, servers = run.engines(a, models(a), script, a.window)
    for kv in a.endpoint_for:
        step, url = kv.split("=", 1)
        b[step] = Served(url, model=step, max_window=a.window)
    return [
        run.reader(a),
        LayoutStep(b["layout"]),
        LinesStep(b["lines"]),
        AssignLinesToRegions(formulas_separately=not a.no_formulas),
        RecognitionStep(b["recognition"]),
        NormalizeUnicode(),                       # kraken writes decomposed text; the as-written layer is NFC
        *([] if a.no_tables else [TablesStep(b["tables"])]),
        *([] if a.no_formulas else [FormulasStep(b["formulas"])]),
        Typography(),
        AssembleDocument(text=a.text),
        *([PageFilesWriter(a.files, formats=tuple(a.formats.split(",")))] if a.files else []),
        *([PageFilesWriter(a.exports, formats=("md", "txt", "json"), suffix=".paddle", furniture=True,
                           bucket_by_item=False)] if a.exports else []),
        run.rows(a),
        # after the page writers: ItemTexts consumes the pages and emits one document per item and version
        *([ItemTexts(), ItemTextFilesWriter(a.texts),
           ItemTextJsonlWriter(a.texts, output_filename="${variant}/${rank}.jsonl.gz")] if a.texts else []),
        *servers,                                 # last: lives until every page is written
    ]


if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline)
