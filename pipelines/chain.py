# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # IIIF manifests and http(s) images (--manifests); direct, so its source applies
#     "pybookget",
#     "linecaster-kraken",
#     "linecaster-paddlex",
#     "linecaster-tesseract",
#     # direct, so the fork in [tool.uv.sources] applies (sources only apply to a script's own dependencies)
#     "kraken",
#     # s3:// image folders (e.g. BHL's public bucket: FSSPEC_S3_ANON=true)
#     "s3fs",
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
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/dd0ce49bd835be78fbbca4dd0ba470033454efad.tar.gz" }
# linecaster-kraken = { path = "../engines/kraken", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix and the
# # line prefetch (storytracer/linecaster#1)
# kraken = { git = "https://github.com/storytracer/kraken", rev = "48eecb78" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
r"""A chain of smaller models, picked step by step from the catalogue's presets (`linecaster models`): text
lines and a line recogniser, optionally a layout model first (without one the page is one region) and table
and formula models after; then Unicode NFC, typography and document assembly. Page rows in OUT/rows; with
--files per-page hOCR/ALTO/PAGE/txt/md/json, with --exports the per-page md/txt/json squiddleocr writes, with
--texts one text per item in each text version.

    uv run pipelines/chain.py IMAGES OUT --lines pp-ocrv6-medium-det --recognizer kraken-ppocrv6-medium
    uv run pipelines/chain.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognizer tesseract-best-latin --tables slanet-plus --formulas pp-formulanet-plus-l
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --backend served                        # a server in the task
    uv run pipelines/chain.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/chain.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --commit <sha> --tasks 64

``linecaster.run`` has the options every pipeline shares; ``--recipe`` fills the slots.
"""
from linecaster import run
from linecaster.blocks.document import AssembleDocument, Typography
from linecaster.blocks.layout import SingleRegionLayout
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import FormulasStep, LayoutStep, LinesStep, RecognitionStep, TablesStep
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.unicode import NormalizeUnicode
from linecaster.blocks.writers import ItemTextFilesWriter, ItemTextJsonlWriter, PageFilesWriter

STEPS = ("layout", "lines", "recognition", "tables", "formulas")


def options(ap):
    ap.add_argument("--layout", help="layout preset (none: the page is one region)")
    ap.add_argument("--lines", help="line detection preset (needed)")
    ap.add_argument("--recognizer", help="line recogniser preset (needed)")
    ap.add_argument("--tables", help="table preset (needs --layout)")
    ap.add_argument("--formulas", help="formula preset (needs --layout; without, formulas are read as text)")
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


def chosen(a) -> dict[str, str]:
    picks = {"layout": a.layout, "lines": a.lines, "recognition": a.recognizer, "tables": a.tables,
             "formulas": a.formulas}
    return {step: preset for step, preset in picks.items() if preset}


def models(a) -> list[dict]:
    picks = chosen(a)
    sets = run.overrides(a.set, steps=list(picks))
    return [{"name": step, "preset": preset, **({"overrides": sets[step]} if step in sets else {})}
            for step, preset in picks.items()]


def pipeline(a, script: str) -> list:
    from linecaster.backends import Served

    picks = chosen(a)
    missing = [f"--{'recognizer' if s == 'recognition' else s}" for s in ("lines", "recognition") if s not in picks]
    if missing:
        raise SystemExit(f"chain: pick {' and '.join(missing)} (`linecaster models` lists the presets)")
    if not a.layout and (a.tables or a.formulas):
        raise SystemExit("chain: --tables and --formulas work on layout regions; pick --layout too")
    if a.texts and a.tasks > 1:
        raise SystemExit("chain: --texts needs every page of an item in one task; with several tasks write "
                         "--item-shards N and run pipelines/items.py on OUT/rows afterwards")
    b, servers = run.engines(a, models(a), script, a.window)
    for kv in a.endpoint_for:
        step, url = kv.split("=", 1)
        b[step] = Served(url, model=step, max_window=a.window)
    return [
        run.reader(a),
        LayoutStep(b["layout"]) if "layout" in b else SingleRegionLayout(),
        LinesStep(b["lines"]),
        AssignLinesToRegions(formulas_separately="formulas" in b),
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


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "chain.v1"
SLOTS = {"layout": "layout", "lines": "lines", "recognition": "recognizer", "tables": "tables", "formulas": "formulas"}

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
