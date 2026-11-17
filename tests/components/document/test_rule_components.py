"""The blocks of the rule-based steps on their engines: a preset or an engine spec with options over it, in-process
only, an annotator per call (engine, preset edition and hash, seconds, datetime), the page and the item unit."""
from __future__ import annotations

import pytest

from conftest import page_doc, page_t
from linecaster.backends import InProcess, Served
from linecaster.core.item import ITEM_KEY, item_pages
from linecaster.core.page import page_of
from linecaster.components.items import ItemAssembler
from linecaster.components.document import DocumentComposer
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.writers import ItemDocumentWriter
from linecaster.catalog.registry import catalog
from linecaster.errors import PipelineConfigError
from linecaster.text.recomposition import paragraphs


def run(blocks, docs):
    for b in blocks:
        docs = b(docs)
    return list(docs)


def test_a_preset_or_an_engine_spec_with_options_over_it():
    by_preset = HierarchyDetector("ratios")
    assert by_preset.backend.preset == "ratios" and by_preset.backend.preset_sha256 == catalog().resolve(
        "ratios").sha256
    spec = HierarchyDetector(InProcess("linecaster.engines:RatiosHierarchyEngine", demote=1.0), options={"split": 2.0})
    assert spec.backend.kwargs == {"demote": 1.0, "split": 2.0} and spec.backend.overrides == {"split": 2.0}
    assert spec.backend.preset is None
    over = DocumentComposer("linked-document", options={"sections": True})
    assert over.backend.kwargs == {"sections": True} and over.backend.overrides == {"sections": True}
    with pytest.raises(PipelineConfigError, match="no Served backend"):
        HierarchyDetector(Served("http://127.0.0.1:1/v1", model="hierarchy"))
    with pytest.raises(PipelineConfigError, match="is a document preset"):
        HierarchyDetector("linked-document")
    with pytest.raises(PipelineConfigError, match="no_such"):
        HierarchyDetector("ratios", options={"no_such": 1})
    with pytest.raises(PipelineConfigError, match="is a hierarchy engine"):
        DocumentComposer(InProcess("linecaster.engines:RatiosHierarchyEngine"))
    with pytest.raises(PipelineConfigError):
        ParagraphBuilder("unicode-paragraphs", unit="book")


def test_each_block_records_its_step():
    (doc,) = run([HierarchyDetector("ratios"), ParagraphBuilder("unicode-paragraphs"), DocumentComposer("linked-document")],
                 [page_doc()])
    t = page_of(doc).transcriptions["ocr_new"]
    added = t.annotators[1:]                        # after the page's own (the layout's)
    steps = [(s.kind, s.step, s.engine, s.preset) for s in added]
    assert steps == [("rule", "hierarchy", "hierarchy.ratios.v1", "ratios"),
                     ("rule", "paragraphs", "paragraphs.unicode.v1", "unicode-paragraphs")]  # composing adds none
    assert all({"seconds", "datetime"} <= set(s.measurements) and s.preset_sha256 for s in added)
    assert t.paragraphs and all(p.annotator == 2 for p in t.paragraphs)
    assert not t.edits                              # no step writes text: a strategy does, when a text is written
    assert doc.metadata["document"]["name"] == "p1"


def _item_docs():
    pages = [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
             page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]
    docs = [page_doc(page_id=f"b1-{n}", item="b1", t=t, seq=n) for n, t in enumerate(pages, start=1)]
    for d in docs:
        d.metadata["page"].setdefault("metadata", {})["item_page_count"] = 2
    return docs


@pytest.mark.parametrize("recomposed", [False, True])
@pytest.mark.parametrize("sections", [False, True])
def test_item_blocks_compose_the_item(recomposed, sections, tmp_path):
    """Item records (``ItemAssembler``) through ``ParagraphBuilder(unit="item")`` and ``DocumentComposer(unit="item")``: one document per
    item, page ``n`` its ``n``-th page, paragraphs continued across the page break; without a recomposition as laid
    out."""
    blocks = [ItemAssembler(), *([ParagraphBuilder("unicode-paragraphs", unit="item")] if recomposed else []),
              DocumentComposer("linked-document", unit="item", options={"sections": sections})]
    (item,) = run(blocks, list(reversed(_item_docs())))
    assert item.id == "b1" and item.metadata["item_id"] == "b1" and item.metadata["document"]["blocks"]
    assert ("turned to\nthe north" in item.text) is recomposed           # literal: one paragraph, its rows
    assert any(b["section"] for b in item.metadata["document"]["blocks"]) is sections
    pages = item_pages(item)
    assert [p.page_id for p in pages] == ["b1-1", "b1-2"] and item.metadata[ITEM_KEY]["item_id"] == "b1"
    steps = [[s.step for s in p.transcriptions["ocr_new"].annotators[1:]] for p in pages]
    assert steps == [(["paragraphs"] if recomposed else [])] * 2          # composing adds none
    if recomposed:
        first, second = (p.transcriptions["ocr_new"] for p in pages)
        assert first.link(first.paragraphs[1].id, "runs_into") == f"b1-2#{second.paragraphs[0].id}"
        assert second.link(second.paragraphs[0].id, "continues") == f"b1-1#{first.paragraphs[1].id}"
    list(ItemDocumentWriter(str(tmp_path), texts=("literal:md", "literal:json")).run(iter([item])))
    assert (tmp_path / "literal" / "b1.md").read_text().startswith("#") and (tmp_path / "literal" / "b1.json").exists()


def test_the_item_recomposition_makes_the_paragraphs_anew():
    """Pages recomposed one by one carry their own paragraphs; the item-level recomposition makes them anew
    (continued across the page break), as from pages without any."""
    docs = run([ParagraphBuilder("unicode-paragraphs")], _item_docs())
    assert all(page_of(d).transcriptions["ocr_new"].paragraphs for d in docs)
    item = [ItemAssembler(), ParagraphBuilder("unicode-paragraphs", unit="item"), DocumentComposer("linked-document", unit="item")]
    (flowed,) = run(item, docs)
    (fresh,) = run(item, _item_docs())
    assert flowed.metadata["document"] == fresh.metadata["document"] and "turned to\nthe north" in flowed.text
    pages = [p.transcriptions["ocr_new"] for p in item_pages(flowed)]
    assert [sum(r.kind == "paragraph" for r in t.ranges) for t in pages] == [2 * len(paragraphs(t)) for t in pages]   # the earlier ones stay
    assert all(page_of(d).transcriptions["ocr_new"].annotators[-1].step == "paragraphs" for d in docs)   # untouched
