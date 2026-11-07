"""XY-Cut++ reading order (``linecaster.data.geometry.xy_cut_plus_plus``) on synthetic pages, 1000 x 1400 pixels,
each with the order a reader follows; one page where plain XY-cut fails."""
import random

from linecaster.data.geometry import BBox
from linecaster.data.geometry.order import xy_cut_order
from linecaster.data.geometry.xy_cut_plus_plus import xy_cut_plus_plus_order

PAGE = (1000, 1400)


def order(regions, **kwargs):
    """The region names in XY-Cut++ order; ``regions``: name -> (label, x0, y0, x1, y1)."""
    names = list(regions)
    boxes = [BBox(*regions[n][1:]) for n in names]
    return [names[i] for i in xy_cut_plus_plus_order(boxes, [regions[n][0] for n in names], PAGE, **kwargs)]


def plain(regions):
    names = list(regions)
    return [names[i] for i in xy_cut_order([BBox(*regions[n][1:]) for n in names])]


def test_single_column():
    page = {"p2": ("text", 100, 420, 900, 700), "footer": ("page_footer", 480, 1340, 520, 1360),
            "title": ("title", 300, 120, 700, 160), "p1": ("text", 100, 200, 900, 400),
            "header": ("page_header", 450, 40, 550, 60), "p3": ("text", 100, 720, 900, 1000)}
    assert order(page) == ["header", "title", "p1", "p2", "p3", "footer"]


def test_two_columns_where_plain_xy_cut_fails():
    # the paragraph gaps of both columns line up, so a horizontal cut runs through both
    page = {"L1": ("text", 100, 100, 480, 500), "R1": ("text", 520, 100, 900, 500),
            "L2": ("text", 100, 520, 480, 1300), "R2": ("text", 520, 520, 900, 1300)}
    assert plain(page) == ["L1", "R1", "L2", "R2"]
    assert order(page) == ["L1", "L2", "R1", "R2"]


def test_title_and_cross_layout_paragraph_over_two_columns():
    page = {"R1": ("text", 520, 300, 900, 1000), "L1": ("text", 100, 300, 480, 700),
            "abstract": ("text", 100, 180, 900, 280), "T": ("title", 100, 100, 900, 160),
            "R2": ("text", 520, 1020, 900, 1300), "L2": ("text", 100, 720, 480, 1300)}
    assert order(page) == ["T", "abstract", "L1", "L2", "R1", "R2"]


def test_l_shaped_figure_across_the_gutter():
    # the figure reaches into the left column: no vertical cut and no horizontal cut for plain XY-cut
    page = {"L1": ("text", 100, 100, 480, 600), "F": ("picture", 450, 100, 900, 400),
            "R1": ("text", 520, 420, 900, 800), "L2": ("text", 100, 620, 480, 1300),
            "R2": ("text", 520, 820, 900, 1300)}
    assert plain(page) == ["L1", "F", "R1", "L2", "R2"]
    assert order(page) == ["L1", "L2", "F", "R1", "R2"]


def test_table_with_caption_between_two_column_parts():
    page = {"Tb": ("table", 150, 580, 850, 900), "L2": ("text", 100, 940, 480, 1300),
            "C": ("caption", 350, 540, 650, 570), "R1": ("text", 520, 100, 900, 500),
            "L1": ("text", 100, 100, 480, 500), "R2": ("text", 520, 940, 900, 1300)}
    assert order(page) == ["L1", "R1", "C", "Tb", "L2", "R2"]


def test_isolated_centered_title_cuts_the_page():
    page = {"L1": ("text", 100, 100, 480, 600), "R1": ("text", 520, 100, 900, 640),
            "T": ("section_header", 410, 680, 610, 720), "L2": ("text", 100, 760, 480, 1300),
            "R2": ("text", 520, 760, 900, 1300)}
    assert order(page) == ["L1", "R1", "T", "L2", "R2"]
    # without the pre-cut the masked title leaves the gutter free from top to bottom
    assert order(page, center_tolerance=0.0) == ["L1", "T", "L2", "R1", "R2"]


def test_page_header_footer_and_footnote():
    page = {"fn": ("footnote", 100, 1200, 480, 1260), "R1": ("text", 520, 100, 900, 1300),
            "header": ("page_header", 100, 30, 900, 60), "L1": ("text", 100, 100, 480, 1150),
            "footer": ("page_footer", 480, 1350, 520, 1370)}
    assert order(page) == ["header", "L1", "fn", "R1", "footer"]


def test_any_page_gives_a_deterministic_permutation():
    rng = random.Random(7)
    labels = ["text", "title", "section_header", "picture", "table", "caption", "footnote", "page_header",
              "page_footer", "list_item"]
    assert xy_cut_plus_plus_order([], [], PAGE) == []
    for _ in range(200):
        n = rng.randint(1, 25)
        boxes = []
        for _ in range(n):
            x0, y0 = rng.uniform(0, 900), rng.uniform(0, 1300)
            boxes.append(BBox(x0, y0, x0 + rng.uniform(1, 600), y0 + rng.uniform(1, 400)))
        lab = [rng.choice(labels) for _ in range(n)]
        out = xy_cut_plus_plus_order(boxes, lab, PAGE)
        assert sorted(out) == list(range(n))
        assert out == xy_cut_plus_plus_order(boxes, lab, PAGE)
