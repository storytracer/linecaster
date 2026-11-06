"""Sample pages for tests: a synthetic page image with printed lines at known boxes, its layout, its datatrove
document, and a realistic transcription that exercises every serializer feature."""
from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from ..data import Line, Region, Source, Transcription, Word

#: the lines a sample page prints by default
SAMPLE_LINES = ("The species described here", "were collected in the summer", "of 1887 by the author.",
                "Plate IV shows the flowers.")
#: the name of the transcription a sample document carries
SAMPLE_TRANSCRIPTION = "ocr_new"


def _texts(lines: int | Sequence[str]) -> list[str]:
    if isinstance(lines, int):
        return [SAMPLE_LINES[k % len(SAMPLE_LINES)] for k in range(lines)]
    return list(lines)


def box(x: float, y: float, w: float, h: float) -> list[list[float]]:
    """Returns the polygon of the box ``x, y, w, h`` (four corners, clockwise from the top left).

    Args:
        x, y, w, h: the box's left, top, width and height in pixels.
    """
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def sample_boxes(width: int = 800, height: int = 400, lines: int | Sequence[str] = 4) -> list[list[float]]:
    """Returns the boxes (``[x, y, width, height]``) a sample page prints its lines in, top to bottom.

    The lines sit in one column with margins of a tenth of the page; each line is one slot high, with a slot of
    space above and below (``2 * n + 1`` slots in the page's height).

    Args:
        width, height: the page's size in pixels.
        lines: the number of lines, or their texts.
    """
    n = max(len(_texts(lines)), 1)
    slot = height / (2 * n + 1)
    x, w = round(width / 10), width - 2 * round(width / 10)
    return [[float(x), float(round(slot * (2 * k + 1))), float(w), float(round(slot))] for k in range(n)]


def sample_page(width: int = 800, height: int = 400, lines: int | Sequence[str] = 4) -> Image.Image:
    """Returns a synthetic page image: black lines of text printed on white at the ``sample_boxes``.

    Args:
        width, height: the page's size in pixels.
        lines: the number of lines (texts from ``SAMPLE_LINES``), or their texts.
    """
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for text, (x, y, _, h) in zip(_texts(lines), sample_boxes(width, height, lines)):
        font = ImageFont.load_default(size=max(int(h * 0.75), 6))
        draw.text((x, y), text, fill="black", font=font)
    return image


def sample_png(width: int = 800, height: int = 400, lines: int | Sequence[str] = 4, fmt: str = "PNG") -> bytes:
    """Returns ``sample_page`` as an image file's bytes.

    Args:
        width, height, lines: as ``sample_page``.
        fmt: the image format Pillow writes (``PNG``, ``WEBP``, ``JPEG``, ...).
    """
    buf = io.BytesIO()
    sample_page(width, height, lines).save(buf, format=fmt)
    return buf.getvalue()


def sample_layout(width: int = 800, height: int = 400, lines: int | Sequence[str] = 4,
                  text: bool = False) -> Transcription:
    """Returns the transcription of a sample page's layout: one text region around its lines, the lines at their
    boxes.

    The region is ``text_0``; the lines are ``text_0_l<k>`` with their box, polygon, baseline, row and reading
    order; with ``text`` also their text and a confidence, and their words.

    Args:
        width, height, lines: as ``sample_page``.
        text: the lines carry their printed text (a recognized page); without it geometry only.
    """
    texts, boxes = _texts(lines), sample_boxes(width, height, lines)
    x0, y0 = boxes[0][0], boxes[0][1]
    x1, y1 = boxes[-1][0] + boxes[-1][2], boxes[-1][1] + boxes[-1][3]
    region = Region(id="text_0", label="text", raw_label="text", polygon=box(x0, y0, x1 - x0, y1 - y0),
                    bbox=[x0, y0, x1 - x0, y1 - y0], score=1.0, reading_order=0)
    out = []
    for k, (t, (x, y, w, h)) in enumerate(zip(texts, boxes)):
        line = Line(id=f"text_0_l{k}", region_id="text_0", reading_order=k, row=k, bbox=[x, y, w, h],
                    polygon=box(x, y, w, h), baseline=[[x, y + 0.8 * h], [x + w, y + 0.8 * h]])
        if text:
            line.text, line.confidence = t, 0.99
            step = w / max(len(t), 1)
            pos = 0
            for j, word in enumerate(t.split()):
                start = t.index(word, pos)
                pos = start + len(word)
                line.words.append(Word(id=f"{line.id}_w{j}", text=word, confidence=0.99,
                                       bbox=[x + start * step, y, len(word) * step, h]))
        out.append(line)
    return Transcription(regions=[region], lines=out, source=Source(image_width=width, image_height=height))


def sample_document(page_id: str = "item1_0001", width: int = 800, height: int = 400,
                    lines: int | Sequence[str] = 4, item_id: str | None = "item1", sequence: int | None = 1,
                    transcription: Transcription | None = None, name: str = SAMPLE_TRANSCRIPTION, fmt: str = "PNG"):
    """Returns the datatrove ``Document`` of a sample page: its image bytes as media and its page record.

    The page record names the image (``/scans/<page_id>.<ext>``, its size, format and hash), the item and the
    sequence; with ``transcription`` it carries that transcription under ``name`` and the document's ``text`` is its
    text.

    Args:
        page_id: the page's id.
        width, height, lines: as ``sample_page``.
        item_id: the page's item; ``None``: a page without item.
        sequence: the page's position in its item.
        transcription: the transcription the page carries; ``None``: none.
        name: the name of that transcription.
        fmt: the image format of the media (``PNG``, ``WEBP``, ...).
    """
    from ..blocks.base.page import new_page_document, page_of, set_page

    data = sample_png(width, height, lines, fmt)
    doc = new_page_document(page_id, data, uri=f"/scans/{page_id}.{fmt.lower()}", item_id=item_id,
                            sequence=sequence)
    if transcription is not None:
        page = page_of(doc)
        page.transcriptions[name] = transcription
        set_page(doc, page, name)
    return doc


def sample_documents(n: int = 2, item_id: str = "item1", text: bool = True, **kwargs) -> list:
    """Returns ``n`` sample documents of one item, in order, each with a recognized layout (``sample_layout``).

    Args:
        n: the number of pages.
        item_id: their item.
        text: the lines carry their text (``sample_layout(text=...)``).
        **kwargs: ``width``, ``height``, ``lines``, ``fmt`` as ``sample_document``.
    """
    size = {k: kwargs[k] for k in ("width", "height", "lines") if k in kwargs}
    return [sample_document(f"{item_id}_{k:04d}", item_id=item_id, sequence=k,
                            transcription=sample_layout(text=text, **size), **kwargs) for k in range(1, n + 1)]


def sample_transcription() -> Transcription:
    """Returns a realistic transcription that exercises every serializer feature.

    Five regions (a page header, a title with a heading level, body text, a picture, a footnote) and eight lines:
    with polygons and baselines or boxes only, recognized, empty, not yet recognized, a line without a region, words
    with confidences, a hyphen and alternatives; a 1600 x 2400 page.
    """
    regions = [
        Region(id="page_header_0", label="page_header", raw_label="header", reading_order=0,
               polygon=[[120.0, 80.0], [1480.0, 80.0], [1480.0, 140.0], [120.0, 140.0]],
               bbox=[120.0, 80.0, 1360.0, 60.0], score=0.91),
        Region(id="doc_title_1", label="title", raw_label="doc_title", reading_order=1,
               polygon=[[300.4, 200.2], [1300.7, 198.9], [1302.1, 330.5], [298.0, 331.6]],
               bbox=[298.0, 198.9, 1004.1, 132.7], score=0.873, heading_level=1),
        Region(id="text_2", label="text", raw_label="text", reading_order=2,
               polygon=[[118.0, 400.0], [1490.5, 400.0], [1490.5, 700.25], [118.0, 700.25]],
               bbox=[118.0, 400.0, 1372.5, 300.25], score=0.95),
        Region(id="image_3", label="picture", raw_label="image", reading_order=3,
               polygon=[[200.0, 760.0], [1400.0, 760.0], [1400.0, 1500.0], [200.0, 1500.0]],
               bbox=[200.0, 760.0, 1200.0, 740.0], score=0.88),
        Region(id="footnote_4", label="footnote", raw_label="footnote", reading_order=4,
               polygon=[[120.0, 1900.0], [1480.0, 1900.0], [1480.0, 2000.0], [120.0, 2000.0]],
               bbox=[120.0, 1900.0, 1360.0, 100.0]),
    ]
    lines = [
        Line(id="l0", region_id="page_header_0", reading_order=0, row=0, bbox=[130.0, 85.0, 400.0, 50.0],
             baseline=[[130.0, 125.0], [530.0, 126.0]], text="12 THE BOTANIST", confidence=0.97,
             words=[Word(id="l0_w0", text="12", bbox=[130.0, 86.0, 40.0, 40.0], confidence=0.99),
                    Word(id="l0_w1", text="THE", bbox=[190.0, 86.0, 90.0, 40.0], confidence=0.96),
                    Word(id="l0_w2", text="BOTANIST", bbox=[300.0, 86.0, 230.0, 40.0], confidence=0.95)]),
        Line(id="l1", region_id="doc_title_1", reading_order=1, row=0, bbox=[310.25, 210.5, 980.5, 110.75],
             polygon=[[310.25, 210.5], [1290.75, 209.0], [1290.75, 321.25], [310.25, 322.0]],
             baseline=[[312.5, 300.25], [800.0, 301.5], [1288.0, 302.75]], score=0.8125,
             text="Flora of the Northern Hills", confidence=0.884,
             words=[Word(id="l1_w0", text="Flora", bbox=[312.0, 215.0, 200.0, 100.0], confidence=0.9),
                    Word(id="l1_w1", text="of", bbox=[530.0, 215.0, 70.0, 100.0], confidence=0.8),
                    Word(id="l1_w2", text="the", bbox=[620.0, 215.0, 120.0, 100.0], confidence=0.85),
                    Word(id="l1_w3", text="Northern", bbox=[760.0, 215.0, 300.0, 100.0], confidence=0.9),
                    Word(id="l1_w4", text="Hills", bbox=[1080.0, 215.0, 200.0, 100.0], confidence=0.88,
                         alternatives=["Hilis"])]),
        Line(id="l2", region_id="text_2", reading_order=2, row=0, bbox=[120.0, 405.0, 1360.0, 60.0],
             polygon=[[120.0, 405.0], [1480.0, 405.0], [1480.0, 465.0], [120.0, 465.0]],
             baseline=[[120.0, 455.0], [1480.0, 455.0]],
             text="The species described here were col-", confidence=0.93,
             words=[Word(id="l2_w0", text="The", bbox=[120.0, 410.0, 80.0, 50.0], confidence=0.99),
                    Word(id="l2_w1", text="species", bbox=[215.0, 410.0, 170.0, 50.0], confidence=0.97),
                    Word(id="l2_w2", text="described", bbox=[400.0, 410.0, 220.0, 50.0], confidence=0.95),
                    Word(id="l2_w3", text="here", bbox=[635.0, 410.0, 100.0, 50.0], confidence=0.9),
                    Word(id="l2_w4", text="were", bbox=[750.0, 410.0, 110.0, 50.0], confidence=0.92),
                    Word(id="l2_w5", text="col-", bbox=[875.0, 410.0, 90.0, 50.0], confidence=0.71,
                         hyphen=True)]),
        # boxes only, recognized: no polygon, no baseline, no words
        Line(id="l3", region_id="text_2", reading_order=3, row=1, bbox=[120.0, 475.0, 1300.0, 60.0],
             text="lected in the summer of 1887 by the author.", confidence=0.9),
        # empty text line (recognized as empty)
        Line(id="l4", region_id="text_2", reading_order=4, row=2, bbox=[120.0, 545.0, 1300.0, 60.0],
             baseline=[[120.0, 595.0], [1420.0, 595.0]], text="", confidence=0.5),
        # not recognized yet (text None)
        Line(id="l5", region_id="text_2", reading_order=5, row=3, bbox=[120.0, 615.0, 1300.0, 60.0],
             polygon=[[120.0, 615.0], [1420.0, 615.0], [1420.0, 675.0], [120.0, 675.0]]),
        # a line without a region (an orphan row from the line step)
        Line(id="orphan_0", region_id=None, reading_order=6, row=0, bbox=[1500.0, 1600.0, 80.0, 300.0],
             baseline=[[1540.0, 1600.0], [1540.0, 1900.0]], text="Plate IV", confidence=0.66,
             words=[Word(id="orphan_0_w0", text="Plate", bbox=[1500.0, 1600.0, 80.0, 180.0], confidence=0.7),
                    Word(id="orphan_0_w1", text="IV", bbox=[1500.0, 1800.0, 80.0, 100.0], confidence=0.6)]),
        Line(id="l7", region_id="footnote_4", reading_order=7, row=0, bbox=[130.0, 1910.0, 1000.0, 40.0],
             baseline=[[130.0, 1945.0], [1130.0, 1945.0]], text="1 See  Gray, Manual.", confidence=0.8,
             words=[Word(id="l7_w0", text="1", bbox=[130.0, 1912.0, 20.0, 36.0]),
                    Word(id="l7_w1", text="See", bbox=[160.0, 1912.0, 70.0, 36.0], confidence=0.85),
                    Word(id="l7_w2", text="Gray,", bbox=[250.0, 1912.0, 110.0, 36.0], confidence=0.83),
                    Word(id="l7_w3", text="Manual.", bbox=[375.0, 1912.0, 160.0, 36.0], confidence=0.77)]),
    ]
    return Transcription(regions=regions, lines=lines,
                         source=Source(image_width=1600, image_height=2400, uri="page_0001.webp"))
