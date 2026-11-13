"""``Binder`` and ``Splitter``: pages into item records and back, and the parts the builder carries across them."""
from __future__ import annotations

from conftest import page_doc, page_t
from linecaster.blocks.base.item import item_pages
from linecaster.blocks.base.page import page_of
from linecaster.blocks.binding import Binder, Splitter
from linecaster.blocks.composition import Composer, Recomposer
from linecaster.blocks.conversion import ImageFetcher
from linecaster.blocks.readers import ImageFolderReader, PageRecordReader
from linecaster.blocks.writers import ItemDocumentWriter, ItemTextWriter, PageFileWriter, PageJsonlWriter
from linecaster.runtime.builder import build


def _docs(item="b1", count=True):
    pages = [page_t(1, ["It was a dark and stormy night when the", "ship left the harbour and turned to"], "CHAPTER I"),
             page_t(2, ["the north, where the ice waited.", "Nobody spoke."])]
    docs = [page_doc(page_id=f"{item}-{n}", item=item, t=t, seq=n) for n, t in enumerate(pages, start=1)]
    for d in docs:
        if count:
            d.metadata["page"].setdefault("metadata", {})["item_page_count"] = 2
    return docs


def test_the_binder_gathers_each_item_in_order():
    b = Binder()
    stream = [*reversed(_docs("b1")), *_docs("b2", count=False)]
    items = list(b.run(iter(stream)))
    assert [d.id for d in items] == ["b1", "b2"]                  # b1 as soon as its two pages are in
    assert [[p.page_id for p in item_pages(d)] for d in items] == [["b1-1", "b1-2"], ["b2-1", "b2-2"]]
    assert all(d.metadata["item"]["item_id"] == d.id and not d.media for d in items)
    assert b.stats["items"].total == 2 and b.stats["pages"].total == 4
    partial = Binder()
    assert [d.id for d in partial.run(iter(_docs("b3")[:1]))] == ["b3"]
    assert partial.stats["incomplete_items"].total == 1


def test_the_splitter_passes_on_the_pages_with_what_the_item_added():
    (item,) = list(Recomposer("unicode-recomposition@1", unit="item").run(Binder().run(iter(_docs()))))
    pages = list(Splitter().run(iter([item])))
    assert [d.id for d in pages] == ["b1-1", "b1-2"]
    first, second = (page_of(d).transcriptions["ocr_new"] for d in pages)
    body = next(p for p in first.paragraphs if p.region == "text_1")
    assert first.link(body.id, "runs_into") == "b1-2#text_1_p0"
    assert second.link(second.paragraphs[0].id, "continues") == f"b1-1#{body.id}"
    assert pages[0].text == first.text and first.annotators[-1].step == "recomposition"


def test_parts_carry_across_the_binder_and_the_splitter(tmp_path):
    """The item record holds its pages, so what the page blocks added is there for the item-unit blocks; the image
    bytes stay behind at the binder, the item's document at the splitter."""
    records = PageRecordReader("p", fetch_images=False, provides=["ocr_new:regions", "ocr_new:lines"])
    ok = [records, Binder(), Recomposer("unicode-recomposition@1", unit="item"),
          Composer("docling-composition@1", unit="item"), ItemDocumentWriter(str(tmp_path)),
          ItemTextWriter(str(tmp_path), variants=("verbatim_txt",)), Splitter(), PageJsonlWriter(str(tmp_path))]
    assert build(ok).problems == []
    plot = PageFileWriter(str(tmp_path), formats=("plot",))
    assert build([ImageFolderReader("x"), Binder(), Splitter(), plot]).problems == [
        "PageFileWriter (🗂️ page files) reads image, which no block before it in the pipeline adds"]
    assert build([ImageFolderReader("x"), Binder(), Splitter(), ImageFetcher(), plot]).problems == []
    assert "reads document" in " ".join(build([ImageFolderReader("x"), Binder(), Composer(
        "docling-composition@1", unit="item"), Splitter(), Binder(), ItemDocumentWriter(str(tmp_path))]).problems)
