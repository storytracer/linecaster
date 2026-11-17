"""Dispatch by script (``linecaster.engines.base.ScriptDispatch``, ``linecaster.engines.scripts``): the script of a
decision and of a text's runs, the by-script engines routing each decision to a strategy, and by-script presets in
the catalog. Today one strategy covers every script, so the second one here is a fake."""
import datetime as dt

import pytest

from linecaster.catalog import registry
from linecaster.catalog.registry import Catalog, engine_spec, write_entry
from linecaster.data import Annotator, Transcription
from linecaster.engines import ByScriptParagraphsEngine, ScriptDispatch
from linecaster.engines.base import RuleEngine
from linecaster.engines.scripts import Classifier, check_code
from linecaster.errors import CatalogError

HERE = "test_dispatch"


class FakeHebrewRecompositionEngine(RuleEngine):
    """A Hebrew strategy that keeps every division mark and joins rows with " | "; notes what it decided."""

    engine_id = "paragraphs.fake-hebrew.v1"
    step = "paragraphs"
    capabilities = {"unit": "item", "produces": ["paragraphs"]}
    scripts = ("Hebr",)
    calls: list = []

    def resolve_mark(self, prev_text, next_text, lexicon=None):
        self.calls.append(("mark", prev_text[-3:], next_text[:3]))
        return False, ""

    def separator(self, prev_text, next_text):
        self.calls.append(("separator", prev_text[-3:], next_text[:3]))
        return " | "


def spec(cls) -> dict:
    return {"engine": f"{HERE}:{cls.__name__}", "options": {}}


UNICODE = {"engine": "linecaster.engines:UnicodeParagraphsEngine", "options": {}}
RATIOS = {"engine": "linecaster.engines:RatiosHierarchyEngine", "options": {}}


# ------------------------------------------------------------------------------------------------ scripts

def test_the_script_of_a_decision_and_of_runs():
    c = Classifier(["Latn", "Hebr"])
    qamats, diaeresis, superscript_e = "ָ", "̈", "ͤ"      # Hebrew, Inherited, Inherited
    assert (c("a"), c("ſ"), c("ש"), c(qamats), c("-"), c(" "), c(diaeresis), c(superscript_e), c("α")) == (
        "Latn", "Latn", "Hebr", "Hebr", None, None, None, None, "*")
    assert c.at("Wort-", "teil") == "Latn"                   # the letter before the row end decides
    assert c.at("שָׁלוֹ-", "ם") == "Hebr" and c.at("שלו-", "teil") == "Hebr"
    assert c.at("1914 -", "teil") == "Latn" and c.at("-", "") == "*" and c.at("λόγ-", "ος") == "*"
    assert c.runs("ſchön, שָׁלוֹם! 12 abc") == [("Latn", "ſchön, "), ("Hebr", "שָׁלוֹם! 12 "), ("Latn", "abc")]
    assert c.runs("« שלום") == [("Hebr", "« שלום")] and c.runs("12 –") == [("*", "12 –")] and c.runs("") == []
    with pytest.raises(ValueError):
        check_code("Latin")
    with pytest.raises(ValueError):
        check_code("Xyzw")


def test_a_dispatch_needs_a_default_and_covering_strategies():
    with pytest.raises(ValueError, match="default"):
        ScriptDispatch({"Hebr": spec(FakeHebrewRecompositionEngine)})
    with pytest.raises(ValueError, match="covers only"):
        ScriptDispatch({"Latn": spec(FakeHebrewRecompositionEngine), "*": UNICODE})
    with pytest.raises(ValueError, match="hierarchy engine"):
        ScriptDispatch({"Hebr": RATIOS, "*": UNICODE}, step="paragraphs")
    d = ScriptDispatch({"Hebr": spec(FakeHebrewRecompositionEngine), "*": UNICODE})
    assert type(d.at("שלו-", "ם")).__name__ == "FakeHebrewRecompositionEngine"
    assert type(d.at("Wort-", "teil")).__name__ == "UnicodeParagraphsEngine"
    assert type(d.strategy("Arab")) is type(d.default)


# --------------------------------------------------------------------------------------- by-script engines

def _region(t, a, rid, order, texts, x0=100.0):
    """A text region of ``texts`` by annotator ``a`` of ``t``: one line per row, 30 high every 40; returns its line
    ids."""
    t.add_region(a, rid, [x0 - 10, 90.0, 820.0, 40.0 * len(texts) + 20],
                 [[x0 - 10, 90.0], [x0 + 810, 90.0], [x0 + 810, 110.0 + 40 * len(texts)],
                  [x0 - 10, 110.0 + 40 * len(texts)]], label="text", role="text")
    for i, text in enumerate(texts):
        y = 100.0 + 40 * i
        t.add_line(a, f"{rid}_l{i}", [x0, y, 800.0, 30.0], [[x0, y], [x0 + 800, y], [x0 + 800, y + 30], [x0, y + 30]],
                   region=rid, text=text)
    return [f"{rid}_l{i}" for i in range(len(texts))]


def test_recomposition_by_script_routes_each_decision():
    """A Latin and a Hebrew region on one page: the Latin row ends decided by the Unicode rules, the Hebrew ones by
    the Hebrew strategy; the by-script engine records the step."""
    from linecaster.engines import UnicodeParagraphsEngine

    page = Transcription()
    a = page.add_annotator(Annotator(step="layout", name="test"))
    latin = _region(page, a, "latin", 0, ["Die Untersuchung der Ab-", "lagerungen ist alt."])
    hebrew = _region(page, a, "hebrew", 1, ["שָׁלוֹם עֲלֵי-", "כֶם וּבְרָכָה", "וְשָׁלוֹם"])
    lines = latin + hebrew
    page.add_order(a, ["latin", "hebrew"], lines, [0, 1, 0, 1, 2])
    FakeHebrewRecompositionEngine.calls = []
    e = ByScriptParagraphsEngine(strategies={"Hebr": spec(FakeHebrewRecompositionEngine), "*": UNICODE})
    (t,) = e([page.model_copy(deep=True)])
    # each row end goes to its script's strategy: the Hebrew one is asked about its mark and its separator; the
    # paragraphs hold their rows (since linecaster.page/5 no text: a strategy writes it)
    assert [c[0] for c in FakeHebrewRecompositionEngine.calls] == ["mark", "separator"]
    assert [[r.lines for r in p.rows] for p in t.paragraphs] == [[["latin_l0"], ["latin_l1"]],
                                                                 [["hebrew_l0"], ["hebrew_l1"], ["hebrew_l2"]]]
    m = t.annotators[-1]
    assert len(t.annotators) == 2 and (m.step, m.engine) == ("paragraphs", "paragraphs.by-script.v1")
    assert m.settings["strategies"]["Hebr"]["engine"] == f"{HERE}:FakeHebrewRecompositionEngine"
    (alone,) = UnicodeParagraphsEngine()([page.model_copy(deep=True)])
    assert [[r.lines for r in p.rows] for p in alone.paragraphs] == [[r.lines for r in p.rows] for p in t.paragraphs]


# -------------------------------------------------------------------------------------------- the catalog

def preset(root, pid, engine, step="paragraphs", **fields):
    write_entry(root / "presets" / step / f"{pid}.yaml", {
        "schema": "linecaster.preset", "id": pid, "step": step, "engine": engine,
        "capabilities": {"unit": "item", "produces": ["paragraphs"]}, **fields})


@pytest.fixture
def fake_engine(monkeypatch):
    monkeypatch.setitem(registry.BUILTIN_ENGINES, FakeHebrewRecompositionEngine.engine_id,
                        f"{HERE}:FakeHebrewRecompositionEngine")
    monkeypatch.setattr(registry, "IN_PROCESS_ONLY", registry.IN_PROCESS_ONLY | {FakeHebrewRecompositionEngine.engine_id})


def test_by_script_presets(tmp_path, fake_engine):
    preset(tmp_path, "unicode-paragraphs", "paragraphs.unicode.v1")
    preset(tmp_path, "hebrew-recomposition", FakeHebrewRecompositionEngine.engine_id)
    preset(tmp_path, "by-script", "paragraphs.by-script.v1",
           by_script={"Hebr": "hebrew-recomposition", "*": "unicode-paragraphs"})
    c = Catalog([tmp_path])
    c.write_index()                                   # a catalog directory commits its index (catalog.index)
    assert c.verify() == []
    content = c.resolve("by-script").content
    assert content["by_script"] == {code: {"ref": ref, "sha256": c.resolve(ref).sha256} for code, ref in
                                    (("*", "unicode-paragraphs"), ("Hebr", "hebrew-recomposition"))}
    with registry.active(c):
        target, kwargs, r = engine_spec("by-script")
        assert target == "linecaster.engines:ByScriptParagraphsEngine" and r.ref == "by-script"
        assert kwargs["strategies"]["Hebr"] == {"engine": f"{HERE}:FakeHebrewRecompositionEngine", "options": {},
                                                "preset": "hebrew-recomposition",
                                                "preset_sha256": c.resolve("hebrew-recomposition").sha256}
        e = registry.engine_class(r.engine)(**kwargs)
        assert type(e.dispatch.at("שלו-", "ם")).__name__ == "FakeHebrewRecompositionEngine"
        with pytest.raises(CatalogError, match="pipeline's process only"):
            engine_spec("by-script", served=True)
    assert Catalog([tmp_path]).verify() == []


def test_by_script_presets_are_checked(tmp_path, fake_engine):
    preset(tmp_path, "unicode-paragraphs", "paragraphs.unicode.v1")
    preset(tmp_path, "hebrew-recomposition", FakeHebrewRecompositionEngine.engine_id)
    preset(tmp_path, "latin-hebrew", "paragraphs.by-script.v1",
           by_script={"Latn": "hebrew-recomposition", "*": "unicode-paragraphs"})
    preset(tmp_path, "unknown", "paragraphs.by-script.v1",
           by_script={"Hebr": "no-such", "*": "unicode-paragraphs"})
    preset(tmp_path, "ratios", "hierarchy.ratios.v1", step="hierarchy",
           capabilities={"unit": "page", "produces": ["hierarchy"]})
    preset(tmp_path, "other-step", "paragraphs.by-script.v1",
           by_script={"*": "ratios"})
    problems = Catalog([tmp_path]).verify()
    assert any("latin-hebrew: by_script Latn" in p and "covers only ['Hebr']" in p for p in problems)
    assert any("unknown: by_script Hebr" in p and "no-such" in p for p in problems)
    assert any("other-step: by_script *" in p and "hierarchy preset" in p for p in problems)
    for bad in ({"Hebr": "hebrew-recomposition"}, {"Hebrew": "x", "*": "y"}, {"*": "unicode-paragraphs@1"}):
        preset(tmp_path, "bad", "paragraphs.by-script.v1", by_script=bad)
        with pytest.raises(CatalogError, match="by_script"):
            Catalog([tmp_path])
