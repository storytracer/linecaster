"""Reading order in any writing direction: boxes seen in a direction's frame, and every ordering helper (XY-cut,
XY-Cut++, slotting unordered regions, the assigner's rows, the recomposition's margins) ordering right-to-left
columns, vertical columns from the right and from the left, as it orders horizontal text left to right."""
from __future__ import annotations

import pytest

from linecaster.components.lines.line_assigner import order_rows
from linecaster.data import Annotator, Transcription
from linecaster.data.geometry import BBox
from linecaster.data.geometry.frames import framed, from_frame, to_frame
from linecaster.data.geometry.order import place_unordered, xy_cut_order
from linecaster.data.geometry.xy_cut_plus_plus import xy_cut_plus_plus_order
from linecaster.data.writing import DIRECTIONS
from linecaster.engines.paragraphs import in_direction
from linecaster.text.paragraphs import Row

# a page of two columns, two blocks each, not aligned across the columns
TWO_COLUMNS = [BBox(0, 0, 480, 400), BBox(520, 0, 1000, 600), BBox(0, 450, 480, 900), BBox(520, 650, 1000, 900)]
# three full-height columns
COLUMNS = [BBox(0, 0, 300, 1000), BBox(350, 0, 650, 1000), BBox(700, 0, 1000, 1000)]


@pytest.mark.parametrize("direction", [None, *DIRECTIONS])
def test_a_box_comes_back_from_its_frame(direction):
    b = BBox(10, 20, 110, 70)
    assert from_frame(to_frame(b, direction), direction) == b


def test_an_unknown_direction_is_refused():
    with pytest.raises(ValueError):
        to_frame(BBox(0, 0, 1, 1), "diagonal")


@pytest.mark.parametrize("direction,expected", [
    (None, [0, 2, 1, 3]),                   # the left column, then the right one
    ("horizontal-lr", [0, 2, 1, 3]),
    ("horizontal-rl", [1, 3, 0, 2]),        # the right column first
])
def test_xy_cut_reads_columns_in_the_direction(direction, expected):
    assert xy_cut_order(TWO_COLUMNS, direction=direction) == expected


@pytest.mark.parametrize("direction,expected", [("vertical-rl", [2, 1, 0]), ("vertical-lr", [0, 1, 2]),
                                                ("horizontal-lr", [0, 1, 2]), ("horizontal-rl", [2, 1, 0])])
def test_vertical_columns_are_read_from_their_side(direction, expected):
    assert xy_cut_order(COLUMNS, direction=direction) == expected


def test_xy_cut_plus_plus_reads_in_the_direction():
    boxes = [BBox(0, 0, 1000, 80), *[BBox(b.x0, b.y0 + 100, b.x1, b.y1 + 100) for b in TWO_COLUMNS]]
    labels = ["doc_title", "text", "text", "text", "text"]
    assert xy_cut_plus_plus_order(boxes, labels, (1000, 1000)) == [0, 1, 3, 2, 4]
    assert xy_cut_plus_plus_order(boxes, labels, (1000, 1000), direction="horizontal-rl") == [0, 2, 4, 1, 3]
    assert xy_cut_plus_plus_order(COLUMNS, ["text"] * 3, (1000, 1000), direction="vertical-rl") == [2, 1, 0]
    assert xy_cut_plus_plus_order(COLUMNS, ["text"] * 3, (1000, 1000), direction="vertical-lr") == [0, 1, 2]


class _Region:
    def __init__(self, bbox, order=None):
        self.bbox, self.order = bbox, order


def test_an_unordered_region_is_slotted_in_by_the_direction():
    def ranks(direction):
        regions = [_Region(TWO_COLUMNS[0], 0), _Region(TWO_COLUMNS[1], 1), _Region(BBox(0, 950, 1000, 990))]
        place_unordered(regions, direction)
        return [r.order for r in regions]

    assert ranks(None) == ranks("horizontal-rl") == [0, 1, 2]          # a footer last either way


def test_framed_objects_pass_their_attributes_through():
    r = _Region(BBox(0, 0, 10, 10), 3)
    (f,) = framed([r], "horizontal-rl")
    f.order = 5
    assert (r.order, f.bbox, framed([r], None)[0] is r) == (5, BBox(-10, 0, 0, 10), True)


def _lines(boxes):
    t = Transcription()
    a = t.add_annotator(Annotator(step="lines", name="test"))
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        t.add_line(a, f"l{k}", box=[x0, y0, x1 - x0, y1 - y0])
    return t.lines


def test_rows_run_in_the_direction():
    # two lines side by side on one row, a third below
    lines = _lines([(0, 0, 400, 40), (500, 0, 900, 40), (0, 60, 900, 100)])
    ids = lambda direction: [ln.id for ln in order_rows(lines, direction)[0]]       # noqa: E731
    assert ids(None) == ["l0", "l1", "l2"]
    assert ids("horizontal-rl") == ["l1", "l0", "l2"]
    # vertical lines (columns): three from the right, one below the rightmost
    columns = _lines([(800, 0, 840, 400), (700, 0, 740, 400), (600, 0, 640, 400), (800, 450, 840, 900)])
    assert [ln.id for ln in order_rows(columns, "vertical-rl")[0]] == ["l0", "l3", "l1", "l2"]
    assert [ln.id for ln in order_rows(columns, "vertical-lr")[0]] == ["l2", "l1", "l0", "l3"]


def test_recomposition_margins_follow_the_recorded_direction():
    rows = [Row("a", BBox(100, 0, 900, 40), 0), Row("b", None, 1)]
    assert in_direction(rows, False, None) == (rows, False)
    assert in_direction(rows, True, "vertical-rl") == (rows, True)          # the option overrides
    framed_rows, rtl = in_direction(rows, False, "horizontal-rl")
    assert (rtl, framed_rows[0].bbox, framed_rows[1].bbox) == (False, BBox(-900, 0, -100, 40), None)


@pytest.mark.parametrize("recorded,indented_at,paragraphs", [
    (True, "right", [["l0", "l1"], ["l2", "l3"]]),       # right to left: an indent from the right starts one
    (True, "left", [["l0", "l1", "l2", "l3"]]),
    (False, "left", [["l0", "l1"], ["l2", "l3"]]),
    (False, "right", [["l0", "l1", "l2", "l3"]]),
])
def test_paragraphs_start_at_an_indent_on_the_side_lines_start(recorded, indented_at, paragraphs):
    from linecaster.data import Source
    from linecaster.engines import UnicodeParagraphsEngine

    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    if recorded:
        t.classify(a, "", "direction", "horizontal-rl")
    t.add_region(a, "r0", [100, 100, 800, 400], role="paragraph")
    for i, s in enumerate(["الحمد لله رب العالمين الرحمن", "الرحيم مالك يوم الدين.", "إياك نعبد وإياك نستعين",
                           "اهدنا الصراط المستقيم"]):
        x0, x1 = (200 if i == 2 and indented_at == "left" else 100), (800 if i == 2 and indented_at == "right"
                                                                      else 900)
        t.add_line(a, f"l{i}", [x0, 100 + i * 50, x1 - x0, 40], region="r0", text=s)
    t.add_order(a, ["r0"], [f"l{i}" for i in range(4)], [0, 1, 2, 3])
    UnicodeParagraphsEngine()([t])
    assert [[ln for row in p.rows for ln in row.lines] for p in t.paragraphs] == paragraphs
