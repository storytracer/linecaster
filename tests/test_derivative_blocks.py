"""Blocks moved in from the derivatives: filters with rejects, media, text variants, item texts,
Transcription.scaled, jobs helpers, PageRowReader with Parquet rows."""
from __future__ import annotations

import io
import json
import struct
import zlib
from pathlib import Path

import pytest
from datatrove.data import Document, Media, MediaType
from PIL import Image

from linecaster import text as T
from linecaster.blocks.base import page_of, set_page
from linecaster.blocks.filters import RejectSink, ValidatePages
from linecaster.blocks.media import AttachImage, WorkingImages
from linecaster.blocks.readers import PageRowReader
from linecaster.blocks.texts import ItemTexts
from linecaster.blocks.writers import PageParquetWriter
from linecaster.page import PAGE_KEY, Page, PageImage
from linecaster.transcription import Line, Region, Source, Transcription, Word


def _doc(page: Page, media: bytes | None = None) -> Document:
    d = Document(text="", id=page.page_id, metadata={},
                 media=[Media(id="m", type=MediaType.IMAGE, url="", media_bytes=media)] if media else [])
    set_page(d, page)
    return d


# ------------------------------------------------------------------ Transcription.scaled

def test_scaled_scales_everything_and_copies():
    t = Transcription(
        regions=[Region(id="r", label="text", polygon=[[10, 20], [30, 20], [30, 40]], bbox=[10, 20, 20, 20])],
        lines=[Line(id="l", region_id="r", bbox=[10, 20, 20, 10], polygon=[[10, 20], [30, 30]],
                    baseline=[[10, 28], [30, 28]], words=[Word(id="w", text="a", bbox=[10, 20, 5, 10]),
                                                          Word(id="v", text="b")])],
        source=Source(image_width=100, image_height=50))
    s = t.scaled(2.0, 3.0)
    assert s.regions[0].polygon == [[20, 60], [60, 60], [60, 120]] and s.regions[0].bbox == [20, 60, 40, 60]
    ln = s.lines[0]
    assert ln.bbox == [20, 60, 40, 30] and ln.polygon == [[20, 60], [60, 90]] and ln.baseline == [[20, 84], [60, 84]]
    assert ln.words[0].bbox == [20, 60, 10, 30] and ln.words[1].bbox is None
    assert (s.source.image_width, s.source.image_height) == (200, 150) and s.source.extra["scale"] == [2.0, 3.0]
    assert t.lines[0].bbox == [10, 20, 20, 10]                       # the original is untouched
    assert s.scaled(0.5).source.extra["scale"] == [1.0, 1.5]
    assert Transcription(lines=[Line(id="x", text="t")]).scaled(2).lines[0].bbox is None


# ------------------------------------------------------------------ filters

def test_reject_sink_and_validate_pages(tmp_path: Path):
    good = Page(page_id="i_1", item_id="i", image=PageImage(uri="x"))
    no_image = Page(page_id="i_2", item_id="i")
    broken = Document(text="", id="i_3", metadata={PAGE_KEY: {"page_id": 3}})
    docs = [_doc(good), _doc(no_image), broken]
    out = list(ValidatePages(str(tmp_path), required=("image",)).run(iter(docs)))
    assert [d.id for d in out] == ["i_1"]
    rows = [json.loads(x) for x in (tmp_path / "validate_00000.jsonl").read_text().splitlines()]
    assert [(r["key"], r["field"]) for r in rows] == [("i_2", "image"), ("i_3", "page_id")]
    assert all({"key", "field", "error", "raw_value"} <= set(r) for r in rows)
    with RejectSink(str(tmp_path), rank=3) as sink:
        pass
    assert not (tmp_path / "00003.jsonl").exists()                 # no rejects, no file


# ------------------------------------------------------------------ media

def _forged_png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    data = bytearray(buf.getvalue())
    data[16:24] = struct.pack(">II", w, h)
    data[29:33] = struct.pack(">I", zlib.crc32(bytes(data[12:29])) & 0xFFFFFFFF)
    return bytes(data)


def test_working_images_and_attach(tmp_path: Path):
    Image.new("RGB", (60, 40), (10, 200, 30)).save(tmp_path / "a.tif", compression="tiff_lzw")
    (tmp_path / "big.png").write_bytes(_forged_png(20000, 10))
    before = (tmp_path / "a.tif").read_bytes()
    pages = [Page(page_id="b_1", item_id="b", image=PageImage(uri=str(tmp_path / "a.tif"))),
             Page(page_id="b_2", item_id="b", image=PageImage(uri=str(tmp_path / "big.png"))),
             Page(page_id="b_3", item_id="b")]
    out = list(WorkingImages(str(tmp_path / "webp"), str(tmp_path / "rejects")).run(iter(map(_doc, pages))))
    assert [d.id for d in out] == ["b_1"] and out[0].media == []
    img = page_of(out[0]).image
    assert img.format == "webp" and (img.width, img.height) == (60, 40) and img.uri.endswith("webp/b/b_1.webp")
    assert img.extra["original"]["format"] == "tiff" and img.pixels_sha256
    assert (tmp_path / "a.tif").read_bytes() == before                # the delivery is only read
    rejects = [json.loads(x) for x in (tmp_path / "rejects" / "00000.jsonl").read_text().splitlines()]
    assert [(r["key"], r["field"]) for r in rejects] == [("b_2", "image"), ("b_3", "image")]
    assert "16383" in rejects[0]["error"]
    attached = list(AttachImage().run(iter(out)))
    assert Image.open(io.BytesIO(attached[0].media[0].media_bytes)).getpixel((3, 3)) == (10, 200, 30)


# ------------------------------------------------------------------ text

def test_normalise_never_nfkc():
    assert T.normalise("Weſen ﬁnden ﬂ ﬀ ﬃ ﬄ ﬅ ﬆ ꝛecht Ꝛ") == "Wesen finden fl ff ffi ffl st st recht R"
    assert T.normalise("Muͤller Koͤnig Gaͤrten Uͤber eͤ") == "Müller König Gärten Über eͤ"
    assert T.normalise("Æsop œuvre søster år Straße ½ x² ¹") == "Æsop œuvre søster år Straße ½ x² ¹"
    assert T.normalise("é") == "é"


def test_join_lines():
    assert T.join_lines("Entwicklungs-", "geschichte") == "Entwicklungsgeschichte"
    assert T.join_lines("Nord-", "Amerika") == "Nord-Amerika"
    assert T.join_lines("rufe¬", "scentibus") == "rufescentibus"
    assert T.join_lines("a -", "b") == "a - b" and T.join_lines("", "b") == "b"


def _page(regions, start=0) -> Transcription:
    t, n = Transcription(), 0
    for i, (rid, label, lines) in enumerate(regions):
        t.regions.append(Region(id=rid, label=label, polygon=[[0, 0], [1, 0], [1, 1]], bbox=[0, 0, 1, 1],
                                reading_order=i))
        for k, s in enumerate(lines):
            t.lines.append(Line(id=f"{rid}{k}", region_id=rid, reading_order=n, row=k, text=s))
            n += 1
    return t


def test_variants():
    p1 = _page([("h", "page_header", ["12 KAPITEL"]), ("t", "title", ["Vom Weſen"]),
                ("s", "section_header", ["Erſter Theil"]), ("a", "text", ["Die Unter-", "ſuchung der"]),
                ("f", "page_footer", ["12"])])
    p2 = _page([("h", "page_header", ["KAPITEL 13"]), ("a", "text", ["Kaͤfer zeigt.", "# Neuer Satz"]),
                ("l", "list_item", ["erſtens"]), ("p", "picture", [])])
    v = T.variants([p1, p2])
    assert v["verbatim_txt"] == ("12 KAPITEL\nVom Weſen\nErſter Theil\nDie Unter-\nſuchung der\n12\f"
                                 "KAPITEL 13\nKaͤfer zeigt.\n# Neuer Satz\nerſtens")
    assert v["readable_txt"] == "Vom Wesen\n\nErster Theil\n\nDie Untersuchung der Käfer zeigt. # Neuer Satz\n\nerstens"
    assert v["readable_md"] == ("# Vom Wesen\n\n## Erster Theil\n\nDie Untersuchung der Käfer zeigt. # Neuer Satz\n\n"
                                "- erstens")
    assert T.variants([_page([("a", "text", ["Ende."])]), _page([("a", "text", ["neu"])])])["readable_txt"] == "Ende.\n\nneu"
    assert T.variants([_page([("a", "text", ["# kein Titel"])])])["readable_md"] == "\\# kein Titel"
    assert T.verbatim([Transcription(), p2]).startswith("\fKAPITEL")


def test_item_texts_block():
    docs = []
    for item, seqs in (("b1", [2, 1]), ("b2", [1])):
        for s in seqs:
            p = Page(page_id=f"{item}_{s}", item_id=item, sequence=s, metadata={"item_page_count": len(seqs)})
            p.transcriptions["ocr"] = _page([("a", "text", [f"Seite {s}"])])
            docs.append(_doc(p))
    out = list(ItemTexts(token_counter=len).run(iter(docs)))
    assert [(d.id, d.metadata["variant"]) for d in out] == [
        ("b1", "verbatim_txt"), ("b1", "readable_txt"), ("b1", "readable_md"),
        ("b2", "verbatim_txt"), ("b2", "readable_txt"), ("b2", "readable_md")]
    assert out[0].text == "Seite 1\fSeite 2" and out[1].text == "Seite 1 Seite 2"
    assert out[0].metadata["page_ids"] == ["b1_1", "b1_2"] and out[0].metadata["token_count"] == len(out[0].text)
    assert out[2].metadata["format"] == "text/markdown" and out[1].metadata["fidelity"] == "normalised"
    with pytest.raises(ValueError):
        ItemTexts(variants=("nope",))


# ------------------------------------------------------------------ readers

def test_page_row_reader_reads_parquet_rows_with_errors(tmp_path: Path):
    p = Page(page_id="x_1", item_id="x", image=PageImage(uri=str(tmp_path / "missing.png")))
    d = _doc(p)
    d.metadata["errors"] = [{"step": "layout", "error": "boom"}]
    w = PageParquetWriter(str(tmp_path / "rows"))
    for _ in w.run(iter([d])):
        pass
    docs = list(PageRowReader(str(tmp_path / "rows"), glob_pattern="*.parquet", fetch_images=False).run())
    assert docs[0].id == "x_1" and docs[0].text == "" and docs[0].metadata["errors"][0]["error"] == "boom"
    assert page_of(docs[0]).item_id == "x"


# ------------------------------------------------------------------ jobs

def test_jobs_dependencies_and_wheel_volume(monkeypatch):
    from linecaster import jobs

    deps = jobs.dependencies("abc123")
    assert deps[0] == "linecaster @ https://github.com/storytracer/linecaster/archive/abc123.tar.gz"
    assert "opencv-contrib-python @ https://github.com/storytracer/linecaster/archive/abc123.tar.gz#subdirectory=stubs/opencv-contrib-python" in deps
    assert "kraken @ git+https://github.com/storytracer/kraken@3d235ee8" in deps and "pillow==12.3.0" in deps
    assert jobs.dependencies("abc123", engines=None) == deps[:1]
    vol = jobs.wheel_volume("hf://buckets/ns/runs/run-1/wheels")
    assert vol == {"type": "bucket", "source": "ns/runs", "mount_path": "/wheels", "read_only": True,
                   "path": "run-1/wheels"}

    import huggingface_hub
    seen = {}

    class J:
        id, url = "j", "u"

    monkeypatch.setattr(huggingface_hub, "run_uv_job", lambda *a, **k: (seen.update(k), J())[1])
    ex = jobs.WheelJobsExecutor([lambda d, r, w: d], tasks=1, logging_dir="hf://buckets/ns/runs/x",
                                dependencies=["d"], volumes=[vol])
    ex._submit_array_index(0, "hf://buckets/ns/runs/x/executor.pik", "token")
    assert [v.to_dict()["mountPath"] for v in seen["volumes"]] == ["/wheels"]
    assert huggingface_hub.run_uv_job.__name__ == "<lambda>"     # the wrapper is removed again
