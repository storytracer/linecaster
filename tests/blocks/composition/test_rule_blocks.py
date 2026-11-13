"""The blocks of the rule-based steps on their engines: a preset or an engine spec with options over it, in-process
only, an annotator per call (engine, preset edition and hash, seconds, datetime), the page and the item unit."""
from __future__ import annotations

import pytest

from conftest import page_doc, page_t
from linecaster.backends import InProcess, Served
from linecaster.blocks.base.item import ITEM_KEY, item_pages
from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding import Binder
from linecaster.blocks.composition import Composer, Recomposer, Typographer
from linecaster.blocks.text import CharacterNormalizer
from linecaster.blocks.writers import ItemDocumentWriter
from linecaster.catalog.registry import catalog
from linecaster.errors import PipelineConfigError
from linecaster.text.recomposition import paragraphs
from linecaster.text.variants import normalize


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
    added = t.annotators[1:]                        # after the page's own (the layout's)
    steps = [(s.kind, s.step, s.engine, s.preset) for s in added]
    assert steps == [("rule", "typography", "typography.ratios.v1", "ratios@1"),
                     ("rule", "recomposition", "recomposition.unicode.v1", "unicode-recomposition@1"),
                     ("rule", "normalization", "normalization.latin-historic.v1", "latin-historic@1")]   # composing adds none
    assert all({"seconds", "datetime"} <= set(s.measurements) and s.preset_sha256 for s in added)
    assert t.paragraphs and all(p.annotator == 2 for p in t.paragraphs)
    assert all(e.annotator == 3 and e.kind == "normalized" for e in t.edits)
    assert doc.metadata["docling"]["name"] == "p1"


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
    """Item records (``Binder``) through ``Recomposer(unit="item")`` and ``Composer(unit="item")``: one document per
    item, page ``n`` its ``n``-th page, paragraphs continued across the page break; without a recomposition as laid
    out."""
    blocks = [Binder(), *([Recomposer("unicode-recomposition@1", unit="item")] if recomposed else []),
              Composer("docling-composition@1", unit="item", options={"sections": sections})]
    (item,) = run(blocks, list(reversed(_item_docs())))
    assert item.id == "b1" and item.metadata["item_id"] == "b1" and item.metadata["region_of"]
    assert ("turned to the north" in item.text) is recomposed
    assert bool(item.metadata["docling"]["groups"]) is sections
    pages = item_pages(item)
    assert [p.page_id for p in pages] == ["b1-1", "b1-2"] and item.metadata[ITEM_KEY]["item_id"] == "b1"
    steps = [[s.step for s in p.transcriptions["ocr_new"].annotators[1:]] for p in pages]
    assert steps == [(["recomposition"] if recomposed else [])] * 2          # composing adds none
    if recomposed:
        first, second = (p.transcriptions["ocr_new"] for p in pages)
        assert first.link(first.paragraphs[1].id, "runs_into") == f"b1-2#{second.paragraphs[0].id}"
        assert second.link(second.paragraphs[0].id, "continues") == f"b1-1#{first.paragraphs[1].id}"
    list(ItemDocumentWriter(str(tmp_path), formats=("md", "json"), by_format=True).run(iter([item])))
    assert (tmp_path / "md" / "b1.md").read_text().startswith("#") and (tmp_path / "json" / "b1.json").exists()


def test_the_item_recomposition_makes_the_paragraphs_anew():
    """Pages recomposed one by one carry their own paragraphs; the item-level recomposition makes them anew
    (continued across the page break), as from pages without any."""
    docs = run([Recomposer("unicode-recomposition@1")], _item_docs())
    assert all(page_of(d).transcriptions["ocr_new"].paragraphs for d in docs)
    item = [Binder(), Recomposer("unicode-recomposition@1", unit="item"), Composer("docling-composition@1", unit="item")]
    (flowed,) = run(item, docs)
    (fresh,) = run(item, _item_docs())
    assert flowed.metadata["docling"] == fresh.metadata["docling"] and "turned to the north" in flowed.text
    pages = [p.transcriptions["ocr_new"] for p in item_pages(flowed)]
    assert [sum(r.kind == "paragraph" for r in t.ranges) for t in pages] == [2 * len(paragraphs(t)) for t in pages]   # the earlier ones stay
    assert all(page_of(d).transcriptions["ocr_new"].annotators[-1].step == "recomposition" for d in docs)   # untouched


def test_the_normalizer_on_item_records():
    (item,) = run([Binder(), Recomposer("unicode-recomposition@1", unit="item"),
                   CharacterNormalizer("latin-historic@1", unit="item")], _item_docs())
    for p in item_pages(item):
        t = p.transcriptions["ocr_new"]
        assert t.annotators[-1].preset == "latin-historic@1"
        assert paragraphs(t) and all((t.edit(x.id, ("normalized",)) or x.text) == normalize(x.text) for x in paragraphs(t))
    with pytest.raises(PipelineConfigError):
        CharacterNormalizer("latin-historic@1", unit="book")
