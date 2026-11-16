"""Content roles and rendering policies: labels as roles, region labels from roles, layers from rules, and the
default policy as the catalog's."""
from __future__ import annotations

import pytest

from linecaster.data import Annotator, RenderingPolicy, RenderingRule, Source, Transcription
from linecaster.data.policy import DEFAULT_POLICY, region_label, role_of_label
from linecaster.text.page import page_text


def test_the_default_policy_is_the_catalog_s():
    from linecaster.catalog.registry import catalog, rendering_policy

    assert rendering_policy("page-layers") == DEFAULT_POLICY
    c = catalog()
    assert DEFAULT_POLICY.ref in c.policies["page-layers"][0].read_index()["policies"]


def test_an_unknown_policy_is_refused():
    from linecaster.blocks.composition import Composer
    from linecaster.errors import CatalogError

    with pytest.raises(CatalogError):
        Composer("linked-composition", policy="nowhere")


@pytest.mark.parametrize("label,role,production", [
    ("text", "paragraph", None), ("section_header", "heading", None), ("page_header", "header", None),
    ("marginalia", "marginalia", None), ("handwritten_text", "paragraph", "handwritten"), ("seal", "seal", None)])
def test_labels_are_read_as_content_roles(label, role, production):
    assert role_of_label(label) == (role, production)


def _page() -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    for rid, role, y, text in (("r0", "page_number", 20, "12"), ("r1", "paragraph", 300, "Body."),
                               ("r2", "marginalia", 320, "Note."), ("r3", "page_number", 950, "13")):
        t.add_region(a, rid, [0, y, 100, 20], role=role)
        t.add_line(a, f"{rid}_l0", region=rid, text=text)
    t.add_order(a, ["r0", "r1", "r2", "r3"], [f"r{k}_l0" for k in range(4)])
    return t


def test_a_page_number_s_docling_label_follows_its_place():
    t = _page()
    assert (region_label(t, "r0"), region_label(t, "r3")) == ("page_header", "page_footer")


def test_a_policy_moves_marginalia_out_of_the_text():
    t = _page()
    assert page_text(t) == "12\nBody.\nNote.\n13"
    notes = RenderingPolicy(id="marginalia-apart", rules=[RenderingRule(role="marginalia", to="none")])
    assert page_text(t, notes) == "12\nBody.\n13"
    assert notes.layer("marginalia") == "none" and DEFAULT_POLICY.layer("marginalia") == "body"
    assert DEFAULT_POLICY.layer("header") == "furniture" and DEFAULT_POLICY.layer(None, motivation="describing") == \
        "metadata"


def _described() -> Transcription:
    from linecaster.data.transcription import Description

    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    t.add_region(a, "r0", [0, 0, 1000, 90], role="paragraph")
    t.add_line(a, "l0", region="r0", text="Before the figure.")
    t.add_region(a, "r1", [0, 100, 1000, 90], role="picture")
    t.add_region(a, "r2", [0, 200, 1000, 90], role="paragraph")
    t.add_line(a, "l1", region="r2", text="After the figure.")
    t.add_region(a, "r3", [0, 300, 1000, 90], role="picture")
    t.add_order(a, ["r0", "r1", "r2", "r3"], ["l0", "l1"])
    t.classify(a, "r3", "status", "suppressed")
    t.descriptions.append(Description(annotator=a, target="r1", text="A ship at sea."))
    t.descriptions.append(Description(annotator=a, target="r3", text="A suppressed picture."))
    t.descriptions.append(Description(annotator=a, target="", text="A page of a log book."))
    return t


def test_page_layers_described_renders_descriptions_after_their_region():
    from linecaster.catalog.registry import rendering_policy
    from linecaster.document import to_markdown
    from linecaster.document.builder import build_document
    from linecaster.scoring.elements import elements
    from linecaster.scoring.render import text

    t, described = _described(), rendering_policy("page-layers-described")
    assert text(t, "full") == "Before the figure.\nAfter the figure."              # by default, in the metadata
    assert text(t, "full", described) == ("Before the figure.\nA ship at sea.\nAfter the figure.\n"
                                          "A page of a log book.")
    assert [(e.kind, e.role, e.content) for e in elements(t, described)] == [
        ("text", "paragraph", "Before the figure."), ("description", "picture", "A ship at sea."),
        ("text", "paragraph", "After the figure."), ("description", None, "A page of a log book.")]
    assert [e.kind for e in elements(t)] == ["text", "text"]
    doc = build_document(t, policy=described)
    assert [(b.kind, b.role, b.text) for b in doc.blocks if b.role == "description"] == [
        ("paragraph", "description", "A ship at sea."), ("paragraph", "description", "A page of a log book.")]
    assert "A ship at sea.\n\nAfter the figure." in to_markdown(doc)
    assert not [b for b in build_document(t).blocks if b.role == "description"]
