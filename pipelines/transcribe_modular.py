# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray (HF Jobs leave it out)
#     "linecaster[ray,pybookget]",
#     # manifests (IIIF, METS) and http(s) images (--manifests); direct, so its source applies
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
# pybookget = { url = "https://github.com/storytracer/pybookget/archive/449bcc50b25aaa8d4ad4ea00bc78c9554e136af7.tar.gz" }
# linecaster-kraken = { path = "../engines/kraken", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix and the
# # line prefetch (storytracer/linecaster#1)
# kraken = { git = "https://github.com/storytracer/kraken", rev = "48eecb78" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
r"""The modular pipeline: smaller models, picked step by step from the catalog's presets (`linecaster models`):
text lines and a line recogniser, optionally a layout model first (without one the page is one region) and table
and formula models after; then Unicode NFC, typography and page composition. Page records in OUT/pages; with
--files per-page files in the --formats asked for (--naming squiddleocr: flat `<page>.paddle.<ext>`, as
squiddleocr names them), with --item-texts one text per item in each text version.

    uv run pipelines/transcribe_modular.py IMAGES OUT --lines pp-ocrv6-medium-det --recognition kraken-ppocrv6-medium
    uv run pipelines/transcribe_modular.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognition tesseract-best-latin --tables slanet-plus --formulas pp-formulanet-plus-l
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --backend served                        # a server in the task
    ... --files OUT/files --formats md,txt,json --naming squiddleocr --furniture    # squiddleocr's per-page files
    uv run pipelines/transcribe_modular.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --commit <sha> --tasks 64

``linecaster.runtime.run`` has the options every pipeline shares; ``--recipe`` fills the slots.
"""
from linecaster.blocks.binding.texts import ItemTexts
from linecaster.blocks.composition.composer import Composer
from linecaster.blocks.composition.typographer import Typographer
from linecaster.blocks.layout.detector import LayoutDetector
from linecaster.blocks.layout.single_region import SingleRegionLayout
from linecaster.blocks.lines.assigner import LineAssigner
from linecaster.blocks.lines.detector import LineDetector
from linecaster.blocks.recognition.recognizers import FormulaRecognizer, LineRecognizer, TableRecognizer
from linecaster.blocks.text.unicode import UnicodeNormalizer
from linecaster.blocks.writers.files import PAGE_FILE_EXTENSIONS, PageFileWriter
from linecaster.blocks.writers.items import ItemTextWriter
from linecaster.runtime import run

STEPS = ("layout", "lines", "recognition", "tables", "formulas")
#: --naming: how per-page files are named
NAMING = {"item": {}, "squiddleocr": {"suffix": ".paddle", "bucket_by_item": False}}


def options(ap):
    ap.add_argument("--layout", help="layout preset (none: the page is one region)")
    ap.add_argument("--lines", help="line detection preset (needed)")
    ap.add_argument("--recognition", help="line recognition preset (needed)")
    ap.add_argument("--tables", help="table preset (needs --layout)")
    ap.add_argument("--formulas", help="formula preset (needs --layout; without, formulas are read as text)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. recognition.batch_size=4; repeatable")
    ap.add_argument("--text", choices=["lines", "reflow"], default="lines", help="document text")
    ap.add_argument("--files", metavar="DIR", help="per-page files here, one per format (--formats, --naming)")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json",
                    help=f"formats for --files, comma-separated: {', '.join(PAGE_FILE_EXTENSIONS)}")
    ap.add_argument("--naming", choices=list(NAMING), default="item",
                    help="--files names: item, <item>/<page>.<ext>; squiddleocr, <page>.paddle.<ext> in one folder")
    ap.add_argument("--furniture", action="store_true",
                    help="--files: keep page headers and footers in md, txt and html (as squiddleocr does)")
    ap.add_argument("--item-texts", metavar="DIR", help="per-item texts: <version>/<item>.txt|.md and JSONL")
    ap.add_argument("--window", type=int, default=32, help="pages in flight per served step")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL",
                    help="a different server for one step")


def chosen(a) -> dict[str, str]:
    picks = {"layout": a.layout, "lines": a.lines, "recognition": a.recognition, "tables": a.tables,
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
    missing = [f"--{s}" for s in ("lines", "recognition") if s not in picks]
    if missing:
        raise SystemExit(f"modular: pick {' and '.join(missing)} (`linecaster models` lists the presets)")
    if not a.layout and (a.tables or a.formulas):
        raise SystemExit("modular: --tables and --formulas work on layout regions; pick --layout too")
    if a.item_texts and a.tasks > 1:
        raise SystemExit("modular: --item-texts needs every page of an item in one task; with several tasks write "
                         "--item-shards N and run pipelines/bind.py on OUT/pages afterwards")
    formats = tuple(a.formats.split(","))
    unknown = sorted(set(formats) - set(PAGE_FILE_EXTENSIONS))
    if unknown:
        raise SystemExit(f"modular: unknown --formats {unknown}; choose from {', '.join(PAGE_FILE_EXTENSIONS)}")
    b, servers = run.engines(a, models(a), script, a.window)
    for kv in a.endpoint_for:
        step, url = kv.split("=", 1)
        b[step] = Served(url, model=step, max_window=a.window)
    return [
        run.reader(a),
        LayoutDetector(b["layout"]) if "layout" in b else SingleRegionLayout(),
        LineDetector(b["lines"]),
        LineAssigner(formulas_separately="formulas" in b),
        LineRecognizer(b["recognition"]),
        UnicodeNormalizer(),                       # kraken writes decomposed text; the as-written layer is NFC
        *([TableRecognizer(b["tables"])] if "tables" in b else []),
        *([FormulaRecognizer(b["formulas"])] if "formulas" in b else []),
        Typographer(),
        Composer(text=a.text),
        *([PageFileWriter(a.files, formats=formats, furniture=a.furniture, **NAMING[a.naming])] if a.files else []),
        run.pages(a),
        # after the page writers: ItemTexts consumes the pages and emits one document per item and version
        *([ItemTexts(), ItemTextWriter(a.item_texts, format="files"), ItemTextWriter(a.item_texts)]
          if a.item_texts else []),
        *servers,                                 # last: lives until every page is written
    ]


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "transcribe_modular.v1"
SLOTS = {"layout": "layout", "lines": "lines", "recognition": "recognition", "tables": "tables", "formulas": "formulas"}

if __name__ == "__main__":
    run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
