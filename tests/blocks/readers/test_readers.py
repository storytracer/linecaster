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
    tasks read whole shards, so each item's pages all arrive in one task, and ItemTexts emits it whole."""
    from linecaster.blocks.binding.texts import ItemTexts
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
    texts = list(ItemTexts(variants=("verbatim_txt",)).run(
        PageRecordReader(str(tmp_path / "pages"), fetch_images=False, item_shards=True).run()))
    assert sorted((d.id, d.metadata["pages"]) for d in texts) == [("a", 4), ("b", 4), ("c", 4)]
