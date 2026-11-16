"""The vocabularies (``vocabularies/<scheme>.yaml``): they define exactly the data model's roles, statuses, reasons
and property schemes, validate their shape, are hashed in the index by their functional content, and agree with the
data model's tables in ``docs/reference/data-model.md``."""
import re
from pathlib import Path

import pytest

from linecaster.catalog import catalog
from linecaster.catalog.registry import Catalog, vocabulary_problems
from linecaster.catalog.vocabulary import VocabularyDoc
from linecaster.data import PROPERTIES, REASONS, ROLES, SCHEMES, STATUSES, Annotator, Transcription

DOCS = Path(__file__).resolve().parents[2] / "docs" / "reference" / "data-model.md"


def test_every_role_status_and_reason_has_its_definition_and_nothing_else():
    c = catalog()
    assert list(c.vocabulary("role").values) == list(ROLES)
    assert list(c.vocabulary("status").values) == list(STATUSES)
    assert list(c.vocabulary("status").reasons) == list(REASONS)
    for scheme in ("role", "status", "production", *PROPERTIES):
        v = c.vocabulary(scheme)
        for name, term in {**v.values, **v.reasons}.items():
            assert term.definition.strip().endswith("."), (scheme, name)
            assert term.counts or name == "no", (scheme, name)


def test_property_schemes_are_yes_no_with_answers_named_after_the_property():
    c = catalog()
    for scheme in PROPERTIES:
        v = c.vocabulary(scheme)
        assert tuple(v.values) == ("yes", "no") and v.property
        assert v.answers["no"] == f"not_{v.answers['yes']}"
        assert v.answer_values() == {v.answers["yes"]: "yes", v.answers["no"]: "no"}


def test_every_vocabulary_is_a_scheme_of_the_data_model():
    c = catalog()
    assert set(c.vocabularies) <= set(SCHEMES)
    assert {"role", "status", "production", *PROPERTIES} <= set(c.vocabularies)
    assert vocabulary_problems(c.dirs[0]) == []


def test_verify_names_a_vocabulary_that_differs_from_the_data_model(tmp_path):
    folder = tmp_path / "vocabularies"
    folder.mkdir()
    (folder / "status.yaml").write_text(
        "schema: linecaster.vocabulary\nscheme: status\ndescription: d\ntargets: [region]\n"
        "values:\n  illegible: {definition: x.}\n", encoding="utf-8")
    (folder / "colour.yaml").write_text(
        "schema: linecaster.vocabulary\nscheme: colour\ndescription: d\ntargets: [region]\n"
        "values:\n  red: {definition: x.}\n", encoding="utf-8")
    problems = vocabulary_problems(Catalog([tmp_path]).dirs[0])
    assert any("colour: no classification scheme" in p for p in problems)
    assert any("status: values differ" in p and "missing ['duplicate'" in p for p in problems)
    assert any("status: reasons differ" in p for p in problems)


@pytest.mark.parametrize("data, message", [
    ({"values": {"yes": {"definition": "x."}, "maybe": {"definition": "y."}}, "answers": {"yes": "a", "no": "b"}},
     "property scheme"),
    ({"values": {"yes": {"definition": "x."}, "no": {"definition": "y."}}, "answers": {"yes": "a", "no": "a"}},
     "distinct"),
    ({"values": {"yes": {"definition": "x."}, "no": {"definition": "y."}}, "answers": {"yes": "yes", "no": "b"}},
     "distinct"),
    ({"open": True}, "pattern"),
    ({"open": True, "pattern": "^x$", "values": {"a": {"definition": "x."}}}, "no values"),
    ({"values": {}}, "lists its values"),
    ({"values": {"A": {"definition": "x."}}}, "lowercase"),
    ({"values": {"a": {"definition": "x."}}, "reasons": {"r": {"definition": "y."}}}, "only status"),
    ({"values": {"a": {"definition": "x."}}, "targets": ["region", "line"]}, "narrowest first"),
])
def test_a_vocabulary_is_validated(data, message):
    doc = {"schema": "linecaster.vocabulary", "scheme": "thing", "description": "d", "targets": ["region"], **data}
    with pytest.raises(ValueError, match=message):
        VocabularyDoc.model_validate(doc)


def test_an_open_vocabulary_is_never_asked():
    v = VocabularyDoc.model_validate({"schema": "linecaster.vocabulary", "scheme": "script", "description": "d",
                                      "targets": ["line"], "open": True, "pattern": "^[A-Z][a-z]{3}$"})
    with pytest.raises(ValueError, match="open scheme"):
        v.answer_values()


def test_the_index_hashes_what_a_vocabulary_does_not_its_description():
    c = catalog()
    v = c.vocabulary("degraded")
    index = c.index_data(c.dirs[0], pipelines=False)
    assert index["vocabularies"]["degraded"] == c.vocabulary_sha256("degraded")
    changed = v.model_copy(update={"description": "another description", "provenance": ["elsewhere"]})
    assert changed.functional() == v.functional()
    term = v.values["yes"].model_copy(update={"definition": "Another definition."})
    other = v.model_copy(update={"values": {**v.values, "yes": term}})
    assert other.functional() != v.functional()


def test_a_property_scheme_takes_only_yes_and_no():
    t = Transcription()
    a = t.add_annotator(Annotator(step="tagging", name="x"))
    t.classify(a, "r1", "degraded", "yes")
    with pytest.raises(ValueError, match="property scheme"):
        t.classify(a, "r1", "degraded", "degraded")


def _table(heading: str) -> list[list[str]]:
    text = DOCS.read_text(encoding="utf-8")
    section = text.split(heading, 1)[1]
    rows = []
    for line in section.splitlines()[1:]:
        if line.startswith("#"):
            break
        if line.startswith("| `"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def test_the_data_model_docs_agree_with_the_vocabularies():
    roles = [re.match(r"`(\w+)`", r[0]).group(1) for r in _table("## Content roles")]
    assert roles == list(ROLES)
    schemes = [re.match(r"`(\w+)`", r[0]).group(1) for r in _table("### Classifications")]
    assert schemes == list(SCHEMES)
    rows = {re.match(r"`(\w+)`", r[0]).group(1): r for r in _table("### Classifications")}
    c = catalog()
    for scheme in ("production", "status"):
        assert re.findall(r"`(\w+)`", rows[scheme][1].split(";")[0]) == list(c.vocabulary(scheme).values)
