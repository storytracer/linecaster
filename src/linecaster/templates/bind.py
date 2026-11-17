r"""The item stage (binding): an item's pages (book, issue, manuscript) bound into one item record, recomposed as one
(paragraphs continued across page breaks) and composed into the item's document, written by transcription
strategies. It reads the page records of a transcribe run; written in item shards (`--item-shards N`), each task
reads whole shard folders, so it sees every page of its items. No engine or GPU is needed: the steps are rule-based,
each a preset.

    uv run pipelines/bind.py OUT1/pages OUT2 --paragraphs unicode-paragraphs --document linked-document
    ... --text literal:txt --text latin-historic+flow+unicode-marks:md    # texts by named strategies
    uv run pipelines/transcribe_modular.py IMAGES OUT1 ... --tasks 4000 --item-shards 64
    uv run pipelines/bind.py OUT1/pages OUT2 ... --tasks 64
    ... --set composition.sections=true          # an option over the preset's
    ... --jsonl                                  # the texts as JSON Lines too
    ... --on hf-jobs --namespace NS --commit <sha> --flavor cpu-upgrade --tasks 64

Each text (``--text STRATEGY:FORMAT``; by default the literal document as JSON) is one file per item,
OUT2/documents/<strategy>/<item>.<ext>; with --jsonl also OUT2/texts/<strategy>.<format>/<rank>.jsonl.gz. Nothing is
normalized unless a text names a strategy. ``linecaster.execution.run`` has the options every pipeline shares (IMAGES
is the page records folder here).
"""
from linecaster.components.items import ItemAssembler
from linecaster.components.document import DocumentComposer
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.readers.records import PageRecordReader
from linecaster.components.writers.items import DEFAULT_TEXTS, ItemDocumentWriter, ItemTextWriter, parse_texts
from linecaster.errors import PipelineConfigError
from linecaster.execution import run

#: the rule-based steps of the item stage, each a slot
RULE_SLOTS = ("paragraphs", "document")


def options(ap):
    ap.add_argument("--paragraphs", help="recomposition preset: the item's pages as running text, paragraphs "
                                            "continued across page breaks (e.g. unicode-paragraphs)")
    ap.add_argument("--document", help="composition preset: the item's document (e.g. linked-document)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. composition.sections=true; repeatable")
    ap.add_argument("--text", action="append", default=[], metavar="STRATEGY:FORMAT",
                    help="an item text, one file per item (OUT/documents/<strategy>/<item>.<ext>): a transcription "
                         "strategy (literal, a catalog strategy, or normalizations joined by +) and a format (md, "
                         "txt, html, json); repeatable; default literal:json, the document as it is")
    ap.add_argument("--jsonl", action="store_true",
                    help="also the texts as JSON Lines, a row per item and text: OUT/texts/<strategy>.<format>/")
    ap.add_argument("--furniture", action="store_true",
                    help="item documents: keep page headers and footers in md, txt and html")
    ap.add_argument("--dividers", action="store_true",
                    help="item documents: --- between the items of consecutive layout regions in md")
    ap.add_argument("--policy", default="page-layers", metavar="ID@EDITION",
                    help="the rendering policy (a catalog policy) the documents, files and texts are rendered "
                         "under: which content roles are body, furniture, notes or nowhere")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    out = a.out.rstrip("/")
    texts = [f"{s}:{f}" for s, f in parse_texts(a.text or list(DEFAULT_TEXTS))]
    if not a.document:
        raise PipelineConfigError("bind: pick --document (or a --recipe that names it): every text is written "
                                  "from the item's document")
    over = run.overrides(a.set, steps=[s for s in RULE_SLOTS if getattr(a, s)])
    return [
        PageRecordReader(a.images, fetch_images=False, item_shards=True, sample=run.sample_rule(a)),
        ItemAssembler(),
        *([ParagraphBuilder(a.paragraphs, unit="item", options=over.get("paragraphs"))] if a.paragraphs else []),
        DocumentComposer(a.document, unit="item", options=over.get("document"), policy=a.policy),
        ItemDocumentWriter(f"{out}/documents", texts=texts, furniture=a.furniture, dividers=a.dividers,
                           policy=a.policy),
        *([ItemTextWriter(f"{out}/texts", texts=texts, policy=a.policy)] if a.jsonl else []),
    ], {"engines": False}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "bind.v1"
SLOTS = {"paragraphs": "paragraphs", "document": "document"}
