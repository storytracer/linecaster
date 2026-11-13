r"""The item stage (binding): an item's pages (book, issue, manuscript) bound into one item record, recomposed as one
(paragraphs continued across page breaks), normalized and composed into the item's document; one text per item and
text variant, and the item document in each format. It reads the page records of a transcribe run; written in item
shards (`--item-shards N`), each task reads whole shard folders, so it sees every page of its items. No engine or
GPU is needed: the steps are rule-based, each a preset (`--recipe item-texts` fills them).

    uv run pipelines/bind.py OUT1/pages OUT2 --recipe item-texts
    uv run pipelines/bind.py OUT1/pages OUT2 --recomposition unicode-recomposition --normalization latin-historic \
        --composition docling-composition
    uv run pipelines/transcribe_modular.py IMAGES OUT1 ... --tasks 4000 --item-shards 64
    uv run pipelines/bind.py OUT1/pages OUT2 --recipe item-texts --tasks 64
    ... --set composition.sections=true          # an option over the preset's
    ... --no-documents                           # texts only (then --composition is not needed)
    ... --on hf-jobs --namespace NS --commit <sha> --flavor cpu-upgrade --tasks 64

Texts in OUT2/texts/<variant>/<rank>.jsonl.gz (with --files also OUT2/texts/<variant>/<item>.txt|.md), item
documents in OUT2/documents/<format>/<item>.<ext>. ``linecaster.runtime.run`` has the options every pipeline shares
(IMAGES is the page records folder here).
"""
from ..blocks.binding import Binder
from ..blocks.composition import Composer, Recomposer
from ..blocks.readers.records import PageRecordReader
from ..blocks.text import CharacterNormalizer
from ..blocks.writers.items import ItemDocumentWriter, ItemTextWriter
from ..errors import PipelineConfigError
from ..runtime import run

#: the rule-based steps of the item stage, each a slot
RULE_STEPS = ("recomposition", "normalization", "composition")


def options(ap):
    ap.add_argument("--recomposition", help="recomposition preset: the item's pages as running text, paragraphs "
                                            "continued across page breaks (e.g. unicode-recomposition)")
    ap.add_argument("--normalization", help="character normalization preset of the readable texts "
                                            "(e.g. latin-historic)")
    ap.add_argument("--composition", help="composition preset: the item's document (e.g. docling-composition)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. composition.sections=true; repeatable")
    ap.add_argument("--variants", default="verbatim_txt,readable_txt,readable_md",
                    help="text variants, comma-separated: verbatim_txt, readable_txt, readable_md")
    ap.add_argument("--files", action="store_true", help="also one file per item and variant: OUT/texts/<variant>/")
    ap.add_argument("--no-texts", action="store_true", help="no item texts")
    ap.add_argument("--formats", default="md,txt,json",
                    help="item document formats, comma-separated: md, txt, html, doclang, json")
    ap.add_argument("--furniture", action="store_true",
                    help="item documents: keep page headers and footers in md, txt and html")
    ap.add_argument("--dividers", action="store_true",
                    help="item documents: --- between the items of consecutive layout regions in md")
    ap.add_argument("--policy", default="page-layers@1", metavar="ID@EDITION",
                    help="the rendering policy (a catalog policy edition) the documents, files and texts are rendered "
                         "under: which content roles are body, furniture, notes or nowhere")
    ap.add_argument("--no-documents", action="store_true", help="no item documents")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    out = a.out.rstrip("/")
    variants = tuple(v for v in a.variants.split(",") if v) if not a.no_texts else ()
    if not variants and a.no_documents:
        raise PipelineConfigError("bind: --no-texts and --no-documents leave nothing to write")
    readable = any(v != "verbatim_txt" for v in variants)
    needs = [*(("recomposition", "normalization") if readable else ()),
             *(("composition",) if not a.no_documents else ())]
    missing = [f"--{s}" for s in needs if not getattr(a, s)]
    if missing:
        raise PipelineConfigError(f"bind: pick {' and '.join(missing)} (or --recipe item-texts); the readable texts "
                                  f"need the recomposition and the normalization, the documents the composition")
    over = run.overrides(a.set, steps=[s for s in RULE_STEPS if getattr(a, s)])
    return [
        PageRecordReader(a.images, fetch_images=False, item_shards=True, sample=run.sample_rule(a)),
        Binder(),
        *([Recomposer(a.recomposition, unit="item", options=over.get("recomposition"))] if a.recomposition else []),
        *([CharacterNormalizer(a.normalization, unit="item", options=over.get("normalization"))]
          if a.normalization else []),
        *([Composer(a.composition, unit="item", options=over.get("composition"), policy=a.policy)]
          if a.composition and not a.no_documents else []),
        *([ItemTextWriter(f"{out}/texts", format="files", variants=variants, policy=a.policy)]
          if variants and a.files else []),
        *([ItemTextWriter(f"{out}/texts", variants=variants, policy=a.policy)] if variants else []),
        *([ItemDocumentWriter(f"{out}/documents", formats=tuple(a.formats.split(",")), furniture=a.furniture,
                              dividers=a.dividers, by_format=True)] if not a.no_documents else []),
    ], {"engines": False}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "bind.v1"
SLOTS = {"recomposition": "recomposition", "normalization": "normalization", "composition": "composition"}
