"""The builder: a pipeline (a list of blocks and composites) turned into stages, checked against the blocks'
contracts before anything runs (``docs/reference/pipelines.md``).

    plan = build(blocks, tasks=8, run_folder="OUT")
    plan.check()                    # PipelineConfigError listing every problem
    print(plan.mermaid())           # the graph: blocks, the parts between them, composites as subgraphs
    for stage in plan.stages:       # one datatrove pipeline each, run one after another
        LocalPipelineExecutor(stage.pipeline, tasks=stage.tasks, ...)

* **Checks** (all problems collected): the stage starts with a reader; every part a block reads is added earlier
  in its stage (or by the stage's reader) and not removed since (``removes``); a part is added by one block only
  unless a later block declares it in ``replaces``; units fit (a page block cannot follow an item stream); the parts carry across a binder and a
  splitter (an item record holds its pages), apart from the image bytes and the item's document; server blocks go
  last; a served model block whose endpoint is a server block of its stage finds its model there; a ``group`` of
  alternatives (``when=``) adds the same parts in every alternative.
* **Order** is the given one: the builder checks it and never reorders, except that the server blocks at the end
  go with the stage of the model blocks.
* **Branches**: a block with a ``when`` condition (``branch(block, when=..., group=...)``) processes the pages the
  condition accepts; the others pass unchanged. Blocks sharing a ``group`` are alternatives, one after another:
  a page goes through the first one whose condition accepts it (the last may be ``OTHERWISE``).
* **Composites** (``linecaster.blocks.base.composite.Composite``) expand into their blocks; the graph keeps the
  group.
* **Stages**: with ``tasks > 1``, the stream's change to items (a binder) cuts the pipeline: the first stage writes
  page records in item shards (``PageJsonlWriter(item_shards=N)`` into ``<run_folder>/pages``), the next reads
  whole shards (``PageRecordReader(item_shards=True)``). A splitter after it needs no cut: its items are whole.
* **Rejects**: with a run folder, a ``RejectWriter`` into ``<run_folder>/rejects`` goes before the first writer (or
  binder) unless the pipeline has one: it writes the pages that carry errors.
* **Converters**: a reader that brings a library's transcription file (``ManifestReader(existing_ocr=True)``) gets a
  ``TranscriptionConverter`` right after it, into ``ocr_original``, unless a block reads the file already. ``max_page_errors`` sets every page
  block's error budget.
* **Partial runs**: ``until`` keeps the blocks up to a block and writes page records; ``after`` starts from page
  records (the pipeline's ``PageRecordReader``) with the blocks after one; ``taps`` write page records after a
  block (``Tap`` observers). Blocks are named by their datatrove ``name``, their class name or their composite's
  name; a name that fits several blocks is a problem.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from ..blocks.base.composite import Composite
from ..blocks.base.contract import Contract, Part, contract_of
from ..errors import PipelineConfigError
from .observers import Boundary, Observer, Observers, Tap

#: where a page records which alternative of a group took it (removed after the group)
BRANCH_KEY = "linecaster_branch"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


# ------------------------------------------------------------------------------------------------ conditions

@runtime_checkable
class Condition(Protocol):
    """A picklable predicate on the page record (``linecaster.data.Page``), with a description for the plan."""

    def __call__(self, page) -> bool: ...

    def describe(self) -> str: ...


class Otherwise:
    """The last alternative of a group: every page no earlier alternative took."""

    def __call__(self, page) -> bool:
        return True

    def describe(self) -> str:
        return "otherwise"

    def __reduce__(self):
        return (_otherwise, ())


def _otherwise() -> Otherwise:
    return OTHERWISE


OTHERWISE = Otherwise()


class MetadataEquals:
    """Pages whose ``metadata[key]`` equals ``value``."""

    def __init__(self, key: str, value):
        self.key, self.value = key, value

    def __call__(self, page) -> bool:
        return page.metadata.get(self.key) == self.value

    def describe(self) -> str:
        return f"metadata.{self.key} == {self.value!r}"


def branch(block, when: Condition, group: str | None = None):
    """``block`` with a condition: it processes the pages ``when`` accepts, the others pass unchanged. Blocks with
    the same ``group`` are alternatives (one after another in the pipeline). Returns the block."""
    if not isinstance(when, Condition):
        raise PipelineConfigError(f"when= needs a Condition (a callable on the page record with describe()), got {when!r}")
    block.when, block.group = when, group
    return block


class Branch:
    """The datatrove step of a block with a condition (see ``branch``). A per-unit block gets the pages it takes
    one by one; any other block one stream of them, the pages it does not take passed on as soon as the block
    yields (a long run of pages it does not take is held until then)."""

    def __init__(self, block, when: Condition, group: str | None = None, label: str = "", last: bool = False):
        self.block, self.when, self.group, self.label, self.last = block, when, group, label, last

    def __getattr__(self, name):          # stats, backend, port, ...: the block's (executors and helpers look)
        if name == "block":
            raise AttributeError(name)
        return getattr(self.block, name)

    def _takes(self, doc) -> bool:
        from ..blocks.base.page import page_of

        taken = doc.metadata.get(BRANCH_KEY) or {}
        if self.group is not None and self.group in taken:
            return False
        if not self.when(page_of(doc)):
            return False
        if self.group is not None:
            doc.metadata.setdefault(BRANCH_KEY, {})[self.group] = self.label
        return True

    def _done(self, doc):
        if self.last and self.group is not None:
            taken = doc.metadata.get(BRANCH_KEY) or {}
            taken.pop(self.group, None)
            if not taken:
                doc.metadata.pop(BRANCH_KEY, None)
        return doc

    def __call__(self, data, rank: int = 0, world_size: int = 1):
        from ..blocks.base.block import warm

        warm(self.block)
        if getattr(self.block, "shape", None) == "unit" and hasattr(self.block, "process_page"):
            for doc in data:
                if self._takes(doc):
                    for out in self.block.run(iter([doc]), rank, world_size):
                        yield self._done(out)
                else:
                    yield self._done(doc)
            return
        from collections import deque

        passed: deque = deque()

        def taken():
            for doc in data:
                if self._takes(doc):
                    yield doc
                else:
                    passed.append(doc)

        for out in self.block.run(taken(), rank, world_size):
            while passed:
                yield self._done(passed.popleft())
            yield self._done(out)
        while passed:
            yield self._done(passed.popleft())

    def __repr__(self) -> str:
        return f"{self.block!r} when {self.when.describe()}"


# ------------------------------------------------------------------------------------------------ the plan

@dataclass
class Node:
    id: str
    block: str                         # class name
    name: str                          # datatrove name (or class name)
    role: str
    unit: str
    stage: int
    composites: tuple[str, ...] = ()
    group: str | None = None
    when: str | None = None


@dataclass
class Edge:
    source: str
    target: str
    parts: tuple[str, ...]


@dataclass
class Graph:
    """Nodes are blocks (composites expanded, their group kept), edges the parts a block reads, from the block
    that added them."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def mermaid(self, stage_names: list[str] | None = None) -> str:
        def q(text: str) -> str:
            return text.replace('"', "#quot;")

        lines = ["flowchart TD"]
        stages = sorted({n.stage for n in self.nodes})
        for s in stages:
            nodes = [n for n in self.nodes if n.stage == s]
            indent = "  "
            if len(stages) > 1:
                title = stage_names[s] if stage_names else f"stage {s + 1}"
                lines.append(f'  subgraph stage{s + 1}["{q(title)}"]')
                indent = "    "
            open_path: tuple[str, ...] = ()
            for n in nodes:
                common = 0
                while common < min(len(open_path), len(n.composites)) and open_path[common] == n.composites[common]:
                    common += 1
                for _ in open_path[common:]:
                    lines.append(indent + "  " * (len(open_path) - 1) + "end")
                    open_path = open_path[:-1]
                for c in n.composites[common:]:
                    open_path = (*open_path, c)
                    cid = f"c{s + 1}_" + "_".join("".join(ch if ch.isalnum() else "_" for ch in p) for p in open_path)
                    lines.append(indent + "  " * (len(open_path) - 1) + f'subgraph {cid}["{q(c)}"]')
                label = n.block if n.name == n.block else f"{n.block}<br/>{n.name}"
                if n.when:
                    label += f"<br/>when {n.when}"
                lines.append(indent + "  " * len(open_path) + f'{n.id}["{q(label)}"]')
            for _ in open_path:
                lines.append(indent + "  " * (len(open_path) - 1) + "end")
                open_path = open_path[:-1]
            if len(stages) > 1:
                lines.append("  end")
        incoming = {e.target for e in self.edges}
        for e in self.edges:
            lines.append(f'  {e.source} -->|"{q(", ".join(e.parts))}"| {e.target}')
        previous = None
        for n in self.nodes:             # blocks fed by no part: the order they run in
            if previous is not None and n.id not in incoming and previous.stage == n.stage:
                lines.append(f"  {previous.id} -.-> {n.id}")
            previous = n
        return "\n".join(lines)


@dataclass
class Stage:
    """One datatrove pipeline: ``blocks`` in order, ``pipeline`` the steps an executor runs (branch wrappers and
    observer boundaries included), ``tasks`` its tasks."""

    name: str
    tasks: int
    blocks: list
    pipeline: list
    observers: Observers | None = None


@dataclass
class Plan:
    stages: list[Stage]
    graph: Graph
    problems: list[str]
    _describe: list[dict] = field(default_factory=list, repr=False)

    def check(self) -> None:
        if self.problems:
            raise PipelineConfigError(self.problems)

    def mermaid(self) -> str:
        return self.graph.mermaid([f"{s.name} ({s.tasks} task{'s' if s.tasks != 1 else ''})" for s in self.stages])

    def describe(self) -> dict:
        """The stages with their blocks (each its ``to_dict()``: class and parameters; its contract, composite,
        group, condition), the graph's edges and the problems: for ``--dry-run``; the stages are the run record's
        ``pipeline``."""
        return {"stages": [{"name": s.name, "tasks": s.tasks, "blocks": d} for s, d in zip(self.stages, self._describe)],
                "edges": [{"from": e.source, "to": e.target, "parts": list(e.parts)} for e in self.graph.edges],
                "problems": list(self.problems)}

    @property
    def blocks(self) -> list:
        """Every stage's blocks, in order."""
        return [b for s in self.stages for b in s.blocks]


# ------------------------------------------------------------------------------------------------ building

@dataclass
class _Entry:
    block: object
    composites: tuple[str, ...] = ()
    contract: Contract | None = None

    def __post_init__(self):
        if self.contract is None:
            self.contract = contract_of(self.block)

    @property
    def label(self) -> str:
        name = getattr(self.block, "name", None)
        cls = type(self.block).__name__
        return cls if not name or name == cls else f"{cls} ({name})"


def _expand(blocks: list, problems: list[str]) -> list[_Entry]:
    out = []
    for b in blocks:
        if isinstance(b, Composite):
            if getattr(b, "when", None) is not None or getattr(b, "group", None) is not None:
                problems.append(f"composite {b.name!r} has a condition: give when= to its blocks")
            out += [_Entry(x, path) for x, path in b.expanded()]
        else:
            out.append(_Entry(b))
    return out


def _find(entries: list[_Entry], name: str, what: str, problems: list[str]) -> int | None:
    """The index of the block named ``name`` (its datatrove name, class name, or composite: its last block)."""
    hits = [i for i, e in enumerate(entries)
            if getattr(e.block, "name", None) == name or type(e.block).__name__ == name]
    if not hits:
        in_composite = [i for i, e in enumerate(entries) if name in e.composites]
        if in_composite:
            return in_composite[-1]
        problems.append(f"{what} {name}: no block of that name (names: "
                        f"{', '.join(sorted({type(e.block).__name__ for e in entries}))})")
        return None
    if len(hits) > 1:
        problems.append(f"{what} {name}: {len(hits)} blocks have that name ({', '.join(entries[i].label for i in hits)}); "
                        f"use the block's datatrove name")
        return None
    return hits[0]


def _is(block, cls_name: str) -> bool:
    return any(c.__name__ == cls_name for c in type(block).__mro__)


def _folder(writer) -> str | None:
    folder = getattr(writer, "output_folder", None)
    return getattr(folder, "path", None) if folder is not None else None


def _pages_writer(folder: str, item_shards: int | None = None):
    from ..blocks.writers.records import PageJsonlWriter

    return PageJsonlWriter(folder, output_filename="${rank}.jsonl.gz", item_shards=item_shards)


def _parts_through(entries: list[_Entry]) -> frozenset[Part]:
    """The parts a page carries after ``entries`` (from the page image and record on)."""
    out = {Part("image"), Part("metadata")}
    for e in entries:
        out |= e.contract.adds | e.contract.replaces
    return frozenset(p for p in out if p.name != "*")


def _after(entries: list[_Entry], name: str, problems: list[str]) -> list[_Entry]:
    i = _find(entries, name, "--after", problems)
    if i is None:
        return entries
    if not entries or not _is(entries[0].block, "PageRecordReader"):
        problems.append(f"--after {name}: the run must start from page records (--pages DIR)")
        return entries
    reader = entries[0].block
    given = reader.provides or frozenset()
    reader.provides = frozenset(given | _parts_through(entries[1:i + 1]))
    return [_Entry(reader), *entries[i + 1:]]


def _until(entries: list[_Entry], name: str, run_folder: str | None, problems: list[str]) -> list[_Entry]:
    i = _find(entries, name, "--until", problems)
    if i is None:
        return entries
    unit = "page"
    for e in entries[:i + 1]:
        unit = e.contract.output_unit if e.contract.unit != "any" else unit
    if unit != "page":
        problems.append(f"--until {name}: after it the stream carries {unit}s, not pages; page records cannot be written")
        return entries
    if run_folder is None:
        problems.append(f"--until {name}: needs a run folder for the page records")
        return entries
    kept = entries[:i + 1]
    folder = posixpath.join(run_folder.rstrip("/"), "pages")
    from datatrove.io import get_datafolder

    target = get_datafolder(folder).path
    if not any(_is(e.block, "PageJsonlWriter") and _folder(e.block) == target for e in kept):
        kept.append(_Entry(_pages_writer(folder)))
    return kept + [e for e in entries[i + 1:] if e.contract.role == "server"]


def _stamp(entries: list[_Entry], recipe: tuple[str, str]) -> None:
    """The recipe edition on every step: a ``RecipeStamper`` before the first writer."""
    from ..blocks.validation.recipe import RecipeStamper

    i = next((k for k, e in enumerate(entries) if e.contract.role in ("writer", "server")), len(entries))
    entries.insert(i, _Entry(RecipeStamper(*recipe)))


def _converters(entries: list[_Entry]) -> None:
    """A ``TranscriptionConverter`` right after a block that brings a transcription file (``ManifestReader(
    existing_ocr=True)``) when no block after it reads the file."""
    from ..blocks.conversion.transcriptions import TranscriptionConverter

    file = Part("transcription_file")
    for i, e in enumerate(entries):
        if file in e.contract.adds and not any(file in later.contract.reads for later in entries[i + 1:]):
            entries.insert(i + 1, _Entry(TranscriptionConverter()))
            return


def _rejects(entries: list[_Entry], run_folder: str) -> None:
    """A ``RejectWriter`` into ``<run_folder>/rejects`` before the first writer, binder or server (the stream still
    carries pages there), unless the pipeline has one."""
    from ..blocks.writers.rejects import RejectWriter

    if any(_is(e.block, "RejectWriter") for e in entries):
        return
    i = next((k for k, e in enumerate(entries) if e.contract.role in ("writer", "server", "binder")
              or e.contract.unit_out == "item"), len(entries))
    entries.insert(i, _Entry(RejectWriter(posixpath.join(run_folder.rstrip("/"), "rejects"))))


def _cut(entries: list[_Entry], tasks: int, run_folder: str | None, problems: list[str]):
    """``[(name, entries, tasks)]``: one stage, or two cut where the stream changes to items (``tasks > 1``)."""
    end = len(entries)
    while end > 0 and entries[end - 1].contract.role == "server":
        end -= 1
    body, servers = entries[:end], entries[end:]
    k = next((i for i, e in enumerate(body) if e.contract.unit == "page" and e.contract.unit_out == "item"), None)
    whole = bool(body) and getattr(body[0].block, "whole_items", False)     # each task reads whole items already
    if tasks <= 1 or k is None or whole:
        return [("pages" if k is None else "pages and items", entries, tasks)]
    if run_folder is None:
        problems.append(f"{body[k].label} binds items from pages that {tasks} tasks read: the cut into stages needs "
                        f"a run folder")
        return [("pages and items", entries, tasks)]
    from datatrove.io import get_datafolder

    pre, post = list(body[:k]), body[k:]
    folder = posixpath.join(run_folder.rstrip("/"), "pages")
    target = get_datafolder(folder).path
    shards = next((i for i, e in enumerate(pre) if _is(e.block, "PageJsonlWriter") and e.block.item_shards), None)
    if shards is not None:           # its own item shards: read them where it writes them (its DataFolder)
        n, folder = pre[shards].block.item_shards, pre[shards].block.output_folder
    else:
        n = tasks
        same = next((i for i, e in enumerate(pre) if _is(e.block, "PageJsonlWriter") and _folder(e.block) == target),
                    None)
        if same is not None:
            pre[same] = _Entry(_pages_writer(folder, n))
        else:
            pre.append(_Entry(_pages_writer(folder, n)))
    from ..blocks.readers.records import PageRecordReader

    reader = PageRecordReader(folder, fetch_images=False, item_shards=True, provides=())
    models_after = any(e.contract.role == "model" for e in post)
    first, second = (pre, [_Entry(reader), *post, *servers]) if models_after else (pre + servers, [_Entry(reader), *post])
    return [("pages", first, tasks), ("items", second, n)]


def _provider(p: Part, available: dict[Part, str]) -> str | None:
    if p in available:
        return available[p]
    if p.name == "*":            # any part of that transcription
        for a, node in available.items():
            if a.transcription == p.transcription or (a.name == "*" and a.transcription is None):
                return node
        return None
    for a, node in available.items():
        if a.covers(p):
            return node
    return None


#: what does not cross a change of unit: an item record holds no page image bytes, its pages not the item's document
LEFT_BEHIND = {"binder": frozenset({Part("image")}), "splitter": frozenset({Part("document")})}


def _across(c: Contract, available: dict[Part, str]) -> dict[Part, str]:
    """The parts after a block that changes the stream's unit: a binder's item record holds its pages, and a
    splitter's pages what the item record held, so the parts carry across (apart from ``LEFT_BEHIND``); after any
    other such block only what it adds."""
    if c.role not in LEFT_BEHIND:
        return {p: v for p, v in available.items() if p in c.adds}
    return {p: v for p, v in available.items() if p not in LEFT_BEHIND[c.role]}


class _Analysis:
    """Walks one stage: checks, nodes and edges."""

    def __init__(self, graph: Graph, problems: list[str], counter: list[int]):
        self.graph, self.problems, self.counter = graph, problems, counter

    def node(self, e: _Entry, stage: int) -> Node:
        n = Node(id=f"n{self.counter[0]}", block=type(e.block).__name__,
                 name=getattr(e.block, "name", None) or type(e.block).__name__, role=e.contract.role,
                 unit=e.contract.unit, stage=stage, composites=e.composites,
                 group=getattr(e.block, "group", None),
                 when=(w.describe() if (w := getattr(e.block, "when", None)) is not None else None))
        self.counter[0] += 1
        self.graph.nodes.append(n)
        return n

    def stage(self, entries: list[_Entry], index: int, where: str, given: bool = False) -> tuple[dict, list[Node]]:
        problems = self.problems
        available: dict[Part, str] = {}
        gone: dict[Part, str] = {}                  # removed parts -> the block that removed them
        nodes = [self.node(e, index) for e in entries]
        edges: dict[tuple[str, str], set[str]] = {}
        unit = "page"
        if given and (not entries or entries[0].contract.role != "reader"):
            available[Part("*")] = "input"
        elif not entries or entries[0].contract.role != "reader":
            problems.append(f"{where} starts with {entries[0].label if entries else 'nothing'}, not a reader")
        server_seen = None
        groups_done: set[str] = set()
        i = 0
        while i < len(entries):
            group = getattr(entries[i].block, "group", None)
            j = i + 1
            if group is not None:
                while j < len(entries) and getattr(entries[j].block, "group", None) == group:
                    j += 1
                if group in groups_done:
                    problems.append(f"{where}: the alternatives of group {group!r} are not next to each other")
                groups_done.add(group)
            before = dict(available)
            added_by: list[frozenset[Part]] = []
            for k in range(i, j):
                e, n = entries[k], nodes[k]
                c = e.contract
                if k > 0 and c.unit != "any" and c.unit != unit:
                    problems.append(f"{e.label} works on {c.unit}s, but the stream carries {unit}s here")
                if server_seen is not None and c.role != "server":
                    problems.append(f"{e.label} comes after the server block {server_seen}: server blocks go last")
                if c.role == "server":
                    server_seen = e.label
                when = getattr(e.block, "when", None)
                if group is not None and when is None:
                    problems.append(f"{e.label} is an alternative of group {group!r} without a condition (when=)")
                if when is not None and c.role in ("reader", "server"):
                    problems.append(f"{e.label}: a {c.role} cannot take a condition")
                if isinstance(when, Otherwise) and group is not None and k != j - 1:
                    problems.append(f"{e.label}: OTHERWISE must be the last alternative of group {group!r}")
                base = before if group is not None else available
                for p in sorted(c.reads):
                    src = _provider(p, base)
                    if p in gone:
                        problems.append(f"{e.label} reads {p}, which {gone[p]} removes before it")
                    elif src is None:
                        problems.append(f"{e.label} reads {p}, which no block before it in {where} adds")
                    elif src != "input":
                        edges.setdefault((src, n.id), set()).add(str(p))
                for p in sorted(c.adds):
                    if p in base and p not in c.replaces and p.name != "*":
                        owner = next(x for x in self.graph.nodes if x.id == base[p])
                        problems.append(f"{e.label} adds {p}, which {owner.block} adds already (a block that "
                                        f"rewrites a part declares it in replaces)")
                    available[p] = n.id
                    gone.pop(p, None)
                for p in c.replaces:
                    available[p] = n.id
                    gone.pop(p, None)
                for p in c.removes:              # gone after the block: a later read of it is a problem
                    available.pop(p, None)
                    gone[p] = e.label
                added_by.append(c.adds | c.replaces)
                if c.unit_out:
                    unit = c.unit_out
                    available = _across(c, available)
                elif k == 0:
                    unit = c.output_unit if c.unit != "any" else unit
            if group is not None and len({frozenset(x) for x in added_by}) > 1:
                described = "; ".join(f"{entries[k].label}: {', '.join(sorted(map(str, added_by[k - i]))) or 'nothing'}"
                                      for k in range(i, j))
                problems.append(f"the alternatives of group {group!r} add different parts ({described})")
            i = j
        self._served(entries, where)
        for (s, t), ps in edges.items():
            self.graph.edges.append(Edge(s, t, tuple(sorted(ps))))
        return available, nodes

    def _served(self, entries: list[_Entry], where: str) -> None:
        ports = {}
        for e in entries:
            if e.contract.role == "server" and getattr(e.block, "port", None) is not None:
                ports[e.block.port] = e
        for e in entries:
            backend = getattr(e.block, "backend", None)
            if not getattr(backend, "served", False):
                continue
            u = urlsplit(backend.endpoint)
            server = ports.get(u.port) if u.hostname in LOCAL_HOSTS else None
            if server is None or not _is(server.block, "ModelServer"):
                continue
            hosted = [m.get("name") for m in server.block.models]
            if backend.model not in hosted:
                self.problems.append(f"{e.label} asks the model server on port {u.port} in {where} for "
                                     f"{backend.model!r}, which it does not host ({', '.join(hosted) or 'none'})")


def block_dict(block) -> dict:
    """``block.to_dict()``; a plain datatrove step (no ``to_dict``) by its class only."""
    if callable(getattr(block, "to_dict", None)):
        return block.to_dict()
    return {"block": type(block).__name__, "class": f"{type(block).__module__}:{type(block).__qualname__}"}


def _describe_block(e: _Entry, node: Node) -> dict:
    out: dict = {"id": node.id, "block": node.block}
    if node.name != node.block:
        out["name"] = node.name
    out.update(block_dict(e.block))
    out["contract"] = e.contract.describe()
    shape = getattr(e.block, "shape", None)
    if shape:
        out["shape"] = shape
    if e.composites:
        out["composite"] = "/".join(e.composites)
    if node.group:
        out["group"] = node.group
    if node.when:
        out["when"] = node.when
    if _is(e.block, "PageRecordReader") and e.block.provides is None:
        out["provides"] = "unknown: reads after it are not checked"
    return out


def build(blocks: list, *, tasks: int = 1, until: str | None = None, after: str | None = None,
          taps: dict[str, str] | None = None, run_folder: str | None = None, recipe: tuple[str, str] | None = None,
          observers: list[Observer] | None = None, max_page_errors: float | None = None,
          trace_sample: float | None = None, image_decode: str | None = None, run_id: str | None = None) -> Plan:
    """Turns a list of blocks into a checked plan of stages, cut where the stream changes from pages to items.

    The builder expands composites, checks the contracts (every part a block reads is added before it, units fit,
    servers go last, ...), inserts the blocks a run needs (a ``TranscriptionConverter`` after a reader that brings
    transcription files, the ``RecipeStamper``, a ``RejectWriter`` into ``<run_folder>/rejects``) and derives the
    graph. Problems are collected in ``Plan.problems``; ``Plan.check()`` raises them as one
    ``PipelineConfigError``. Every stage is traced (``linecaster.tracing.Tracing``) into ``<run_folder>/traces``
    and, when the ``OTEL_*`` variables ask for it, to an OTLP endpoint; without a run folder or OTLP nothing is
    traced (``docs/reference/pipelines.md``, "The builder").

    Args:
        blocks: the blocks and composites, in order; the builder checks the order and does not change it.
        tasks: the number of tasks; over 1, the first binder cuts the pipeline into a page stage writing item shards
            and an item stage reading them, unless the reader gives each task whole items.
        until: run the blocks up to and including this one (by name, class name or composite name), then write
            page records into ``<run_folder>/pages``; needs a run folder.
        after: run the blocks after this one, from the pipeline's ``PageRecordReader``, which then declares what the
            blocks up to it add.
        taps: block name -> folder: the page records as they leave that block, written to ``<folder>/<rank>.jsonl.gz``.
        run_folder: the run folder (``OUT``): rejects, traces, partial runs and item shards go there; default none.
        recipe: ``(ref, sha256)`` of the recipe edition the run follows, stamped on every step before the first
            writer (``RecipeStamper``).
        observers: more observers, on every stage next to the taps and the tracing.
        max_page_errors: every page block's error budget, a share of a task's pages; default each block's own
            (0.01).
        trace_sample: the share of pages traced, chosen by page id; default ``linecaster.tracing.DEFAULT_SAMPLE``.
        image_decode: how every model block decodes page images (``auto``, ``gpu``, ``cpu``;
            ``linecaster.images.pixels``); default each block's own (``auto``).
        run_id: the run's id (``RunRecord.run_id``), given to every block that names it on the annotators the run
            adds (``run_id``: the page record writers); default none (nothing named).

    Example:
        from linecaster.blocks.readers import ImageFolderReader
        from linecaster.blocks.writers import PageJsonlWriter
        from linecaster.runtime.builder import build

        plan = build([ImageFolderReader("scans/"), PageJsonlWriter("out/pages")], tasks=4, run_folder="out")
        plan.check()               # PipelineConfigError listing every problem
        print(plan.mermaid())      # the graph as a Mermaid flowchart
        for stage in plan.stages:  # one datatrove pipeline each, run in order
            print(stage.name, stage.tasks, len(stage.pipeline))
    """
    return _build(blocks, tasks=tasks, until=until, after=after, taps=taps, run_folder=run_folder, recipe=recipe,
                  observers=observers, max_page_errors=max_page_errors, trace_sample=trace_sample,
                  image_decode=image_decode, run_id=run_id)


def _tracing(run_folder: str | None, trace_sample: float | None, stage: str | None, problems: list[str]):
    """The stage's tracing observer: when there is a run folder for its file, or an OTLP endpoint."""
    from ..errors import PipelineConfigError
    from ..tracing import DEFAULT_SAMPLE, Tracing, otlp_configured

    if run_folder is None and not otlp_configured():
        return None
    try:
        return Tracing(run_folder, DEFAULT_SAMPLE if trace_sample is None else trace_sample, stage=stage)
    except PipelineConfigError as e:
        if e.problems[0] not in problems:
            problems.extend(e.problems)
        return None


def _build(blocks: list, *, tasks: int = 1, until=None, after=None, taps=None, run_folder=None, recipe=None,
           observers=None, given: bool = False, max_page_errors=None, trace_sample=None, image_decode=None,
           run_id=None) -> Plan:
    problems: list[str] = []
    entries = _expand(list(blocks), problems)
    _converters(entries)
    if after:
        entries = _after(entries, after, problems)
    if until:
        entries = _until(entries, until, run_folder, problems)
    if recipe:
        _stamp(entries, recipe)
    if run_folder is not None:
        _rejects(entries, run_folder)
    if max_page_errors is not None:
        for e in entries:
            if hasattr(e.block, "max_page_errors"):
                e.block.max_page_errors = max_page_errors
    if image_decode is not None:
        for e in entries:
            if hasattr(e.block, "image_decode"):
                e.block.image_decode = image_decode
    cut = _cut(entries, tasks, run_folder, problems)
    graph, counter = Graph(), [0]
    analysis = _Analysis(graph, problems, counter)
    stages, described, previous_nodes, carried = [], [], None, frozenset()
    for index, (name, stage_entries, stage_tasks) in enumerate(cut):
        where = f"stage {index + 1} ({name})" if len(cut) > 1 else "the pipeline"
        if index > 0:          # the reader of a later stage brings what the earlier one wrote
            reader = stage_entries[0]
            reader.block.provides = frozenset(p for p in carried if p.name not in ("*", "image"))
            reader.contract = contract_of(reader.block)
        available, nodes = analysis.stage(stage_entries, index, where, given=given and index == 0)
        carried = frozenset(available)
        if index > 0 and previous_nodes:
            writer = next((n for n in reversed(previous_nodes) if n.block == "PageJsonlWriter"), previous_nodes[-1])
            graph.edges.append(Edge(writer.id, nodes[0].id, ("page records (item shards)",)))
        previous_nodes = nodes
        described.append([_describe_block(e, n) for e, n in zip(stage_entries, nodes)])
        stages.append((name, stage_entries, stage_tasks))
    # taps and observers, per stage
    tap_at: dict[int, list[Observer]] = {}
    flat = [(s, e) for s, (_, es, _) in enumerate(stages) for e in es]
    for block_name, folder in (taps or {}).items():
        i = _find([e for _, e in flat], block_name, "--tap-after", problems)
        if i is None:
            continue
        s, e = flat[i]
        if e.contract.output_unit not in ("page", "any") or e.contract.role == "server":
            problems.append(f"--tap-after {block_name}: page records can only be tapped after a page block")
            continue
        tap_at.setdefault(s, []).append(Tap(e.block, folder))
    out = []
    for s, (name, stage_entries, stage_tasks) in enumerate(stages):
        if run_id is not None:            # the blocks that name the run on the annotators it added
            for e in stage_entries:
                if hasattr(type(e.block), "run_id"):
                    e.block.run_id = run_id
        tracing = _tracing(run_folder, trace_sample, name if len(stages) > 1 else None, problems)
        timing = _timing(stage_entries)
        hub = Observers([*([timing] if timing else []), *tap_at.get(s, []), *(observers or []),
                         *([tracing] if tracing else [])])
        out.append(Stage(name=name, tasks=stage_tasks, blocks=[e.block for e in stage_entries],
                         pipeline=_pipeline(stage_entries, hub if hub else None), observers=hub if hub else None))
    return Plan(stages=out, graph=graph, problems=problems, _describe=described)


def _timing(entries: list[_Entry]):
    """A page stage's ``PageTiming``: from its first block to the first that writes pages, binds or serves (where the
    stream still carries pages, as for ``_rejects``); none for a stage of items or one that writes no page."""
    from .observers import PageTiming

    if not entries or entries[0].contract.unit not in ("page", "any") or entries[0].contract.output_unit == "item":
        return None
    stop = next((e.block for e in entries[1:] if e.contract.role in ("writer", "server", "binder")
                 or e.contract.unit_out == "item"), None)
    return None if stop is None else PageTiming(entries[0].block, stop)


def _pipeline(entries: list[_Entry], hub: Observers | None) -> list:
    """The datatrove steps of a stage: each block (behind a ``Branch`` when it has a condition), with a
    ``Boundary`` after it when the stage has observers."""
    steps = []
    groups = [getattr(e.block, "group", None) for e in entries]
    for i, e in enumerate(entries):
        b = e.block
        when = getattr(b, "when", None)
        if hub is not None and hasattr(b, "warm_up"):
            b._observers = hub
        if when is not None:
            g = groups[i]
            last = g is not None and (i + 1 == len(entries) or groups[i + 1] != g)
            steps.append(Branch(b, when, g, label=getattr(b, "name", None) or type(b).__name__, last=last))
        else:
            steps.append(b)
        if hub is not None:
            nxt = entries[i + 1].block if i + 1 < len(entries) else None
            steps.append(Boundary(hub, b, nxt, last=nxt is None))
    return steps


def run_pages(blocks: list, docs=(), *, observers: list[Observer] | None = None) -> list:
    """Runs blocks on datatrove documents in this process, without an executor, and returns what comes out.

    The pipeline is checked first (without a reader, the documents may carry any part) and run as task 0 of 1; a
    leading reader reads its own input after ``docs``. A pipeline script's ``--page IMAGE OUT`` runs this way.

    Args:
        blocks: the blocks and composites, in order.
        docs: the documents to run, e.g. ``new_page_document(...)`` for a page image; default none (the reader's).
        observers: observers on the run, as ``build`` takes them.
    """
    plan = _build(blocks, observers=observers, given=True)
    plan.check()
    return run_plan(plan, docs)


def run_plan(plan: Plan, docs=()) -> list:
    """Run a plan's stages one after another in this process, as task 0 of 1 each, ``docs`` into the first; the
    documents that come out of one stage go into the next (whose reader yields them before its own input)."""
    out = list(docs)
    for stage in plan.stages:
        data = iter(out)
        for step in stage.pipeline:
            data = step(data, 0, 1)
        out = list(data) if data is not None else []
    return out
