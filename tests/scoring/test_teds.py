"""Tree-edit-distance similarity of tables (``linecaster.scoring.teds``): Zhang–Shasha's distance, TEDS and TEDS-S
from a table's cells."""
from __future__ import annotations

import pytest

pytest.importorskip("rapidfuzz")

from linecaster.data.transcription import Cell, Table  # noqa: E402
from linecaster.scoring.teds import Node, distance, teds, tree  # noqa: E402


def _table(rows: list[list[str]], spans: dict | None = None) -> Table:
    cells = []
    for i, row in enumerate(rows):
        col = 0
        for text in row:
            r, c = (spans or {}).get((i, col), (1, 1))
            cells.append(Cell(start_row=i, end_row=i + r, start_col=col, end_col=col + c, text=text))
            col += c
    return Table(annotator=0, target="", num_rows=len(rows), num_cols=max(c.end_col for c in cells), cells=cells)


def test_zhang_shasha_gives_the_classic_example_s_distance():
    # f(d(a c(b)) e) against f(c(d(a b)) e): two edits (Zhang and Shasha, 1989)
    def node(tag, *children):
        return Node(tag, children=list(children))

    a = node("f", node("d", node("a"), node("c", node("b"))), node("e"))
    b = node("f", node("c", node("d", node("a"), node("b"))), node("e"))
    assert distance(a, b, lambda x, y: 0.0 if x.tag == y.tag else 1.0) == 2


def test_the_tree_is_one_row_per_starting_row_and_one_cell_per_cell():
    t = tree(_table([["a", "b"], ["c"]], spans={(1, 0): (1, 2)}))
    assert [len(r.children) for r in t.children] == [2, 1] and t.children[1].children[0].span == (1, 2)


def test_teds_is_one_for_equal_tables_and_less_for_other_cells_or_structure():
    truth = _table([["Name", "Year"], ["Ship", "1850"], ["Port", "1851"]])
    assert teds(truth, truth) == 1.0
    misread = _table([["Name", "Year"], ["Shop", "1850"], ["Port", "1851"]])
    assert 0.9 < teds(truth, misread) < 1.0 and teds(truth, misread, structure_only=True) == 1.0
    dropped = _table([["Name", "Year"], ["Ship", "1850"]])
    assert teds(truth, dropped) == pytest.approx(1 - 3 / 10)        # a row and its two cells of ten nodes
    merged = _table([["Name", "Year"], ["Ship 1850"], ["Port", "1851"]], spans={(1, 0): (1, 2)})
    assert teds(truth, merged, structure_only=True) < 1.0


def test_cell_contents_are_compared_as_the_caller_writes_them():
    truth, output = _table([["SHIP"]]), _table([["ship"]])
    assert teds(truth, output) < 1.0 and teds(truth, output, text=str.casefold) == 1.0


def test_the_distance_agrees_with_apted():
    apted = pytest.importorskip("apted")
    from apted.helpers import Tree

    def bracket(n: Node) -> str:
        return "{" + n.tag + "".join(bracket(c) for c in n.children) + "}"

    def node(tag, *children):
        return Node(tag, children=list(children))

    a = node("a", node("b", node("c"), node("d")), node("e"), node("f", node("g")))
    b = node("a", node("c"), node("b", node("d", node("e"))), node("g"))
    want = apted.APTED(Tree.from_text(bracket(a)), Tree.from_text(bracket(b))).compute_edit_distance()
    assert distance(a, b, lambda x, y: 0.0 if x.tag == y.tag else 1.0) == want
