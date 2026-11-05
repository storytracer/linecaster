"""Dispatch by script (``linecaster.engines.base.ScriptDispatch``, ``linecaster.engines.scripts``): the script of a
decision and of a text's runs, the by-script engines routing each decision to a strategy, and by-script presets in
the catalog. Today one strategy covers every script, so the second one here is a fake."""
import datetime as dt

import pytest

from linecaster.catalog import registry
from linecaster.catalog.registry import Catalog, engine_spec, write_entry
from linecaster.data import Line, Region, Transcription
from linecaster.engines import ByScriptNormalizationEngine, ByScriptRecompositionEngine, ScriptDispatch
from linecaster.engines.base import RuleEngine
from linecaster.engines.normalization import TextNormalization
from linecaster.engines.scripts import Classifier, check_code
from linecaster.errors import CatalogError

HERE = "test_dispatch"


class FakeHebrewRecompositionEngine(RuleEngine):
    """A Hebrew strategy that keeps every division mark and joins rows with " | "; notes what it decided."""

    engine_id = "recomposition.fake-hebrew.v1"
    step = "recomposition"
    capabilities = {"unit": "item", "produces": ["paragraphs"]}
    scripts = ("Hebr",)
    calls: list = []

    def resolve_mark(self, prev_text, next_text, lexicon=None):
        self.calls.append(("mark", prev_text[-3:], next_text[:3]))
        return False, ""

    def separator(self, prev_text, next_text):
        self.calls.append(("separator", prev_text[-3:], next_text[:3]))
        return " | "


class FakeHebrewNormalizationEngine(TextNormalization):
    """A Hebrew strategy that drops the vowel points (Inherited marks) of its runs."""

    engine_id = "normalization.fake-hebrew.v1"
    step = "normalization"
    capabilities = {"unit": "page", "produces": ["normalized"]}
    scripts = ("Hebr",)

    def normalize(self, text):
        return "".join(ch for ch in text if not "֑" <= ch <= "ׇ")


class FakeIdentityNormalizationEngine(TextNormalization):
    """A default strategy for every script: changes nothing."""

    engine_id = "normalization.fake-identity.v1"
    step = "normalization"
    capabilities = {"unit": "page", "produces": ["normalized"]}
    scripts = ("*",)

    def normalize(self, text):
        return text


def spec(cls) -> dict:
    return {"engine": f"{HERE}:{cls.__name__}", "options": {}}


UNICODE = {"engine": "linecaster.engines:UnicodeRecompositionEngine", "options": {}}
LATIN = {"engine": "linecaster.engines:LatinHistoricNormalizationEngine", "options": {}}


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
    with pytest.raises(ValueError, match="normalization engine"):
        ScriptDispatch({"Hebr": spec(FakeHebrewNormalizationEngine), "*": UNICODE}, step="recomposition")
    d = ScriptDispatch({"Hebr": spec(FakeHebrewRecompositionEngine), "*": UNICODE})
    assert type(d.at("שלו-", "ם")).__name__ == "FakeHebrewRecompositionEngine"
    assert type(d.at("Wort-", "teil")).__name__ == "UnicodeRecompositionEngine"
    assert type(d.strategy("Arab")) is type(d.default)


# --------------------------------------------------------------------------------------- by-script engines

def test_normalization_by_script_routes_each_run():
    with pytest.raises(ValueError, match="covers only"):            # the default covers every script
        ByScriptNormalizationEngine(strategies={"Hebr": spec(FakeHebrewNormalizationEngine), "*": LATIN})
    e = ByScriptNormalizationEngine(strategies={"Hebr": spec(FakeHebrewNormalizationEngine), "Latn": LATIN,
                                                "*": spec(FakeIdentityNormalizationEngine)})
    assert e.normalize("Vnterſuchung: שָׁלוֹם, ﬁſche ὅτι ſ") == "Vntersuchung: שלום, fische ὅτι s"
    t = Transcription(lines=[Line(id="l0", text="ſ שָׁ"), Line(id="l1")])
    e(t)
    assert [ln.normalized for ln in t.lines] == ["s ש", None]
    m = t.steps[-1]
    assert (m.engine, m.measurements) == ("normalization.by-script.v1", {"changed": 1})
    assert set(m.settings["strategies"]) == {"Hebr", "Latn", "*"}


def _region(rid, order, texts, x0=100.0):
    lines = [Line(id=f"{rid}_l{i}", region_id=rid, reading_order=10 * order + i, row=i,
                  bbox=[x0, 100.0 + 40 * i, 800.0, 30.0],
                  polygon=[[x0, 100.0 + 40 * i], [x0 + 800, 100.0 + 40 * i], [x0 + 800, 130.0 + 40 * i],
                           [x0, 130.0 + 40 * i]], text=text) for i, text in enumerate(texts)]
    region = Region(id=rid, label="text", reading_order=order, bbox=[x0 - 10, 90.0, 820.0, 40.0 * len(texts) + 20],
                    polygon=[[x0 - 10, 90.0], [x0 + 810, 90.0], [x0 + 810, 110.0 + 40 * len(texts)],
                             [x0 - 10, 110.0 + 40 * len(texts)]])
    return region, lines


def test_recomposition_by_script_routes_each_decision():
    """A Latin and a Hebrew region on one page: the Latin row ends decided by the Unicode rules (the mark removed),
    the Hebrew ones by the Hebrew strategy (the mark kept, its own separator); the by-script engine records the
    step."""
    from linecaster.engines import UnicodeRecompositionEngine

    latin, latin_lines = _region("latin", 0, ["Die Untersuchung der Ab-", "lagerungen ist alt."])
    hebrew, hebrew_lines = _region("hebrew", 1, ["שָׁלוֹם עֲלֵי-", "כֶם וּבְרָכָה", "וְשָׁלוֹם"])
    page = Transcription(regions=[latin, hebrew], lines=latin_lines + hebrew_lines)
    FakeHebrewRecompositionEngine.calls = []
    e = ByScriptRecompositionEngine(strategies={"Hebr": spec(FakeHebrewRecompositionEngine), "*": UNICODE})
    (t,) = e([page.model_copy(deep=True)])
    # after a kept mark the rows join without a separator (the recomposition's rule); the next row end is the
    # Hebrew strategy's separator
    assert [p.text for p in t.paragraphs] == ["Die Untersuchung der Ablagerungen ist alt.",
                                              "שָׁלוֹם עֲלֵי-כֶם וּבְרָכָה | וְשָׁלוֹם"]
    assert [c[0] for c in FakeHebrewRecompositionEngine.calls] == ["mark", "separator"]
    hebrew_text = t.paragraphs[1].text
    assert [hebrew_text[r.start:r.end] for r in t.paragraphs[1].rows] == ["שָׁלוֹם עֲלֵי-", "כֶם וּבְרָכָה", "וְשָׁלוֹם"]
    assert [r.lines for r in t.paragraphs[1].rows] == [["hebrew_l0"], ["hebrew_l1"], ["hebrew_l2"]]
    m = t.steps[-1]
    assert (m.step, m.engine, m.measurements["marks_removed"], m.measurements["marks_kept"]) == (
        "recomposition", "recomposition.by-script.v1", 1, 1)
    assert m.settings["strategies"]["Hebr"]["engine"] == f"{HERE}:FakeHebrewRecompositionEngine"
    # with the Unicode rules for every script the Hebrew mark follows a Hebrew letter, and the next row is Hebrew too:
    # removed
    (alone,) = UnicodeRecompositionEngine()([page.model_copy(deep=True)])
    assert alone.paragraphs[1].text == "שָׁלוֹם עֲלֵיכֶם וּבְרָכָה וְשָׁלוֹם"
    assert alone.paragraphs[0].text == t.paragraphs[0].text


# -------------------------------------------------------------------------------------------- the catalog

def preset(root, pid, engine, step="recomposition", edition=1, **fields):
    write_entry(root / "presets" / step / f"{pid}.yaml", {
        "schema": "linecaster.preset/1", "id": pid, "edition": edition, "step": step, "engine": engine,
        "capabilities": {"unit": "item", "produces": ["paragraphs"]}, **fields})


@pytest.fixture
def fake_engine(monkeypatch):
    monkeypatch.setitem(registry.BUILTIN_ENGINES, FakeHebrewRecompositionEngine.engine_id,
                        f"{HERE}:FakeHebrewRecompositionEngine")
    monkeypatch.setattr(registry, "IN_PROCESS_ONLY", registry.IN_PROCESS_ONLY | {FakeHebrewRecompositionEngine.engine_id})


def test_by_script_presets(tmp_path, fake_engine):
    preset(tmp_path, "unicode-recomposition", "recomposition.unicode.v1")
    preset(tmp_path, "hebrew-recomposition", FakeHebrewRecompositionEngine.engine_id)
    preset(tmp_path, "by-script", "recomposition.by-script.v1",
           by_script={"Hebr": "hebrew-recomposition@1", "*": "unicode-recomposition@1"})
    c = Catalog([tmp_path])
    assert c.verify() == []
    content = c.resolve("by-script").content
    assert content["by_script"] == {code: {"ref": ref, "sha256": c.resolve(ref).sha256} for code, ref in
                                    (("*", "unicode-recomposition@1"), ("Hebr", "hebrew-recomposition@1"))}
    with registry.active(c):
        target, kwargs, r = engine_spec("by-script")
        assert target == "linecaster.engines:ByScriptRecompositionEngine" and r.ref == "by-script@1"
        assert kwargs["strategies"]["Hebr"] == {"engine": f"{HERE}:FakeHebrewRecompositionEngine", "options": {},
                                                "preset": "hebrew-recomposition@1",
                                                "preset_sha256": c.resolve("hebrew-recomposition").sha256}
        e = registry.engine_class(r.engine)(**kwargs)
        assert type(e.dispatch.at("שלו-", "ם")).__name__ == "FakeHebrewRecompositionEngine"
        with pytest.raises(CatalogError, match="pipeline's process only"):
            engine_spec("by-script", served=True)
    with pytest.raises(CatalogError, match="release its strategies first"):
        c.release("by-script")
    c.release("unicode-recomposition", today=dt.date(2026, 11, 6))
    c.release("hebrew-recomposition", today=dt.date(2026, 11, 6))
    c.release("by-script", today=dt.date(2026, 11, 6))
    assert Catalog([tmp_path]).verify() == []


def test_by_script_presets_are_checked(tmp_path, fake_engine):
    preset(tmp_path, "unicode-recomposition", "recomposition.unicode.v1")
    preset(tmp_path, "hebrew-recomposition", FakeHebrewRecompositionEngine.engine_id)
    preset(tmp_path, "latin-hebrew", "recomposition.by-script.v1",
           by_script={"Latn": "hebrew-recomposition@1", "*": "unicode-recomposition@1"})
    preset(tmp_path, "unknown", "recomposition.by-script.v1",
           by_script={"Hebr": "no-such@1", "*": "unicode-recomposition@1"})
    preset(tmp_path, "latin-historic", "normalization.latin-historic.v1", step="normalization",
           capabilities={"unit": "page", "produces": ["normalized"]})
    preset(tmp_path, "other-step", "recomposition.by-script.v1",
           by_script={"*": "latin-historic@1"})
    problems = Catalog([tmp_path]).verify()
    assert any("latin-hebrew: by_script Latn" in p and "covers only ['Hebr']" in p for p in problems)
    assert any("unknown: by_script Hebr" in p and "no-such" in p for p in problems)
    assert any("other-step: by_script *" in p and "normalization preset" in p for p in problems)
    for bad in ({"Hebr": "hebrew-recomposition@1"}, {"Hebrew": "x@1", "*": "y@1"}, {"*": "unicode-recomposition"}):
        preset(tmp_path, "bad", "recomposition.by-script.v1", by_script=bad)
        with pytest.raises(CatalogError, match="by_script"):
            Catalog([tmp_path])
