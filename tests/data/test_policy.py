"""Content roles and rendering policies: labels as roles, Docling labels from roles, layers from rules, and the
default policy as the catalog's released edition."""
from __future__ import annotations

import pytest

from linecaster.data import Annotator, RenderingPolicy, RenderingRule, Source, Transcription
from linecaster.data.policy import DEFAULT_POLICY, docling_label, role_of_label
from linecaster.text.variants import page_text


def test_the_default_policy_is_the_catalog_s_released_edition():
    from linecaster.catalog.registry import catalog, rendering_policy

    assert rendering_policy("page-layers@1") == DEFAULT_POLICY
    c = catalog()
    assert DEFAULT_POLICY.ref in c.policies["page-layers"][0].lock.policies


def test_an_unknown_policy_is_refused():
    from linecaster.blocks.composition import Composer
    from linecaster.errors import CatalogError

    with pytest.raises(CatalogError):
        Composer("docling-composition@1", policy="nowhere@1")


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
    assert (docling_label(t, "r0"), docling_label(t, "r3")) == ("page_header", "page_footer")


def test_a_policy_moves_marginalia_out_of_the_text():
    t = _page()
    assert page_text(t) == "12\nBody.\nNote.\n13"
    notes = RenderingPolicy(id="marginalia-apart", rules=[RenderingRule(role="marginalia", to="none")])
    assert page_text(t, notes) == "12\nBody.\n13"
    assert notes.layer("marginalia") == "none" and DEFAULT_POLICY.layer("marginalia") == "body"
    assert DEFAULT_POLICY.layer("header") == "furniture" and DEFAULT_POLICY.layer(None, motivation="describing") == \
        "metadata"
