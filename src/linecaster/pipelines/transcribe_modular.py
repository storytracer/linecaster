r"""The modular pipeline: smaller models, picked step by step from the catalog's presets (`linecaster models`):
a layout (a layout model, or `single-region` for the page as one region), text lines and a line recognizer,
optionally table and formula models after; then Unicode NFC and the rule-based steps, each a preset too: typography (--typography),
recomposition (--recomposition; without one the page stays as laid out) and page composition (--composition). Page
records in OUT/pages; with --files per-page files in the --formats asked for (--naming squiddleocr: flat
`<page>.paddle.<ext>`, as squiddleocr names them), with --item-texts one text per item in each text variant (an
item stage: the item recomposed as one, normalized by --normalization). The script's environment has PaddleX and
Tesseract; kraken's presets (the squiddle recipe's recognition) run in an environment that adds kraken (squiddleocr's
`squiddle.py`, or a script of your own that runs this shape), or here with --backend served --endpoint against a server
started from one.

    uv run pipelines/transcribe_modular.py IMAGES OUT --layout single-region --lines pp-ocrv6-medium-det \
        --recognition paddlex-ppocrv6-medium
    uv run pipelines/transcribe_modular.py IMAGES OUT --recipe squiddle --endpoint URL   # every slot from the recipe
    ... --typography ratios --recomposition unicode-recomposition --composition docling-composition
    ... --item-texts OUT/texts --recomposition unicode-recomposition --normalization latin-historic
    uv run pipelines/transcribe_modular.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognition tesseract-best-latin --tables slanet-plus --formulas pp-formulanet-plus-l
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --set composition.sections=true         # also for the rule-based steps
    ... --backend served                        # a server in the task
    ... --files OUT/files --formats md,txt,json --naming squiddleocr --furniture    # squiddleocr's per-page files
    uv run pipelines/transcribe_modular.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --namespace NS --commit <sha> --tasks 64

``linecaster.runtime.run`` has the options every pipeline shares; ``--recipe`` fills the slots.
"""
from ..blocks.binding import Binder
from ..blocks.composites.modular import ModularTranscriber
from ..blocks.composition import Composer, Recomposer, Typographer
from ..blocks.layout.detector import LayoutDetector
from ..blocks.lines.detector import LineDetector
from ..blocks.recognition.recognizers import FormulaRecognizer, LineRecognizer, TableRecognizer
from ..blocks.text import CharacterNormalizer, UnicodeNormalizer
from ..blocks.writers.files import PAGE_FILE_EXTENSIONS, PageFileWriter
from ..blocks.writers.items import ItemTextWriter
from ..errors import PipelineConfigError
from ..runtime import run

STEPS = ("layout", "lines", "recognition", "tables", "formulas")
#: the rule-based steps, each a slot (a preset; none: the step does not run)
RULE_STEPS = ("typography", "recomposition", "normalization", "composition")
#: --naming: how per-page files are named
NAMING = {"item": {}, "squiddleocr": {"suffix": ".paddle", "bucket_by_item": False}}


def options(ap):
    ap.add_argument("--layout", help="layout preset (needed; single-region: the page is one region)")
    ap.add_argument("--lines", help="line detection preset (needed)")
    ap.add_argument("--recognition", help="line recognition preset (needed)")
    ap.add_argument("--tables", help="table preset (reads the layout's table regions)")
    ap.add_argument("--formulas", help="formula preset (reads the layout's formula regions; without, they are read "
                                       "as text)")
    ap.add_argument("--typography", help="typography preset: headings and their levels, initials (e.g. ratios)")
    ap.add_argument("--recomposition", help="recomposition preset: the text regions as running text, in paragraphs "
                                            "(e.g. unicode-recomposition; none: the page stays as laid out)")
    ap.add_argument("--normalization", help="character normalization preset of the readable item texts "
                                            "(--item-texts; e.g. latin-historic)")
    ap.add_argument("--composition", help="page composition preset: the page's document, for md, txt, html, doclang "
                                          "and json (e.g. docling-composition)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. recognition.batch_size=4; repeatable")
    ap.add_argument("--files", metavar="DIR", help="per-page files here, one per format (--formats, --naming); none "
                                                   "for a page a block failed on (OUT/rejects lists it)")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json",
                    help=f"formats for --files, comma-separated: {', '.join(PAGE_FILE_EXTENSIONS)}")
    ap.add_argument("--naming", choices=list(NAMING), default="item",
                    help="--files names: item, <item>/<page>.<ext>; squiddleocr, <page>.paddle.<ext> in one folder")
    ap.add_argument("--furniture", action="store_true",
                    help="--files: keep page headers and footers in md, txt and html (as squiddleocr does)")
    ap.add_argument("--item-texts", metavar="DIR",
                    help="per-item texts: <variant>/<item>.txt|.md and <variant>/<rank>.jsonl.gz (needs "
                         "--recomposition and --normalization)")
    ap.add_argument("--window", type=int, default=32, help="pages in flight per served step")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL",
                    help="a different server for one step")


def chosen(a) -> dict[str, str]:
    picks = {"layout": a.layout, "lines": a.lines, "recognition": a.recognition, "tables": a.tables,
             "formulas": a.formulas}
    return {step: preset for step, preset in picks.items() if preset}


def sets(a) -> dict[str, dict]:
    """``--set`` by step: the model steps picked and the rule-based ones."""
    return run.overrides(a.set, steps=[*chosen(a), *(s for s in RULE_STEPS if getattr(a, s))])


def models(a) -> list[dict]:
    over = sets(a)
    return [{"name": step, "preset": preset, **({"overrides": over[step]} if step in over else {})}
            for step, preset in chosen(a).items()]


def pipeline(a, script: str) -> list:
    from ..backends import Served

    picks = chosen(a)
    missing = [f"--{s}" for s in ("layout", "lines", "recognition") if s not in picks]
    if missing:
        raise PipelineConfigError(f"modular: pick {' and '.join(missing)} (`linecaster models` lists the presets; "
                                  "--layout single-region reads the page as one region)")
    if a.item_texts and not (a.recomposition and a.normalization):
        raise PipelineConfigError("modular: --item-texts makes the readable texts from the item's recomposition and "
                                  "normalization; pick --recomposition and --normalization")
    formats = tuple(a.formats.split(","))
    unknown = sorted(set(formats) - set(PAGE_FILE_EXTENSIONS))
    if unknown:
        raise PipelineConfigError(f"modular: unknown --formats {unknown}; choose from "
                                  f"{', '.join(PAGE_FILE_EXTENSIONS)}")
    over = sets(a)
    b, servers = run.engines(a, models(a), script, a.window)
    for kv in a.endpoint_for:
        step, url = kv.split("=", 1)
        b[step] = Served(url, model=step, max_window=a.window)
    return [
        run.reader(a),
        # layout (or the page as one region) -> lines -> line assignment -> line recognition
        ModularTranscriber(lines=LineDetector(b["lines"]), recognition=LineRecognizer(b["recognition"]),
                           layout=LayoutDetector(b["layout"]), formulas_separately="formulas" in b),
        UnicodeNormalizer(),                       # kraken writes decomposed text; the as-written layer is NFC
        *([TableRecognizer(b["tables"])] if "tables" in b else []),
        *([FormulaRecognizer(b["formulas"])] if "formulas" in b else []),
        *([Typographer(a.typography, options=over.get("typography"))] if a.typography else []),
        *([Recomposer(a.recomposition, options=over.get("recomposition"))] if a.recomposition else []),
        *([Composer(a.composition, options=over.get("composition"))] if a.composition else []),
        # no files for a page a block failed on: OUT/rejects lists it, the page records keep it with its errors
        *([PageFileWriter(a.files, formats=formats, furniture=a.furniture, skip_failed=True, **NAMING[a.naming])]
          if a.files else []),
        run.pages(a),
        # after the page writers, the item stage: the Binder gathers each item's pages into an item record; with
        # several tasks the builder cuts here (the pages in item shards, then a stage over whole items)
        *([Binder(), Recomposer(a.recomposition, unit="item", options=over.get("recomposition")),
           CharacterNormalizer(a.normalization, unit="item", options=over.get("normalization")),
           ItemTextWriter(a.item_texts, format="files"), ItemTextWriter(a.item_texts)] if a.item_texts else []),
        *servers,                                 # last: lives until every page is written
    ]


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "transcribe_modular.v1"
SLOTS = {"layout": "layout", "lines": "lines", "recognition": "recognition", "tables": "tables", "formulas": "formulas",
         "typography": "typography", "recomposition": "recomposition", "normalization": "normalization",
         "composition": "composition"}
