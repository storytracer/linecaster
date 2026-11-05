"""The built-in engines of the rule-based steps (``linecaster.engines``): registered in-process only under their
ids, described by the docs, options with today's constants as defaults, and, while they wrap today's code, the same
results as that code (step 3.2 of the plan makes them real)."""
import inspect
import io

import pytest
from PIL import Image

from conftest import make_transcription
from linecaster.catalog import code
from linecaster.catalog.registry import BUILTIN_ENGINES, IN_PROCESS_ONLY, SERVED_ONLY, engine_class
from linecaster.catalog.schema import RULE_STEPS, STEPS, Capabilities
from linecaster.data import Transcription
from linecaster.engines import scripts

RULE_ENGINES = sorted(set(BUILTIN_ENGINES) - SERVED_ONLY)
#: engines whose options have no defaults (a by-script engine's strategies come from its preset)
NEEDS_OPTIONS = {"normalization.by-script.v1", "recomposition.by-script.v1"}


def test_the_rule_based_steps_are_steps():
    assert set(RULE_STEPS) <= set(STEPS) and STEPS[:5] == ("layout", "lines", "recognition", "tables", "formulas")
    assert {engine_class(e).step for e in RULE_ENGINES} == set(RULE_STEPS)


def test_rule_engines_run_in_process_only():
    assert IN_PROCESS_ONLY == set(RULE_ENGINES) and not IN_PROCESS_ONLY & SERVED_ONLY


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
    for eid in RULE_ENGINES:
        cls, e = engine_class(eid), found[eid]
        assert (e.step, e.capabilities, tuple(e.scripts)) == (cls.step, cls.capabilities, cls.scripts)
        assert [o.name for o in e.options] == list(cls.Options.model_fields)


def test_options_default_to_todays_constants():
    from linecaster.blocks.composition.composer import Composer
    from linecaster.engines import (DoclingCompositionEngine, RatiosTypographyEngine, UnicodeRecompositionEngine,
                                    WebpLosslessImageEngine)
    from linecaster.images.convert import to_working_webp
    from linecaster.text import recomposition as R
    from linecaster.text import typography as T

    o = RatiosTypographyEngine.Options()
    assert (o.page_number_min_conf, o.demote, o.split, o.max_headline_rows) == (
        T.PAGE_NUMBER_MIN_CONF, T.DEMOTE, T.SPLIT, T.MAX_HEADLINE_ROWS)
    assert o.levels == [tuple(x) for x in T.LEVELS] and tuple(o.heading_labels) == T.HEADING_LABELS
    assert UnicodeRecompositionEngine.Options().convention_marks == R.CONVENTION_MARKS
    assert WebpLosslessImageEngine.Options().effort == inspect.signature(to_working_webp).parameters["effort"].default
    composer = {k: p.default for k, p in inspect.signature(Composer.__init__).parameters.items()}
    assert DoclingCompositionEngine.Options().model_dump() == {k: composer[k] for k in ("text", "sections", "rtl")}


# ------------------------------------------------------------------------------------- today's code, wrapped

def test_typography_is_the_retyper():
    from linecaster.engines import RatiosTypographyEngine
    from linecaster.text.typography import retype

    want, got = make_transcription(), make_transcription()
    retype(want)
    RatiosTypographyEngine()(got)
    assert got.steps[-1].engine == "typography.ratios.v1"
    got.steps[-1].engine = None
    assert got == want
    with pytest.raises(ValueError, match="not supported yet"):
        RatiosTypographyEngine(demote=1.5)(make_transcription())


def test_normalization_fills_the_normalized_texts():
    from linecaster.engines import LatinHistoricNormalizationEngine
    from linecaster.text.variants import normalize

    t = make_transcription()
    t.lines[0].text = "Vnterſuchung der ﬁſche"
    before = t.model_copy(deep=True)
    LatinHistoricNormalizationEngine()(t)
    assert t.lines[0].normalized == "Vntersuchung der fische"
    assert [ln.normalized for ln in t.lines] == [None if ln.text is None else normalize(ln.text) for ln in t.lines]
    assert [ln.text for ln in t.lines] == [ln.text for ln in before.lines]      # as written stays
    m = t.steps[-1]
    assert (m.step, m.engine, m.name) == ("normalization", "normalization.latin-historic.v1",
                                          "normalization.latin-historic.v1")
    assert m.measurements["changed"] >= 1


def test_image_is_the_working_webp():
    from linecaster.engines import WebpLosslessImageEngine
    from linecaster.images.convert import to_working_webp

    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(buf, format="PNG")
    assert WebpLosslessImageEngine()(buf.getvalue()) == to_working_webp(buf.getvalue())
    assert WebpLosslessImageEngine()(buf.getvalue(), effort=0)[1]["webp_settings"]["quality"] == 0


@pytest.mark.parametrize("text", ["lines", "reflow"])
def test_composition_is_the_composer(text):
    from linecaster.engines import DoclingCompositionEngine
    from linecaster.formats.docling import REGION_MAP_KEY, DocumentBuilder, docling_dict

    want, got = make_transcription(), make_transcription()
    b = DocumentBuilder("p1", text=text)
    b.add_page(want)
    DoclingCompositionEngine(text=text)(got, name="p1")
    assert got.docling == docling_dict(b.build()) and got.extra[REGION_MAP_KEY] == b.region_of
    assert got.steps[-1].engine == "composition.docling.v1" and got.steps[-1].settings["text"] == text


def test_recomposition_paragraphs_are_the_reflowed_documents():
    """The paragraphs the recomposition engine makes hold, row by row, the provenance of the reflowed document:
    the same texts, boxes and character spans."""
    from linecaster.data.geometry import BBox
    from linecaster.engines import UnicodeRecompositionEngine
    from linecaster.formats.docling import build_docling
    from linecaster.text.typography import line_bbox

    t = make_transcription()
    (got,) = UnicodeRecompositionEngine()([t])
    assert got is t and t.paragraphs and t.steps[-1].engine == "recomposition.unicode.v1"
    assert set(t.steps[-1].measurements) == {"paragraphs", "continuations", "marks_removed", "marks_kept"}
    by_id = {ln.id: ln for ln in t.lines}

    def box(row):
        bs = [line_bbox(by_id[i]) for i in row.lines]
        return BBox(min(b.x0 for b in bs), min(b.y0 for b in bs), max(b.x1 for b in bs), max(b.y1 for b in bs))

    doc = build_docling(make_transcription(), text="reflow")
    texts = [it for it in doc.texts if it.text.strip()]
    clamp = lambda v, hi: min(max(v, 0.0), hi)            # noqa: E731 - docling-core clamps boxes to the page
    w, h = doc.pages[1].size.width, doc.pages[1].size.height
    ours = [(p.text, [(clamp((b := box(r)).x0, w), clamp(b.y0, h), clamp(b.x1, w), clamp(b.y1, h), r.start, r.end)
                      for r in p.rows]) for p in t.paragraphs]
    theirs = [(it.text, [(pv.bbox.l, pv.bbox.t, pv.bbox.r, pv.bbox.b, *pv.charspan) for pv in it.prov]) for it in texts]
    assert ours == theirs


def test_pages_of_an_item_share_the_lexicon():
    from linecaster.engines import UnicodeRecompositionEngine

    pages = [make_transcription(), make_transcription()]
    UnicodeRecompositionEngine()(pages)
    assert all(p.paragraphs for p in pages) and all(len(p.steps) == 1 for p in pages)
    assert Transcription.model_validate_json(pages[1].model_dump_json()) == pages[1]
