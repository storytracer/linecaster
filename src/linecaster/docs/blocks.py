"""The block pages (``linecaster docs``, ``docs/blocks/``): an index with one table per family and the base classes,
and a page per public block (the classes exported from ``linecaster.blocks.<family>``).

Every row comes from code: the summary, behavior and example from the docstring (``linecaster.docs.docstrings``),
the contract from an instance (built with the defaults, or with the block's ``docs_args``), the options from the
constructor's signature and ``Args:``, the backends from the type of a model block's ``backend``, the catalog step
and its presets from the block's ``step``, where a block comes in a pipeline from every block's contract, and the
pipeline scripts that use it from their source (``ast``).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..blocks.base.block import Block
from ..blocks.base.contract import Contract, Part, contract_of
from ..catalog import code
from ..catalog.schema import RULE_STEPS, STEPS
from .common import HEADER, Links, table
from .docstrings import Docstring, markdown, parse

FAMILIES = ("readers", "layout", "lines", "recognition", "conversion", "text", "composition", "binding", "validation",
            "servers", "writers", "composites")
TITLES = {"readers": "Readers", "layout": "Layout", "lines": "Lines", "recognition": "Recognition",
          "conversion": "Conversion", "text": "Text", "composition": "Composition", "binding": "Binding",
          "validation": "Validation", "servers": "Servers", "writers": "Writers", "composites": "Composites"}
#: the backends a model block's ``backend`` annotation names
BACKENDS = {"InProcess": "in-process", "Served": "served", "Chat": "chat"}
#: the part every reader may bring (``PageRecordReader`` without ``provides``): left out of the derived positions
ANYTHING = Part("*")


@dataclass
class BlockDoc:
    name: str
    family: str                   # the package under blocks/, or "base"
    cls: type
    doc: Docstring
    source: Path
    contract: Contract | None = None
    #: the contracts the positions are derived from: the instance's, and an item-unit one where the block has a unit
    contracts: list[Contract] = field(default_factory=list)
    error: str | None = None

    @property
    def module(self) -> str:
        return f"linecaster.blocks.{self.family}"

    @property
    def page(self) -> str:
        return f"{self.family}/{self.name}.md"


def _own_doc(cls) -> str:
    return cls.__dict__.get("__doc__") or ""


def collect(family: str) -> list[BlockDoc]:
    """The public blocks of ``family`` (its ``__all__``), base classes left out unless the family is ``base``."""
    m = importlib.import_module(f"linecaster.blocks.{family}")
    out = []
    for name in sorted(m.__all__):
        obj = getattr(m, name)
        if not (inspect.isclass(obj) and issubclass(obj, Block)):
            continue
        if family != "base" and obj.__module__.startswith("linecaster.blocks.base"):
            continue
        out.append(BlockDoc(name, family, obj, parse(_own_doc(obj)), Path(inspect.getsourcefile(obj))))
    return out


def _describe_backend(ref):
    """A preset ref as the docs build it: a model engine's preset as its ``InProcess`` backend without the engine
    installed (as describe mode does), anything else as given."""
    from ..backends import InProcess
    from ..catalog.registry import BUILTIN_ENGINES, engine_spec
    from ..errors import CatalogError

    if not (isinstance(ref, str) and "@" in ref):
        return ref
    try:
        spec, kwargs, r = engine_spec(ref, installed=False)
    except (CatalogError, ValueError):
        return ref
    if r.engine in BUILTIN_ENGINES:
        return ref
    backend = InProcess(spec, **kwargs)
    backend.preset, backend.preset_sha256 = r.ref, r.sha256
    return backend


def instance(cls, **extra):
    """``cls`` built with its ``docs_args`` (and ``extra``)."""
    kwargs = {k: _describe_backend(v) for k, v in {**cls.docs_args, **extra}.items()}
    return cls(**kwargs)


def contracts(b: BlockDoc) -> None:
    try:
        b.contract = contract_of(instance(b.cls))
    except Exception as e:                  # shown on the page: the docs need not fail for one block
        b.error = f"{type(e).__name__}: {e}"
        return
    b.contracts = [b.contract]
    if "unit" in inspect.signature(b.cls).parameters:
        try:
            b.contracts.append(contract_of(instance(b.cls, unit="item")))
        except Exception:
            pass


def _parts(c: Contract | None, key: str) -> list[str]:
    return sorted(map(str, getattr(c, key))) if c else []


def _covers(added: Part, read: Part) -> bool:
    return added != ANYTHING and added.covers(read)


def positions(blocks: list[BlockDoc]) -> dict[str, tuple[list[str], list[str]]]:
    """Per block: the blocks whose adds cover its reads (comes after), and those that read what it adds (comes
    before), from every contract of every block."""
    out = {}
    for b in blocks:
        reads = {p for c in b.contracts for p in c.reads}
        adds = {p for c in b.contracts for p in c.adds}
        after = [o.name for o in blocks if o is not b and any(
            _covers(a, r) for c in o.contracts for a in c.adds for r in reads)]
        before = [o.name for o in blocks if o is not b and any(
            _covers(a, r) for c in o.contracts for r in c.reads for a in adds)]
        out[b.name] = (after, before)
    return out


def used_in(repo: Path | None) -> dict[str, list[code.Pipeline | Path]]:
    """Block name -> the pipelines whose shapes (``linecaster.pipelines``) construct it (a call of the name), found
    with ``ast``."""
    out: dict[str, list] = {}
    for pl in sorted(code.pipelines(repo).values(), key=lambda pl: pl.shape.name):
        names = set()
        for node in ast.walk(ast.parse(pl.shape.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = node.func
                names.add(fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None))
        for n in sorted(names - {None}):
            out.setdefault(n, []).append(pl)
    return out


def merged_args(cls) -> dict[str, str]:
    """The ``Args:`` of ``cls`` with its bases' (up to the class that defines the constructor)."""
    chain = []
    for c in cls.__mro__:
        if not c.__module__.startswith("linecaster."):
            break
        chain.append(c)
        if "__init__" in c.__dict__:
            break
    out: dict[str, str] = {}
    for c in reversed(chain):
        out.update(parse(_own_doc(c)).args)
    return out


def _repr(value) -> str:
    """A default as Python writes it, sets sorted (their order changes from run to run)."""
    if isinstance(value, (set, frozenset)):
        inner = ", ".join(repr(v) for v in sorted(value, key=repr))
        return f"{type(value).__name__}({{{inner}}})" if value else f"{type(value).__name__}()"
    return repr(value)


def options(cls) -> list[tuple]:
    """The constructor's arguments: name, type, default, description."""
    args = merged_args(cls)
    rows = []
    for p in inspect.signature(cls).parameters.values():
        name = {p.VAR_KEYWORD: f"**{p.name}", p.VAR_POSITIONAL: f"*{p.name}"}.get(p.kind, p.name)
        typ = p.annotation if isinstance(p.annotation, str) else (
            "" if p.annotation is p.empty else inspect.formatannotation(p.annotation))
        if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            default = ""
        else:
            default = "required" if p.default is p.empty else f"`{_repr(p.default)}`"
        rows.append((f"`{name}`", f"`{typ}`" if typ else "", default, markdown(args.get(p.name, ""))))
    return rows


def _backends(cls) -> str | None:
    """A model block's backends, from the annotation of its ``backend`` parameter."""
    p = inspect.signature(cls).parameters.get("backend")
    if p is None:
        return None
    ann = p.annotation if isinstance(p.annotation, str) else str(p.annotation)
    names = re.findall(r"\w+", ann)
    found = [f"{BACKENDS[n]} (`{n}`)" for n in names if n in BACKENDS]
    if "str" in names:
        found.append("a preset ref (`id@edition`) builds one")
    return ", ".join(found)


def _presets(b: BlockDoc, catalog, links: Links, here: Path, catalog_dir: Path) -> list[str]:
    """The catalog's presets for the block's step (recognition: those of the unit the block reads; chat blocks:
    the chat presets)."""
    step = getattr(b.cls, "step", None)
    if step not in STEPS or catalog is None:
        return []
    chat = "chat" in (_backends(b.cls) or "")
    reads = {p.name for p in (b.contract.reads if b.contract else ())}
    unit = "line" if "lines" in reads else "region" if "regions" in reads else "page"
    out = []
    for pid, (_, p) in sorted(catalog.presets.items()):
        if p.step != step or (p.engine == "chat.v1") != chat:
            continue
        if step == "recognition" and p.capabilities.unit not in (None, unit):
            continue
        target = catalog_dir / "presets" / step / f"{pid}.md"
        out.append(f"[`{p.ref}`]({links.to(target, here)})")
    return out


def _names(names: list[str], blocks: dict[str, BlockDoc], here: Path, root: Path, links: Links) -> str:
    readers = sorted(n for n, b in blocks.items() if b.contract and b.contract.role == "reader")
    shown = list(names)
    if readers and all(r in shown for r in readers):
        shown = ["any reader", *[n for n in shown if n not in readers]]
    return ", ".join(n if n == "any reader" else f"[`{n}`]({links.to(root / blocks[n].page, here)})" for n in shown) \
        or "-"


def _mermaid(b: BlockDoc) -> list[str]:
    c = b.contract
    if c is None:
        return []

    def node(prefix, i, label):
        return f'{prefix}{i}["{label}"]'

    lines = ["```mermaid", "flowchart LR", f'    B["{b.name}"]']
    reads = _parts(c, "reads") or [f"{c.unit} stream"]
    adds = _parts(c, "adds") or [f"{c.output_unit} stream"]
    for i, r in enumerate(reads):
        lines.append(f"    {node('r', i, r)} --> B")
    for i, a in enumerate(adds):
        lines.append(f"    B --> {node('a', i, a)}")
    for i, x in enumerate(_parts(c, "replaces")):
        lines.append(f"    B -. replaces .-> {node('x', i, x)}")
    for i, x in enumerate(_parts(c, "removes")):
        lines.append(f"    B -. removes .-> {node('d', i, x)}")
    return [*lines, "```", ""]


def block_page(b: BlockDoc, blocks: dict[str, BlockDoc], position: tuple[list[str], list[str]],
               scripts: list, catalog, links: Links, root: Path, catalog_dir: Path) -> str:
    here = root / b.family
    lines = [f"# {b.name}", "", f"*Block · {b.family} · `{b.module}`*", "", markdown(b.doc.summary), ""]
    c = b.contract
    rows = []
    if c is not None:
        rows.append(("Unit", f"{c.unit} → {c.unit_out}" if c.unit_out else c.unit))
        rows.append(("Role", c.role))
        for key, label in (("reads", "Reads"), ("adds", "Adds"), ("replaces", "Replaces")):
            rows.append((label, ", ".join(f"`{p}`" for p in _parts(c, key)) or "-"))
        if c.removes:
            rows.append(("Removes", ", ".join(f"`{p}`" for p in _parts(c, "removes"))))
    else:
        rows.append(("Contract", f"not built: {b.error}"))
    if backends := _backends(b.cls):
        rows.append(("Backends", backends))
    elif getattr(b.cls, "step", None) in RULE_STEPS:
        rows.append(("Backends", "in-process only (a built-in engine)"))
    step = getattr(b.cls, "step", None)
    if step in STEPS:
        rows.append(("Catalog step", f"`{step}`"))
        if presets := _presets(b, catalog, links, here, catalog_dir):
            rows.append(("Presets", ", ".join(presets)))
    after, before = position
    rows.append(("Comes after", _names(after, blocks, here, root, links)))
    rows.append(("Comes before", _names(before, blocks, here, root, links)))
    used = []
    for s in scripts:
        if isinstance(s, code.Pipeline):
            used.append(f"[`{s.id}`]({links.to(catalog_dir / 'pipelines' / f'{s.id}.md', here)})")
        else:
            used.append(f"[`{s.name}`]({links.to(s, here)})")
    rows.append(("Used in", ", ".join(used) or "-"))
    rows.append(("Source", f"[{b.source.name}]({links.to(b.source, here)})"))
    lines += table(("", ""), rows)
    if b.cls.docs_args:
        args = ", ".join(f"{k}={v!r}" for k, v in b.cls.docs_args.items())
        lines += [f"The contract is that of `{b.name}({args})`; the comes-after and comes-before rows are derived from "
                  "every block's contract.", ""]
    else:
        lines += ["The comes-after and comes-before rows are derived from every block's contract.", ""]
    if opts := options(b.cls):
        lines += ["## Options", "", *table(("Option", "Type", "Default", "Description"), opts)]
    if b.doc.body:
        lines += ["## Behavior", "", markdown(b.doc.body), ""]
    lines += ["## Contract", "", *_mermaid(b)]
    if b.doc.example:
        lines += ["## Example", "", "```python", b.doc.example, "```", ""]
    return "\n".join(lines)


def index_page(families: dict[str, list[BlockDoc]], base: list[BlockDoc], links: Links, root: Path) -> str:
    lines = ["# Blocks", "", "Every public block, by family: one page each with its contract, backends, options, "
             "behavior and where it comes in a pipeline. Terms are the [glossary](../reference/glossary.md)'s; "
             "contracts and the builder are in [pipelines](../reference/pipelines.md).", ""]
    for family, blocks in families.items():
        if not blocks:
            continue
        lines += [f"## {TITLES[family]}", "", f"`linecaster.blocks.{family}`", "",
                  *table(("Block", "What it does"), [(f"[`{b.name}`]({b.page})", markdown(b.doc.summary))
                                                     for b in blocks])]
    if base:
        lines += ["## Base classes", "", "`linecaster.blocks.base`: what the blocks above are built on; no pages of "
                  "their own.", "",
                  *table(("Class", "What it is for"), [(f"[`{b.name}`]({links.to(b.source, root)})",
                                                        markdown(b.doc.summary)) for b in base])]
    return "\n".join(lines)


def build(repo: Path | None = code.REPO):
    """The blocks by family with their contracts, the base classes, the derived positions and the scripts."""
    families = {f: collect(f) for f in FAMILIES}
    every = [b for blocks in families.values() for b in blocks]
    for b in every:
        contracts(b)
    return families, collect("base"), positions(every), used_in(repo)


def pages(out: str | Path, links: Links, catalog=None, catalog_dir: str | Path | None = None,
          repo: Path | None = code.REPO, built=None) -> dict[str, str]:
    """Every block page and the index, by path below ``out`` (``docs/blocks``), each with the generated header."""
    out = Path(out)
    catalog_dir = Path(catalog_dir) if catalog_dir is not None else out.parent / "catalog"
    families, base, position, scripts = built or build(repo)
    blocks = {b.name: b for bs in families.values() for b in bs}
    found = {"README.md": index_page(families, base, links, out)}
    for b in blocks.values():
        found[b.page] = block_page(b, blocks, position[b.name], scripts.get(b.name, []), catalog, links, out,
                                   catalog_dir)
    return {rel: f"{HEADER}\n{text.rstrip(chr(10))}\n" for rel, text in sorted(found.items())}
