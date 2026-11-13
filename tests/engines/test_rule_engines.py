"""The built-in engines of the rule-based steps (``linecaster.engines``): registered in-process only under their
ids, described by the docs, options with today's constants as defaults, every option in effect, and the decisions
the recomposition records. (The recomposition and composition against the legacy builder:
``tests/blocks/composition/test_recomposition_parity.py``.)"""
import inspect
import io

import pytest
from PIL import Image

from conftest import sample_transcription
from linecaster.catalog import code
from linecaster.catalog.registry import BUILTIN_ENGINES, IN_PROCESS_ONLY, SERVED_ONLY, engine_class
from linecaster.catalog.schema import RULE_STEPS, STEPS, Capabilities
from linecaster.data import Transcription
from linecaster.engines import scripts

#: built-in engines of model steps: in-process only too
MODEL_STEP_ENGINES = {"layout.single-region.v1"}
RULE_ENGINES = sorted(set(BUILTIN_ENGINES) - SERVED_ONLY - MODEL_STEP_ENGINES)
#: engines whose options have no defaults (a by-script engine's strategies come from its preset)
NEEDS_OPTIONS = {"image.convert.v1", "normalization.by-script.v1", "recomposition.by-script.v1"}


def test_the_rule_based_steps_are_steps():
    assert set(RULE_STEPS) <= set(STEPS) and STEPS[:5] == ("layout", "lines", "recognition", "tables", "formulas")
    assert {engine_class(e).step for e in RULE_ENGINES} == set(RULE_STEPS)


def test_rule_engines_run_in_process_only():
    assert IN_PROCESS_ONLY == set(RULE_ENGINES) | MODEL_STEP_ENGINES and not IN_PROCESS_ONLY & SERVED_ONLY


@pytest.mark.parametrize("engine", RULE_ENGINES)
def test_rule_engines_declare_themselves(engine):
    cls = engine_class(engine)
    assert cls.engine_id == engine and engine.startswith(f"{cls.step}.") and cls.step in RULE_STEPS
    caps = Capabilities.model_validate(cls.capabilities)
    assert caps.unit in ("page", "item") and caps.produces
    assert cls.scripts and all(scripts.check_code(s) for s in cls.scripts)
    fields = cls.Options.model_fields
    assert all(f.description for f in fields.values()), [n for n, f in fields.items() if not f.description]
    with pytest.raises(ValueError):                 # unknown options are errors, in presets too
        cls.Options(no_such_option=1)
    if engine not in NEEDS_OPTIONS:
        e = cls()
        e.load()
        assert e.options == cls.Options()


def test_the_docs_describe_every_builtin_engine():
    """The docs read the engines from the source: the same ids, classes, steps, capabilities, scripts, options."""
    found = {eid: e for eid, e in code.engines().items() if e.package == "linecaster"}
    assert {eid: e.target for eid, e in found.items()} == BUILTIN_ENGINES
    for eid in sorted(IN_PROCESS_ONLY):
        cls, e = engine_class(eid), found[eid]
        assert (e.step, e.capabilities, tuple(e.scripts)) == (cls.step, cls.capabilities, cls.scripts)
        assert [o.name for o in e.options] == list(cls.Options.model_fields)


def test_options_default_to_todays_constants():
    from linecaster.engines import (DoclingCompositionEngine, RatiosTypographyEngine, UnicodeRecompositionEngine,
                                    WebpLosslessImageEngine)
    from linecaster.images.convert import to_working_webp
    from linecaster.text import recomposition as R
    from linecaster.text import typography as T

    o = RatiosTypographyEngine.Options()
    assert (o.page_number_min_conf, o.demote, o.split, o.max_headline_rows) == (
        T.PAGE_NUMBER_MIN_CONF, T.DEMOTE, T.SPLIT, T.MAX_HEADLINE_ROWS)
    assert o.levels == [tuple(x) for x in T.LEVELS] and tuple(o.heading_labels) == T.HEADING_LABELS
    assert RatiosTypographyEngine.ratios(o) == T.Ratios()
    r = UnicodeRecompositionEngine.Options()
    assert r.convention_marks == R.CONVENTION_MARKS and not r.rtl
    assert UnicodeRecompositionEngine.thresholds(r) == R.Thresholds()
    assert WebpLosslessImageEngine.Options().effort == inspect.signature(to_working_webp).parameters["effort"].default
    assert DoclingCompositionEngine.Options().model_dump() == {"sections": False}


@pytest.mark.parametrize("step,preset", [("image", "working-image"), ("normalization", "latin-historic"),
                                         ("typography", "ratios"), ("recomposition", "unicode-recomposition"),
                                         ("composition", "docling-composition")])
def test_the_presets_are_the_engines_defaults(step, preset):
    """Each rule-based preset names every option of its engine, with the engine's defaults: today's behavior."""
    from linecaster.catalog.registry import catalog

    r = catalog().resolve(f"{preset}@1")
    cls = engine_class(r.engine)
    assert r.content["step"] == step == cls.step and r.released
    assert cls.Options(**r.content.get("options", {})) == cls.Options()
    assert set(r.content.get("options", {})) == set(cls.Options.model_fields)


# ------------------------------------------------------------------------------------------------- typography

def _typography_page():
    from conftest import body_region, line, page_with, region

    b, bl = body_region("text_1", 1, 300)                         # body rows 20 high
    rid = "text_5"
    head = region(rid, "text", 100, 800, 800, 200, 5)
    hl = [line(rid, 0, 100, 800, 800, 34, "HEADLINE"), line(rid, 1, 100, 840, 800, 20, "after a"),
          line(rid, 2, 100, 870, 800, 20, "after b")]
    return page_with([
        region("doc_title_0", "title", 100, 100, 800, 60, 0), b,
        region("section_header_2", "section_header", 100, 600, 800, 22, 2),
        region("section_header_3", "section_header", 100, 700, 800, 36, 3),
        region("number_4", "page_footer", 450, 1000, 40, 20, 4, raw="number"), head,
    ], [line("doc_title_0", 0, 100, 100, 800, 60, "TITLE"), *bl,
        line("section_header_2", 0, 100, 600, 800, 22, "kicker"),
        line("section_header_3", 0, 100, 700, 800, 36, "Chapter"),
        line("number_4", 0, 450, 1000, 40, 20, "12", conf=0.7), *hl])


def test_typography_is_the_retyper_and_records_its_step():
    from linecaster.engines import RatiosTypographyEngine
    from linecaster.text.typography import retype

    want, got = _typography_page(), _typography_page()
    n = len(want.annotators)
    stats = retype(want, annotator=want.add_annotator(RatiosTypographyEngine().annotator()))
    RatiosTypographyEngine()(got)
    m = got.annotators[-1]
    assert len(got.annotators) == n + 1 and (m.kind, m.step, m.name, m.engine) == (
        "rule", "typography", "typography.ratios.v1", "typography.ratios.v1")
    assert m.measurements == stats.counts() and m.settings == RatiosTypographyEngine.Options().model_dump(mode="json")
    want.annotators[-1].measurements = m.measurements
    assert got == want
    # every annotation it added names it; nothing that was there changed
    before = _typography_page()
    assert all(c.annotator == n for c in got.classifications[len(before.classifications):])
    assert [r for r in got.regions if r.id in {x.id for x in before.regions}] == before.regions
    assert got.lines == before.lines and got.orders[:len(before.orders)] == before.orders


def test_every_typography_threshold_is_an_option():
    from linecaster.engines import RatiosTypographyEngine

    def run(**options):
        t = _typography_page()
        RatiosTypographyEngine(**options)(t)
        return ({r.id: (t.label(r.id), t.heading_level(r.id)) for r in t.regions if t.status(r.id) is None},
                t.annotators[-1].measurements)

    regions, m = run()
    assert regions["doc_title_0"] == ("title", 1) and regions["section_header_3"] == ("section_header", 2)
    assert regions["section_header_2"] == ("text", None) and "number_4" not in regions      # 1.1x; 0.7 < 0.75
    assert regions["text_5_head"] == ("section_header", 2) and m["split"] == 1               # 34 / 20 = 1.7
    assert run(demote=1.0)[0]["section_header_2"] == ("section_header", 3)                  # no longer demoted
    assert run(levels=[(4.0, 1), (0.0, 2)])[0]["doc_title_0"] == ("title", 2)
    assert "number_4" in run(page_number_min_conf=0.5)[0]
    assert "text_5_head" not in run(split=1.8)[0]
    assert "text_5_head" not in run(max_headline_rows=0)[0]
    assert run(heading_labels=["title"])[0]["section_header_2"] == ("section_header", None)  # not a heading: untouched
    assert run(demote=1.0)[1]["demoted"] == 0
    e = RatiosTypographyEngine(demote=1.0)
    assert e(_typography_page(), demote=1.2).annotators[-1].settings["demote"] == 1.2      # a call's options win
    with pytest.raises(ValueError):
        RatiosTypographyEngine(no_such=1)


# ------------------------------------------------------------------------------------- the others

def test_normalization_fills_the_normalized_texts():
    from linecaster.engines import LatinHistoricNormalizationEngine
    from linecaster.text.variants import normalize

    t = sample_transcription()
    t.lines[0].reading.text = "Vnterſuchung der ﬁſche"
    from conftest import recomposed

    recomposed(t)
    before = t.model_copy(deep=True)
    LatinHistoricNormalizationEngine()(t)

    def normalized(target, text):
        return t.edit(target, ("normalized",)) or text

    assert normalized("l0", None) == "Vntersuchung der fische"
    assert [normalized(ln.id, t.text_of(ln)) for ln in t.lines] == [
        None if ln.reading is None else normalize(ln.reading.text) for ln in t.lines]
    assert [ln.reading for ln in t.lines] == [ln.reading for ln in before.lines]      # as written stays
    assert [normalized(p.id, p.text) for p in t.paragraphs] == [normalize(p.text) for p in t.paragraphs]
    assert normalized(t.paragraphs[0].id, None) == "Vntersuchung der fische"
    assert t.paragraphs[0].text == "Vnterſuchung der ﬁſche"
    assert {e.target for e in t.edits if e.kind == "normalized"} == {"l0", t.paragraphs[0].id}   # only what changed
    m = t.annotators[-1]
    assert (m.step, m.engine, m.name) == ("normalization", "normalization.latin-historic.v1",
                                          "normalization.latin-historic.v1")
    assert m.measurements["changed"] == 2 and all(e.annotator == len(t.annotators) - 1 for e in t.edits)


def test_image_is_the_working_webp():
    from linecaster.engines import WebpLosslessImageEngine
    from linecaster.images.convert import to_working_webp

    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(buf, format="PNG")
    assert WebpLosslessImageEngine()(buf.getvalue()) == to_working_webp(buf.getvalue())
    assert WebpLosslessImageEngine()(buf.getvalue(), effort=0)[1]["webp_settings"]["quality"] == 0
    assert WebpLosslessImageEngine(effort=10)(buf.getvalue())[1]["webp_settings"]["quality"] == 10


def test_composition_from_lines_and_from_paragraphs():
    """Without paragraphs a text region is one item, its rows as laid out; with them one item per paragraph, one
    provenance entry per row."""
    from conftest import recomposed
    from linecaster.formats.docling import build_docling, docling_dict

    lines = docling_dict(build_docling(sample_transcription(), name="p1"))
    flowed = docling_dict(build_docling(recomposed(sample_transcription()), name="p1"))
    body = lambda d: [x for x in d["texts"] if x["label"] == "text"]       # noqa: E731
    assert body(lines)[0]["text"] == ("The species described here were col-\nlected in the summer of 1887 by the "
                                      "author.\n\n") and len(body(lines)[0]["prov"]) == 1    # two rows without text
    assert body(flowed)[0]["text"] == "The species described here were collected in the summer of 1887 by the author."
    assert [p["charspan"] for p in body(flowed)[0]["prov"]] == [[0, 35], [35, 78]]      # the mark removed
    sections = docling_dict(build_docling(recomposed(sample_transcription()), name="p1", sections=True))
    assert [g["name"] for g in sections["groups"]] == ["Flora of the Northern Hills"]


def test_pages_of_an_item_share_the_lexicon():
    """The item's lexicon grows page by page in page order: a word attested hyphenated on page 1 keeps the hyphen
    on page 2, not on page 1 (the lexicon of a page holds that page and the pages before it)."""
    from conftest import line, page_with, region

    from linecaster.engines import UnicodeRecompositionEngine

    def page(rows):
        return page_with([region("text_0", "text", 100, 100, 800, 30 * len(rows), 0)],
                         [line("text_0", k, 100, 100 + 30 * k, 800, 20, s) for k, s in enumerate(rows)])

    first = page(["Die Nord-", "see liegt kalt.", "Die Nord-See ist kalt."])
    second = page(["Die Nord-", "see liegt kalt."])
    pages = UnicodeRecompositionEngine()([first.model_copy(deep=True), second.model_copy(deep=True)])
    assert [p.paragraphs[0].text[:12] for p in pages] == ["Die Nord-see"] * 2
    alone = UnicodeRecompositionEngine()([second.model_copy(deep=True)])
    assert alone[0].paragraphs[0].text.startswith("Die Nordsee")
    assert all(len(p.annotators) == 2 and p.annotators[-1].step == "recomposition" for p in pages)
    assert all(q.annotator == 1 for p in pages for q in p.paragraphs)
    assert Transcription.model_validate_json(pages[1].model_dump_json()) == pages[1]
