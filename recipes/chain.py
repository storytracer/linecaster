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
"""A chain of smaller models, each step a catalogue preset: layout, text lines, lines assigned to their regions,
a line recogniser (kraken, PaddleX or Tesseract), Unicode NFC, table structure (cells filled with the
recognised lines), formulas as LaTeX, typography, document assembly. Page rows in OUT/rows; with --files
per-page hOCR/ALTO/PAGE/txt/md/json, with --exports the per-page md/txt/json squiddleocr writes, with --texts
one text per item in each text version.

    uv run recipes/chain.py IMAGES OUT                                   # in-process, this machine
    uv run recipes/chain.py IMAGES OUT --recognizer tesseract-best-latin
    uv run recipes/chain.py IMAGES OUT --set recognition.batch_size=4    # an option over the preset's
    uv run recipes/chain.py IMAGES OUT --backend served                  # a server in the task
    uv run recipes/chain.py serve                                        # linecaster serve, these presets
    uv run recipes/chain.py ray start --head --num-gpus 8                # then --on ray --tasks 64
    uv run recipes/chain.py IMAGES OUT --on hf-jobs --commit <sha> --tasks 64

`linecaster models` lists the presets for each step. The defaults are the squiddle combination, the settings
squiddleocr's goldens were recorded with. ``linecaster.run`` has the options every recipe shares.
"""
from linecaster import run
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import FormulasStep, LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import ItemTextFilesWriter, ItemTextJsonlWriter, PageFilesWriter

#: the preset for each step by default; "none" skips tables or formulas
DEFAULTS = {"layout": "pp-doclayoutv3", "lines": "pp-ocrv6-medium-det", "recognition": "kraken-ppocrv6-medium",
            "tables": "slanet-plus", "formulas": "pp-formulanet-plus-l"}


def options(ap):
    ap.add_argument("--layout", default=DEFAULTS["layout"], help="layout preset")
    ap.add_argument("--lines", default=DEFAULTS["lines"], help="line detection preset")
    ap.add_argument("--recognizer", default=DEFAULTS["recognition"], help="line recogniser preset")
    ap.add_argument("--tables", default=DEFAULTS["tables"], help="table preset, or none")
    ap.add_argument("--formulas", default=DEFAULTS["formulas"], help="formula preset, or none (read as text)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. recognition.batch_size=4; repeatable")
    ap.add_argument("--text", choices=["lines", "reflow"], default="lines", help="document text")
    ap.add_argument("--files", metavar="DIR", help="per-page files <item>/<page>.<ext> here")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json", help="formats for --files")
    ap.add_argument("--exports", metavar="DIR", help="<page>.paddle.md/.txt/.json as squiddleocr writes them")
    ap.add_argument("--texts", metavar="DIR", help="per-item texts: <version>/<item>.txt|.md and JSONL")
    ap.add_argument("--window", type=int, default=32, help="pages in flight per served step")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL",
                    help="a different server for one step")


def models(a) -> list[dict]:
    chosen = {"layout": a.layout, "lines": a.lines, "recognition": a.recognizer, "tables": a.tables,
              "formulas": a.formulas}
    sets = run.overrides(a.set, steps=[s for s, p in chosen.items() if p != "none"])
    return [{"name": step, "preset": preset, **({"overrides": sets[step]} if step in sets else {})}
            for step, preset in chosen.items() if preset != "none"]


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
        AssignLinesToRegions(formulas_separately=a.formulas != "none"),
        RecognitionStep(b["recognition"]),
        NormalizeUnicode(),                       # kraken writes decomposed text; the as-written layer is NFC
        *([TablesStep(b["tables"])] if "tables" in b else []),
        *([FormulasStep(b["formulas"])] if "formulas" in b else []),
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
