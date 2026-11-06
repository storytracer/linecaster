"""The page readers on datatrove's reader conventions (files distributed over tasks in turn, ``paths_file``,
``limit`` and ``skip`` per task; Parquet with an image column holding bytes, a Hugging Face image struct or a
path), and item shards: a first stage writes every page into its item's shard, a item stage reads whole shards."""
import io
from pathlib import Path

import pytest
from PIL import Image

from linecaster.blocks.base.page import image_bytes, new_page_document, page_of
from linecaster.blocks.readers.images import ImageFolderReader, ImageParquetReader
from linecaster.blocks.readers.records import PageRecordReader
from linecaster.errors import PageError, PipelineConfigError


def png(color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def item_folders(root: Path, sizes: dict[str, int]):
    for item, n in sizes.items():
        (root / item).mkdir(parents=True, exist_ok=True)
        for i in range(1, n + 1):
            (root / item / f"{item}_{i:04d}.png").write_bytes(png())


def read(reader, rank=0, world_size=1):
    return [(p.item_id, p.page_id) for p in map(page_of, reader.run(rank=rank, world_size=world_size))]


def test_paths_file_lists_image_files_distributed_in_turn(tmp_path):
    item_folders(tmp_path / "images", {"a": 2, "b": 1})
    (tmp_path / "pages.txt").write_text("a/a_0001.png\na/a_0002.png\nb/b_0001.png\n")
    r = lambda: ImageFolderReader(str(tmp_path / "images"), paths_file=str(tmp_path / "pages.txt"),  # noqa: E731
                                  item_from_parent=True)
    assert read(r(), 0, 2) == [("a", "a_0001"), ("b", "b_0001")]
    assert read(r(), 1, 2) == [("a", "a_0002")]
    with pytest.raises(PipelineConfigError, match="glob_pattern, not paths_file"):
        ImageFolderReader(str(tmp_path / "images"), paths_file=str(tmp_path / "pages.txt"), sequence=True)


def test_limit_and_skip_count_pages_per_task(tmp_path):
    item_folders(tmp_path, {"a": 3, "b": 3})
    r = ImageFolderReader(str(tmp_path), item_from_parent=True, limit=2, skip=1)
    assert [pid for _, pid in read(r)] == ["a_0002", "a_0003"]


def test_no_images_is_an_error(tmp_path):
    with pytest.raises(PipelineConfigError, match="No images"):
        list(ImageFolderReader(str(tmp_path)).run())


def test_parquet_with_bytes_structs_and_paths(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "x.png").write_bytes(png("red"))
    absolute = str(tmp_path / "img" / "y.png")
    Path(absolute).write_bytes(png("blue"))
    (tmp_path / "data").mkdir()
    table = pa.table({"id": ["p1", "p2", "p3", "p4"],
                      "image": [{"bytes": png("green"), "path": None}, {"bytes": None, "path": "x.png"},
                                {"bytes": None, "path": absolute}, {"bytes": None, "path": None}],
                      "book": ["b1", "b1", "b2", "b2"], "seq": [1, 2, 1, 2], "note": ["n1", "n2", "n3", "n4"]})
    pq.write_table(table.slice(0, 3), tmp_path / "data" / "part-0.parquet")
    reader = ImageParquetReader(str(tmp_path / "data"), item_key="book", sequence_key="seq",
                                image_folder=str(tmp_path / "img"), read_metadata=True)
    docs = list(reader.run())
    pages = [page_of(d) for d in docs]
    assert [(p.page_id, p.item_id, p.sequence) for p in pages] == [("p1", "b1", 1), ("p2", "b1", 2), ("p3", "b2", 1)]
    assert [Image.open(io.BytesIO(image_bytes(d))).getpixel((0, 0)) for d in docs] == [(0, 128, 0), (255, 0, 0),
                                                                                       (0, 0, 255)]
    assert pages[1].image.uri.endswith("img/x.png") and pages[2].image.uri == absolute
    assert pages[0].metadata["note"] == "n1"
    pq.write_table(table.slice(3), tmp_path / "data" / "part-1.parquet")
    with pytest.raises(PageError, match="neither image bytes nor an image path"):
        list(ImageParquetReader(str(tmp_path / "data"), item_key="book", image_folder=str(tmp_path / "img")).run())


def test_item_shards_bring_an_items_pages_together(tmp_path):
    """Stage 1: four tasks each read some pages of three items and write them into item shards. Stage 2: two
    tasks read whole shards, so each item's pages all arrive in one task, and the Binder emits it whole."""
    from linecaster.blocks.binding import Binder
    from linecaster.blocks.writers.records import PageJsonlWriter
    from linecaster.blocks.writers.shards import item_shard

    pages = [new_page_document(f"{b}_{i}", png(), item_id=b) for b in ("a", "b", "c") for i in range(1, 5)]
    for rank in range(4):                                      # pages handed out in turn, as datatrove does
        with PageJsonlWriter(str(tmp_path / "pages"), item_shards=3) as w:
            for doc in pages[rank::4]:
                w.write(doc, rank)
    shards = {item_shard(b, 3) for b in "abc"}
    assert {p.name for p in (tmp_path / "pages").iterdir()} == shards
    seen = {}
    for rank in range(2):
        for doc in PageRecordReader(str(tmp_path / "pages"), fetch_images=False, item_shards=True).run(rank=rank,
                                                                                                     world_size=2):
            seen.setdefault(page_of(doc).item_id, set()).add(rank)
    assert set(seen) == {"a", "b", "c"} and all(len(ranks) == 1 for ranks in seen.values())
    items = list(Binder().run(PageRecordReader(str(tmp_path / "pages"), fetch_images=False, item_shards=True).run()))
    assert sorted((d.id, len(d.metadata["item"]["pages"])) for d in items) == [("a", 4), ("b", 4), ("c", 4)]


OLD_RECORD = Path(__file__).with_name("records-before-phase-1.jsonl")
PAGE_1_RECORD = Path(__file__).with_name("records-page-1.jsonl")


def test_page_records_carry_their_format(tmp_path):
    import gzip
    import json

    from linecaster.blocks.writers.records import PageJsonlWriter, PageParquetWriter
    from linecaster.data.page import PAGE_SCHEMA

    doc = new_page_document("b_0001", png(), uri="b_0001.png", item_id="b")
    with PageJsonlWriter(str(tmp_path / "jsonl")) as w:
        w.write(doc, 0)
    (row,) = [json.loads(x) for x in gzip.open(tmp_path / "jsonl" / "00000.jsonl.gz", "rt")]
    assert PAGE_SCHEMA == "linecaster.page/2" and list(row)[:2] == ["schema", "id"] and row["schema"] == PAGE_SCHEMA
    with PageParquetWriter(str(tmp_path / "parquet")) as w:
        w.write(doc, 0)
    for folder in ("jsonl", "parquet"):
        glob = "**/*.parquet" if folder == "parquet" else "**/*.jsonl*"
        (back,) = PageRecordReader(str(tmp_path / folder), glob_pattern=glob, fetch_images=False).run()
        assert page_of(back).page_id == "b_0001"


def test_page_records_of_format_1(tmp_path):
    """A ``linecaster.page/1`` record named a transcription's steps ``model`` (``ModelInfo``); they are read as
    ``steps``, from JSONL and Parquet alike."""
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.readers.records import upgrade
    from linecaster.data.page import PAGE_SCHEMA

    row = json.loads(PAGE_1_RECORD.read_text())
    assert row["schema"] == "linecaster.page/1" and all("model" in t for t in row["page"]["transcriptions"].values())
    (tmp_path / "jsonl").mkdir()
    (tmp_path / "jsonl" / "00000.jsonl").write_text(PAGE_1_RECORD.read_text())
    (tmp_path / "parquet").mkdir()
    pq.write_table(pa.Table.from_pylist([{**row, "page": json.dumps(row["page"])}]), tmp_path / "parquet" / "0.parquet")
    pages = [page_of(doc) for folder, glob in (("jsonl", "**/*.jsonl*"), ("parquet", "**/*.parquet"))
             for doc in PageRecordReader(str(tmp_path / folder), glob_pattern=glob, fetch_images=False).run()]
    assert pages[0] == pages[1]
    new, original = pages[0].transcriptions["ocr_new"], pages[0].transcriptions["ocr_original"]
    assert [(m.step, m.name, m.preset) for m in new.steps] == [
        ("layout", "PP-DocLayoutV3", "pp-doclayoutv3@1"), ("recognition", "kraken-ppocrv6-medium", "kraken-ppocrv6-medium@1")]
    assert new.steps[0].measurements == {"seconds": 0.12, "datetime": "2026-11-04T10:00:00Z"}
    assert [m.name for m in original.steps] == ["ABBYY FineReader"] and new.paragraphs == []
    assert upgrade(row)["schema"] == PAGE_SCHEMA == "linecaster.page/2"


def test_parquet_page_records_keep_errors_after_a_page_without(tmp_path):
    """datatrove takes a Parquet file's schema from its first row unless one is given: a page's errors must survive
    a first page that had none."""
    from linecaster.blocks.writers.records import PageParquetWriter

    ok = new_page_document("b_0001", png(), uri="b_0001.png", item_id="b")
    bad = new_page_document("b_0002", png(), uri="b_0002.png", item_id="b")
    bad.metadata["errors"] = [{"block": "LineRecognizer", "type": "RuntimeError", "error": "no lines"}]
    with PageParquetWriter(str(tmp_path / "parquet")) as w:
        w.write(ok, 0)
        w.write(bad, 0)
    back = {d.id: d for d in PageRecordReader(str(tmp_path / "parquet"), glob_pattern="**/*.parquet",
                                              fetch_images=False).run()}
    assert "errors" not in back["b_0001"].metadata
    assert back["b_0002"].metadata["errors"][0]["error"] == "no lines"


def test_page_records_from_before_phase_1(tmp_path):
    """A record without ``schema`` is the format before phase 1: linecaster's transcription was ``ocr`` (now
    ``ocr_new``), and the run folder kept the records in ``rows/`` (now ``pages/``)."""
    import json
    import shutil

    from linecaster.blocks.readers.records import upgrade

    old = json.loads(OLD_RECORD.read_text())
    assert "schema" not in old and list(old["page"]["transcriptions"]) == ["ocr"]
    (tmp_path / "OUT" / "rows").mkdir(parents=True)
    shutil.copy(OLD_RECORD, tmp_path / "OUT" / "rows" / "00000.jsonl")
    (doc,) = PageRecordReader(str(tmp_path / "OUT" / "pages"), fetch_images=False).run()   # pages/: rows/ is read
    page = page_of(doc)
    assert list(page.transcriptions) == ["ocr_new"] and doc.text == "Die Untersuchung"
    t = page.transcriptions["ocr_new"]
    assert [w.text for w in t.lines[0].words] == ["Die", "Untersuchung"] and t.steps[0].preset == "kraken-ppocrv6-medium@1"
    assert t.steps[0].engine is None
    (same,) = PageRecordReader(str(tmp_path / "OUT" / "rows"), fetch_images=False).run()     # or named directly
    assert page_of(same) == page
    with pytest.raises(PipelineConfigError, match="unknown format 'linecaster.page/9'"):
        upgrade({"schema": "linecaster.page/9", "id": "x", "page": {}})
