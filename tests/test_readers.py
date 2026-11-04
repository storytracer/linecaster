"""The page readers on datatrove's reader conventions: books as the entries distributed over tasks (a
``paths_file`` of book folders, or found by glob), ``limit`` and ``skip`` per task, and Parquet with an image
column holding bytes, a Hugging Face image struct or a path."""
import io
from pathlib import Path

import pytest
from PIL import Image

from linecaster.blocks.base import image_bytes, page_of
from linecaster.blocks.readers import ImageFolderReader, ImageParquetReader


def png(color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def books(root: Path, sizes: dict[str, int]):
    for book, n in sizes.items():
        (root / book).mkdir(parents=True, exist_ok=True)
        for i in range(1, n + 1):
            (root / book / f"{book}_{i:04d}.png").write_bytes(png())


def read(reader, rank=0, world_size=1):
    return [(p.item_id, p.page_id, p.sequence) for p in map(page_of, reader.run(rank=rank, world_size=world_size))]


def test_paths_file_lists_books_and_keeps_them_whole(tmp_path):
    books(tmp_path / "images", {"a": 3, "b": 1, "c": 2})
    (tmp_path / "books.txt").write_text("a\nb\nc\n")
    r = lambda: ImageFolderReader(str(tmp_path / "images"), paths_file=str(tmp_path / "books.txt"), sequence=True)  # noqa: E731
    assert read(r(), 0, 2) == [("a", "a_0001", 1), ("a", "a_0002", 2), ("a", "a_0003", 3),
                               ("c", "c_0001", 1), ("c", "c_0002", 2)]
    assert read(r(), 1, 2) == [("b", "b_0001", 1)]


def test_globbed_books_by_parent_folder(tmp_path):
    books(tmp_path, {"a": 2, "b": 2, "c": 1})
    tasks = [read(ImageFolderReader(str(tmp_path), item_from_parent=True), rank, 2) for rank in (0, 1)]
    assert {item for task in tasks for item, _, _ in task} == {"a", "b", "c"}
    by_item = {item: rank for rank, task in enumerate(tasks) for item, _, _ in task}
    assert len(by_item) == 3 and sum(len(t) for t in tasks) == 5      # every page once, each book in one task


def test_limit_and_skip_count_pages_per_task(tmp_path):
    books(tmp_path, {"a": 3, "b": 3})
    r = ImageFolderReader(str(tmp_path), item_from_parent=True, limit=2, skip=1)
    assert [pid for _, pid, _ in read(r)] == ["a_0002", "a_0003"]


def test_flat_folder_is_page_by_page(tmp_path):
    for i in range(4):
        (tmp_path / f"p{i}.png").write_bytes(png())
    assert [pid for _, pid, _ in read(ImageFolderReader(str(tmp_path)), 1, 2)] == ["p1", "p3"]


def test_no_images_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="No images"):
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
    with pytest.raises(ValueError, match="neither image bytes nor an image path"):
        list(ImageParquetReader(str(tmp_path / "data"), item_key="book", image_folder=str(tmp_path / "img")).run())
