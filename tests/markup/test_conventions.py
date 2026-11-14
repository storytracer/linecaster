"""Conventions: the format, layering, decisions, matchers and coverage."""
import pytest
from lxml import html
from pydantic import ValidationError

from linecaster.markup import Conventions, ConventionsDoc, TextMatcher, TreeMatcher, resolve
from linecaster.markup.decisions import Block, Remove, make
from linecaster.markup.resolve import ConventionsError


def doc(id, edition=1, rules=(), extends=None, disable=None, fmt="html"):
    return ConventionsDoc.model_validate({
        "schema": "linecaster.conventions/1", "id": id, "edition": edition, "format": fmt, "extends": extends,
        "description": f"{id} conventions", "rules": list(rules), "disable": disable or {}})


def rule(id, css, decision="remove", params=None, **kw):
    return {"id": id, "match": {"kind": "tree", "css": css}, "decision": decision,
            "params": params if params is not None else {"reason": "generated"}, "why": f"why {id}", **kw}


BASE = doc("base", rules=[rule("edit-links", ".edit"), rule("notes", ".note", "note", {}),
                          rule("heads", "h2", "block", {"role": "heading", "heading_level": 1})])


def entries(*docs):
    by = {d.ref: d for d in docs}
    return lambda ref: by[ref]


def test_a_child_replaces_adds_disables_and_places_rules():
    child = doc("site", 2, extends="base@1", disable={"notes": "the site has no notes"},
                rules=[rule("edit-links", ".edit, .editsection"),
                       rule("hidden", ".hide", "invisible", {}, before="edit-links"),
                       rule("captions", ".cap", "caption", {})])
    r = resolve("site@2", entries(BASE, child))
    assert r.chain == ("base@1", "site@2") and r.ref == "base@1>site@2"
    assert [x.id for x in r.rules] == ["hidden", "edit-links", "heads", "captions"]
    assert r.rule("edit-links").match.css == ".edit, .editsection"
    assert isinstance(r.decisions[2], Block) and r.decisions[2].heading_level == 1
    assert len(r.sha256) == 64 and r.sha256 != resolve("base@1", entries(BASE)).sha256


def test_documentation_does_not_change_the_hash():
    other = doc("base", rules=[{**rule("edit-links", ".edit"), "why": "said differently", "decided": "2026-11-14"},
                               rule("notes", ".note", "note", {}),
                               rule("heads", "h2", "block", {"role": "heading", "heading_level": 1})])
    assert resolve("base@1", entries(BASE)).sha256 == resolve("base@1", entries(other)).sha256


def test_resolution_refuses_what_it_cannot_resolve():
    with pytest.raises(ConventionsError, match="disables"):
        resolve("x@1", entries(BASE, doc("x", extends="base@1", disable={"nope": "?"})))
    with pytest.raises(ConventionsError, match="extends"):
        resolve("x@1", entries(BASE, doc("x", extends="base@1", fmt="xml")))
    with pytest.raises(ConventionsError, match="unknown decision"):
        resolve("x@1", entries(doc("x", rules=[rule("a", ".a", "teleport", {})])))
    with pytest.raises(ConventionsError, match="reason"):
        resolve("x@1", entries(doc("x", rules=[rule("a", ".a", params={"reason": "boredom"})])))
    with pytest.raises(ValidationError):
        doc("x", disable={"a": "no parent"})
    with pytest.raises(ValidationError):
        doc("x", extends="base")                              # not pinned
    with pytest.raises(ValidationError):
        doc("x", rules=[rule("a", ".a"), rule("a", ".b")])


def test_decisions_are_checked():
    assert make("remove", {"reason": "editorial"}) == Remove(reason="editorial")
    for name, params in (("block", {"role": "nonsense"}), ("edit", {"kind": "joined"}), ("remove", {})):
        with pytest.raises(ValidationError):
            make(name, params)


def test_tree_matches_conditions_and_coverage():
    page = html.fromstring('<div><p class="text">a <span class="edit">[edit]</span>'
                           '<span class="hide" style="visibility:hidden">x</span></p>'
                           '<div class="box"><span class="edit">[edit]</span></div><span class="other">y</span></div>')
    c = Conventions(resolve("x@1", entries(doc("x", rules=[
        rule("edit-outside-boxes", ".edit", "remove", {"reason": "generated"}, **{}),
        rule("hidden", "span", "invisible", {}),
    ]))), TreeMatcher())
    m = TreeMatcher()
    from linecaster.markup import TreeMatch
    assert len(m.select(page, TreeMatch(css=".edit", not_inside=".box"))) == 1
    assert len(m.select(page, TreeMatch(css="span", style="visibility"))) == 1
    assert len(m.select(page, TreeMatch(css="span", text=r"^y$"))) == 1
    decided, cov = c.decide(page)
    assert sorted(rid for rid, _ in decided.values()) == ["edit-outside-boxes"] * 2 + ["hidden"] * 2
    assert cov.matched == {"edit-outside-boxes": 2, "hidden": 2}
    assert cov.unmapped == {".text": 1, ".box": 1}
    assert cov.measurements()["unmapped"] == {".text": 1, ".box": 1}


def test_a_matcher_reads_only_its_match_kind():
    tree_rules = resolve("x@1", entries(doc("x", rules=[rule("a", ".a")])))
    with pytest.raises(ValueError, match="match kinds"):
        Conventions(tree_rules, TextMatcher())


def test_text_matches_name_their_span():
    t = TextMatcher()
    from linecaster.markup import TextMatch
    spans = t.select("a [sic] word\nnext [illegible] line", TextMatch(pattern=r"\[(?P<text>[a-z]+)\]"))
    assert [(s.text, s.start) for s in spans] == [("sic", 3), ("illegible", 19)]


def test_anchors_follow_verbatim_text_and_opaque_calls():
    pytest.importorskip("rapidfuzz")
    from linecaster.markup.anchors import SourceMap
    source = "First ''line'' here.\n{{head|Title}}\nSecond line."
    m = SourceMap().verbatim(source[:21], 0).opaque("TITLE", 21, 35).verbatim(source[35:], 35)
    a = m.anchors(["First line here.", "TITLE", "Second line.", "Not there"])
    assert source[a[0].start:a[0].end] == "First ''line'' here."
    assert (a[1].start, a[1].end) == (21, 35)
    assert source[a[2].start:a[2].end] == "Second line."
    assert a[3] is None
