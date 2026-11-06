"""The blocks of the rule-based steps on their engines: a preset or an engine spec with options over it, in-process
only, a step record per call (engine, preset edition and hash, seconds, datetime), the page and the item unit, and
``BindItem`` on the same engines."""
from __future__ import annotations

import pytest

from conftest import page_doc, page_t
from linecaster.backends import InProcess, Served
from linecaster.blocks.base.item import ITEM_KEY, gather, item_pages, new_item_document
from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding import BindItem
from linecaster.blocks.composition import Composer, Recomposer, Typographer
from linecaster.blocks.text import CharacterNormalizer
from linecaster.blocks.writers import ItemDocumentWriter
from linecaster.catalog.registry import catalog
from linecaster.errors import PipelineConfigError


def run(blocks, docs):
    for b in blocks:
        docs = b(docs)
    return list(docs)


def test_a_preset_or_an_engine_spec_with_options_over_it():
    by_preset = Typographer("ratios@1")
    assert by_preset.backend.preset == "ratios@1" and by_preset.backend.preset_sha256 == catalog().resolve(
        "ratios@1").sha256
    spec = Typographer(InProcess("linecaster.engines:RatiosTypographyEngine", demote=1.0), options={"split": 2.0})
    assert spec.backend.kwargs == {"demote": 1.0, "split": 2.0} and spec.backend.overrides == {"split": 2.0}
    assert spec.backend.preset is None
    over = Composer("docling-composition@1", options={"sections": True})
    assert over.backend.kwargs == {"sections": True} and over.backend.overrides == {"sections": True}
    with pytest.raises(PipelineConfigError, match="no Served backend"):
        Typographer(Served("http://127.0.0.1:1/v1", model="typography"))
    with pytest.raises(PipelineConfigError, match="is a composition preset"):
        Typographer("docling-composition@1")
    with pytest.raises(PipelineConfigError, match="no_such"):
        Typographer("ratios@1", options={"no_such": 1})
    with pytest.raises(PipelineConfigError, match="is a typography engine"):
        Composer(InProcess("linecaster.engines:RatiosTypographyEngine"))
    with pytest.raises(PipelineConfigError):
        Recomposer("unicode-recomposition@1", unit="book")


def test_each_block_records_its_step():
    (doc,) = run([Typographer("ratios@1"), Recomposer("unicode-recomposition@1"),
                  CharacterNormalizer("latin-historic@1"), Composer("docling-composition@1")], [page_doc()])
    t = page_of(doc).transcriptions["ocr_new"]
    steps = [(s.step, s.engine, s.preset) for s in t.steps]
    assert steps == [("typography", "typography.ratios.v1", "ratios@1"),
                     ("recomposition", "recomposition.unicode.v1", "unicode-recomposition@1"),
                     ("normalization", "normalization.latin-historic.v1", "latin-historic@1"),
                     ("composition", "composition.docling.v1", "docling-composition@1")]
    assert all({"seconds", "datetime"} <= set(s.measurements) and s.preset_sha256 for s in t.steps)
    assert t.paragraphs and all(p.normalized is not None for p in t.paragraphs)
    assert t.docling["name"] == "p1"


def _item_docs():
    pages = [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
             page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]
    docs = [page_doc(page_id=f"b1-{n}", item="b1", t=t, seq=n) for n, t in enumerate(pages, start=1)]
    for d in docs:
        d.metadata["page"]["metadata"]["item_page_count"] = 2
    return docs


@pytest.mark.parametrize("text", ["lines", "reflow"])
@pytest.mark.parametrize("sections", [False, True])
def test_item_blocks_bind_as_bind_item_does(text, sections, tmp_path):
    """Item records through ``Recomposer(unit="item")`` and ``Composer(unit="item")``: the document ``BindItem``
    makes, written by the same writer."""
    (bound,) = list(BindItem(text=text, sections=sections).run(iter(reversed(_item_docs()))))
    items = [new_item_document(item, pages) for item, pages in gather(reversed(_item_docs()), Typographer("ratios@1"))]
    blocks = [*([Recomposer("unicode-recomposition@1", unit="item")] if text == "reflow" else []),
              Composer("docling-composition@1", unit="item", options={"sections": sections})]
    (item,) = run(blocks, items)
    assert item.id == "b1" and item.metadata["docling"] == bound.metadata["docling"]
    assert item.metadata["region_of"] == bound.metadata["region_of"] and item.text == bound.text
    pages = item_pages(item)
    assert [p.page_id for p in pages] == ["b1-1", "b1-2"] and item.metadata[ITEM_KEY]["item_id"] == "b1"
    steps = [[s.step for s in p.transcriptions["ocr_new"].steps] for p in pages]
    assert steps == [(["recomposition"] if text == "reflow" else []) + ["composition"]] * 2
    if text == "reflow":
        first, second = (p.transcriptions["ocr_new"] for p in pages)
        assert first.paragraphs[1].continues.page_id == "b1-2" and second.paragraphs[0].continues_from.page_id == "b1-1"
    list(ItemDocumentWriter(str(tmp_path / "a"), formats=("md", "json")).run(iter([item])))
    list(ItemDocumentWriter(str(tmp_path / "b"), formats=("md", "json")).run(iter([bound])))
    for name in ("b1.md", "b1.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_bind_item_recomposes_the_item_anew():
    """Pages recomposed one by one carry their own paragraphs; BindItem recomposes the item (continued across the
    page break) and, in lines mode, composes from the lines."""
    docs = run([Recomposer("unicode-recomposition@1")], _item_docs())
    assert all(page_of(d).transcriptions["ocr_new"].paragraphs for d in docs)
    (flowed,) = list(BindItem(text="reflow").run(iter(docs)))
    (fresh,) = list(BindItem(text="reflow").run(iter(_item_docs())))
    assert flowed.metadata["docling"] == fresh.metadata["docling"]
    assert "turned to the north" in flowed.text
    (laid_out,) = list(BindItem(text="lines").run(iter(docs)))
    (fresh,) = list(BindItem(text="lines").run(iter(_item_docs())))
    assert laid_out.metadata["docling"] == fresh.metadata["docling"] and "turned to\nthe north" not in laid_out.text
    assert all(page_of(d).transcriptions["ocr_new"].steps[-1].step == "recomposition" for d in docs)   # untouched
