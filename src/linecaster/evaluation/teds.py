"""Tree-edit-distance similarity of tables (TEDS; Zhong, ShafieiBavani and Jimeno Yepes, 2020), as OmniDocBench
scores tables, computed by the Zhang–Shasha algorithm without a dependency (it gives the same optimal distance as
APTED).

A table is a tree built from its cells (``Table.cells``), not from HTML: ``table`` → one ``tr`` per row (by the
row a cell starts in) → one ``td`` per cell with its row and column spans and its content. Header cells are cells
(``th`` and ``thead`` are not distinguished, as OmniDocBench's normalization has it). Inserting or deleting a node
costs 1; renaming costs 1 between nodes of different tags or spans, else the normalized edit distance of the two
cells' contents (``content``: the caller's comparison, after its strategy and lane, in its unit; 0 for TEDS-S, the
structure alone). ``TEDS = 1 - distance / max(nodes)``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from linecaster.data.transcription import Table


@dataclass
class Node:
    tag: str
    span: tuple[int, int] = (1, 1)
    content: str = ""
    children: list["Node"] = field(default_factory=list)


def tree(table: Table, text: Callable[[str], str] = lambda s: s) -> Node:
    """``table`` as its tree (module docstring); ``text`` writes each cell's content as it is compared."""
    rows: dict[int, list] = {}
    for c in sorted(table.cells, key=lambda c: (c.start_row, c.start_col)):
        rows.setdefault(c.start_row, []).append(Node("td", (c.end_row - c.start_row, c.end_col - c.start_col),
                                                     text(" ".join((c.text or "").split()))))
    return Node("table", children=[Node("tr", children=cells) for _, cells in sorted(rows.items())])


def _postorder(root: Node) -> tuple[list[Node], list[int]]:
    """The nodes in postorder and each one's leftmost leaf descendant (its postorder index)."""
    nodes: list[Node] = []
    lmd: list[int] = []

    def walk(n: Node) -> int:
        first = None
        for c in n.children:
            leftmost = walk(c)
            if first is None:
                first = leftmost
        nodes.append(n)
        lmd.append(first if first is not None else len(nodes) - 1)
        return lmd[-1]

    walk(root)
    return nodes, lmd


def distance(a: Node, b: Node, rename: Callable[[Node, Node], float]) -> float:
    """The tree edit distance of ``a`` and ``b`` (Zhang and Shasha, 1989), unit insertions and deletions."""
    na, la = _postorder(a)
    nb, lb = _postorder(b)
    kr_a = sorted({max(i for i in range(len(na)) if la[i] == v) for v in set(la)})
    kr_b = sorted({max(j for j in range(len(nb)) if lb[j] == v) for v in set(lb)})
    td = [[0.0] * len(nb) for _ in range(len(na))]
    for i in kr_a:
        for j in kr_b:
            li, lj = la[i], lb[j]
            m, n = i - li + 2, j - lj + 2
            fd = [[0.0] * n for _ in range(m)]
            for x in range(1, m):
                fd[x][0] = fd[x - 1][0] + 1
            for y in range(1, n):
                fd[0][y] = fd[0][y - 1] + 1
            for x in range(1, m):
                for y in range(1, n):
                    ia, jb = li + x - 1, lj + y - 1
                    if la[ia] == li and lb[jb] == lj:
                        fd[x][y] = min(fd[x - 1][y] + 1, fd[x][y - 1] + 1, fd[x - 1][y - 1] + rename(na[ia], nb[jb]))
                        td[ia][jb] = fd[x][y]
                    else:
                        p, q = la[ia] - li, lb[jb] - lj
                        fd[x][y] = min(fd[x - 1][y] + 1, fd[x][y - 1] + 1, fd[p][q] + td[ia][jb])
    return td[len(na) - 1][len(nb) - 1]


def _size(n: Node) -> int:
    return 1 + sum(_size(c) for c in n.children)


def teds(truth: Table, output: Table, text: Callable[[str], str] = lambda s: s, unit: str = "grapheme",
         structure_only: bool = False) -> float:
    """TEDS of ``output`` against ``truth`` (module docstring): 1 for equal tables, 0 for nothing alike; with
    ``structure_only`` TEDS-S, the cells' contents ignored."""
    from rapidfuzz.distance import Levenshtein

    from linecaster.evaluation.counts import units

    a, b = tree(truth, text), tree(output, text)

    def rename(x: Node, y: Node) -> float:
        if x.tag != y.tag or x.span != y.span:
            return 1.0
        if structure_only or x.tag != "td":
            return 0.0
        ux, uy = units(x.content, unit), units(y.content, unit)
        m = max(len(ux), len(uy))
        return Levenshtein.distance(ux, uy) / m if m else 0.0

    size = max(_size(a), _size(b))
    return 1.0 - distance(a, b, rename) / size if size else 1.0


__all__ = ["Node", "distance", "teds", "tree"]
