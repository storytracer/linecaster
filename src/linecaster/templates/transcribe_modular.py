r"""The modular pipeline: smaller models, picked step by step from the catalog's presets (`linecaster presets`):
a layout (a layout model, or `single-region` for the page as one region), text lines and a line recognizer,
optionally table and formula models after; then the rule-based steps, each a preset too: headings (--hierarchy),
paragraphs (--paragraphs; without one the page stays as laid out) and the page's document (--document). Page
records in OUT/pages; with --files per-page files in the --formats asked for (`<item>/<page><suffix>.<ext>`, or with
--naming flat `<page><suffix>.<ext>` in one folder; --suffix SUFFIX, e.g. `.paddle`), written literally or by a
--strategy; with --item-texts one file per item and --text (an item stage: the item recomposed and composed as one,
written by each text's transcription strategy). Nothing is normalized unless a strategy is named. The script's
environment has PaddleX and Tesseract; kraken's presets (the squiddle recipe's recognition) run in the recipe's own
script, recipes/squiddle.py (uv run launch.py squiddle IMAGES OUT), or here with --backend served --endpoint against a
server started from it.

    uv run pipelines/transcribe_modular.py IMAGES OUT --layout single-region --lines pp-ocrv6-medium-det \
        --recognition paddlex-ppocrv6-medium
    uv run recipes/squiddle.py IMAGES OUT                     # the recipe squiddle, in its own environment
    ... --hierarchy ratios --paragraphs unicode-paragraphs --document linked-document
    ... --item-texts OUT/texts --paragraphs unicode-paragraphs --document linked-document \
        --text literal:txt --text latin-historic+flow+unicode-marks:md     # texts by named strategies
    uv run pipelines/transcribe_modular.py IMAGES OUT --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
        --recognition tesseract-best-latin --tables slanet-plus
    ... --set recognition.batch_size=4          # an option over the preset's
    ... --set document.sections=true         # also for the rule-based steps
    ... --backend served                        # a server in the task
    ... --files OUT/files --formats md,txt,json --naming flat --suffix .paddle --furniture   # <page>.paddle.md, ...
    uv run pipelines/transcribe_modular.py serve --layout pp-doclayoutv3 ...    # linecaster serve with the presets named
    uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8        # then --on ray --tasks 64
    ... --on hf-jobs --namespace NS --commit <sha> --tasks 64

``linecaster.execution.run`` has the options every pipeline shares; ``--recipe`` fills the slots.
"""
from linecaster.components.items import ItemAssembler
from linecaster.components.composites.modular_transcriber import ModularTranscriber
from linecaster.components.document import DocumentComposer
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.layout.layout_detector import LayoutDetector
from linecaster.components.lines.line_detector import LineDetector
from linecaster.components.formulas.formula_recognizer import FormulaRecognizer
from linecaster.components.recognition.line_recognizer import LineRecognizer
from linecaster.components.tables.table_recognizer import TableRecognizer
from linecaster.components.writers.files import PAGE_FILE_EXTENSIONS, PageFileWriter
from linecaster.components.writers.items import ItemDocumentWriter, ItemTextWriter, parse_texts
from linecaster.errors import PipelineConfigError
from linecaster.execution import run

STEPS = ("layout", "lines", "recognition", "tables", "formulas")
#: the rule-based steps, each a slot (a preset; none: the step does not run)
RULE_SLOTS = ("hierarchy", "paragraphs", "document")
#: --naming: where per-page files go (a folder per item, or one folder)
NAMING = {"item": {"bucket_by_item": True}, "flat": {"bucket_by_item": False}}


def options(ap):
    ap.add_argument("--layout", help="layout preset (needed; single-region: the page is one region)")
    ap.add_argument("--lines", help="line detection preset (needed)")
    ap.add_argument("--recognition", help="line recognition preset (needed)")
    ap.add_argument("--tables", help="table preset (reads the layout's table regions)")
    ap.add_argument("--formulas", help="formula preset (reads the layout's formula regions; without, they are read "
                                       "as text)")
    ap.add_argument("--direction", choices=["horizontal-lr", "horizontal-rl", "vertical-rl", "vertical-lr"],
                    help="the pages' writing direction the line assigner orders rows in (default: each region's "
                         "recorded direction, else horizontal-lr); a layout model without learned order takes its "
                         "own option (--set layout.direction=...)")
    ap.add_argument("--hierarchy", help="hierarchy preset: headings and their levels, initials (e.g. ratios)")
    ap.add_argument("--paragraphs", help="paragraphs preset: the text regions as running text, in paragraphs "
                                            "(e.g. unicode-paragraphs; none: the page stays as laid out)")
    ap.add_argument("--document", help="document preset: the page's document, for md, txt, html and json "
                                          "(e.g. linked-document)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. recognition.batch_size=4; repeatable")
    ap.add_argument("--files", metavar="DIR", help="per-page files here, one per format (--formats, --naming, "
                                                   "--suffix); none for a page a component failed on (OUT/rejects lists it)")
    ap.add_argument("--formats", default="hocr,alto,page,txt,md,json",
                    help=f"formats for --files, comma-separated: {', '.join(PAGE_FILE_EXTENSIONS)}")
    ap.add_argument("--naming", choices=list(NAMING), default="item",
                    help="--files names: item, <item>/<page><suffix>.<ext>; flat, <page><suffix>.<ext> in one folder")
    ap.add_argument("--suffix", default="", metavar="SUFFIX",
                    help="--files: added to each file's stem, before the extension (e.g. .paddle: <page>.paddle.md)")
    ap.add_argument("--furniture", action="store_true",
                    help="--files: keep page headers and footers in md, txt and html (by default they are left out)")
    ap.add_argument("--policy", default="page-layers", metavar="ID@EDITION",
                    help="the rendering policy (a catalog policy) the documents, files and texts are rendered "
                         "under: which content roles are body, furniture, notes or nowhere")
    ap.add_argument("--strategy", default="literal",
                    help="the transcription strategy the page files' md, txt, html and json are written by: literal "
                         "(the default: as read), a catalog strategy, or normalizations joined by +")
    ap.add_argument("--item-texts", metavar="DIR",
                    help="per-item texts, one file per item and --text (<strategy>/<item>.<ext>) and JSON Lines "
                         "(<strategy>.<format>/<rank>.jsonl.gz), from the item's document (needs --document)")
    ap.add_argument("--text", action="append", default=[], metavar="STRATEGY:FORMAT",
                    help="an item text (--item-texts): a transcription strategy (literal, a catalog strategy, or "
                         "normalizations joined by +) and a format (md, txt, html, json); repeatable; default "
                         "literal:txt")
    ap.add_argument("--window", type=int, default=32, help="pages in flight per served step")
    ap.add_argument("--endpoint-for", action="append", default=[], metavar="STEP=URL",
                    help="a different server for one step")


def chosen(a) -> dict[str, str]:
    picks = {"layout": a.layout, "lines": a.lines, "recognition": a.recognition, "tables": a.tables,
             "formulas": a.formulas}
    return {step: preset for step, preset in picks.items() if preset}


def sets(a) -> dict[str, dict]:
    """``--set`` by step: the model steps picked and the rule-based ones."""
    return run.overrides(a.set, steps=[*chosen(a), *(s for s in RULE_SLOTS if getattr(a, s))])


def models(a) -> list[dict]:
    over = sets(a)
    return [{"name": step, "preset": preset, **({"overrides": over[step]} if step in over else {})}
            for step, preset in chosen(a).items()]


def pipeline(a, script: str) -> list:
    from linecaster.backends import Served

    picks = chosen(a)
    missing = [f"--{s}" for s in ("layout", "lines", "recognition") if s not in picks]
    if missing:
        raise PipelineConfigError(f"modular: pick {' and '.join(missing)} (`linecaster presets` lists the presets; "
                                  "--layout single-region reads the page as one region)")
    if a.item_texts and not a.document:
        raise PipelineConfigError("modular: --item-texts writes the item's document; pick --document (e.g. "
                                  "linked-document)")
    texts = parse_texts(a.text or ["literal:txt"]) if a.item_texts else ()
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
                           layout=LayoutDetector(b["layout"]), formulas_separately="formulas" in b,
                           direction=a.direction),
        *([TableRecognizer(b["tables"])] if "tables" in b else []),
        *([FormulaRecognizer(b["formulas"])] if "formulas" in b else []),
        *([HierarchyDetector(a.hierarchy, options=over.get("hierarchy"))] if a.hierarchy else []),
        *([ParagraphBuilder(a.paragraphs, options=over.get("paragraphs"))] if a.paragraphs else []),
        *([DocumentComposer(a.document, options=over.get("document"), policy=a.policy)] if a.document else []),
        # no files for a page a component failed on: OUT/rejects lists it, the page records keep it with its errors
        *([PageFileWriter(a.files, formats=formats, furniture=a.furniture, skip_failed=True, suffix=a.suffix,
                          policy=a.policy, strategy=a.strategy, **NAMING[a.naming])]
          if a.files else []),
        run.pages(a),
        # after the page writers, the item stage: the ItemAssembler gathers each item's pages into an item record; with
        # several tasks the builder cuts here (the pages in item shards, then a stage over whole items)
        *([ItemAssembler(), *([ParagraphBuilder(a.paragraphs, unit="item", options=over.get("paragraphs"))]
                       if a.paragraphs else []),
           DocumentComposer(a.document, unit="item", options=over.get("document"), policy=a.policy),
           ItemDocumentWriter(a.item_texts, texts=[f"{s}:{f}" for s, f in texts], policy=a.policy),
           ItemTextWriter(a.item_texts, texts=[f"{s}:{f}" for s, f in texts], policy=a.policy)]
          if a.item_texts else []),
        *servers,                                 # last: lives until every page is written
    ]


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "transcribe_modular.v1"
SLOTS = {"layout": "layout", "lines": "lines", "recognition": "recognition", "tables": "tables", "formulas": "formulas",
         "hierarchy": "hierarchy", "paragraphs": "paragraphs", "document": "document"}
