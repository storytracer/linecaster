"""Line-level ground truth end to end: a Parquet table of line images with their texts and languages, read by the
pipeline import_transcriptions (text-import with line_image, the language from a context column) into page records,
each a page whose one line is the whole image, and scored against a recognizer's lines with Unicode's word
boundaries."""
from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from linecaster.core.page import page_of
from linecaster.data import Annotator, Transcription
from linecaster.pipelines import import_transcriptions
from linecaster.runtime import run
from linecaster.runtime.builder import run_pages
from linecaster.scoring import score_page

ROWS = [("l1", "東京は晴れです", "ja", (640, 48)), ("l2", "כְּתֹבֶת עִבְרִית", "he", (520, 40)),
        ("l3", "The ship sailed.", "en", (700, 44))]


def _png(size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def test_line_images_and_their_texts_become_one_line_pages(tmp_path):
    table = pa.table({"id": [r[0] for r in ROWS], "image": [_png(r[3]) for r in ROWS], "text": [r[1] for r in ROWS],
                      "language": [r[2] for r in ROWS]})
    pq.write_table(table, tmp_path / "lines.parquet")
    ap = run.parser(None)
    import_transcriptions.options(ap)
    a = run.check(ap, ap.parse_args([str(tmp_path / "out"), "--parquet", str(tmp_path / "lines.parquet"),
                                     "--id-key", "id", "--data-key", "text", "--context-key", "language",
                                     "--importer", "text-import", "--set", "import.line_image=true", "--read-images"]))
    blocks, _ = import_transcriptions.pipeline(a, None)
    pages = {page_of(d).page_id: page_of(d).transcriptions["ground_truth"] for d in run_pages(blocks)}
    assert sorted(pages) == ["l1", "l2", "l3"]
    for pid, text, language, (w, h) in ROWS:
        t = pages[pid]
        (ln,) = t.lines
        assert (t.text_of(ln), ln.box, t.language(ln.id), t.source.kind) == (text, [0.0, 0.0, w, h], language,
                                                                             "ground_truth")
    # a recognizer's line of the same image, one character wrong
    ocr = Transcription(source=pages["l1"].source)
    a = ocr.add_annotator(Annotator(step="recognition", name="test"))
    ocr.add_line(a, "l0", [0, 0, 640, 48], text="東京は晴れでず")
    (row,) = score_page(pages["l1"], ocr, tokenizer="uax29")["rows"][:1]
    assert (row["s"], row["words"], row["words_true"], row["words_both"]) == (1, "uax29", 7, 6)
