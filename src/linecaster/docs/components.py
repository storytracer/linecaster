"""The component pages (``linecaster docs``, ``docs/components/``): an index with one table per family and the base classes,
and a page per public component (the classes exported from ``linecaster.components.<family>``).

Every row comes from code: the summary, behavior and example from the docstring (``linecaster.docs.docstrings``),
the contract from an instance (built with the defaults, or with the component's ``docs_args``), the options from the
constructor's signature and ``Args:``, the backends from the type of a model component's ``backend``, the catalog step
and its presets from the component's ``step``, where a component comes in a pipeline from every component's contract, and the
pipeline scripts that use it from their source (``ast``).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path

from linecaster.core.component import Component
from linecaster.core.contract import Contract, Part, contract_of
from linecaster.catalog import code
from linecaster.catalog.schema import RULE_STEPS, STEPS
from linecaster.docs.common import HEADER, Links, table
from linecaster.docs.docstrings import Docstring, markdown, parse

FAMILIES = ("readers", "images", "layout", "lines", "recognition", "tables", "formulas", "hierarchy", "paragraphs",
            "document", "items", "importers", "tagging", "validation", "servers", "scoring", "writers", "composites")
TITLES = {"readers": "Readers", "images": "Images", "layout": "Layout", "lines": "Lines", "recognition": "Recognition",
          "tables": "Tables", "formulas": "Formulas", "hierarchy": "Hierarchy", "paragraphs": "Paragraphs",
          "document": "Document", "items": "Items", "importers": "Importers", "tagging": "Tagging",
          "validation": "Validation", "servers": "Servers", "scoring": "Scoring", "writers": "Writers",
          "composites": "Composites"}
#: the backends a model component's ``backend`` annotation names
BACKENDS = {"InProcess": "in-process", "Served": "served", "Chat": "chat"}
#: the part every reader may bring (``PageRecordReader`` without ``provides``): left out of the derived positions
ANYTHING = Part("*")


@dataclass
class ComponentDoc:
    name: str
    family: str                   # the package under components/, or "base"
    cls: type
    doc: Docstring
    source: Path
    contract: Contract | None = None
    #: the contracts the positions are derived from: the instance's, and an item-unit one where the component has a unit
    contracts: list[Contract] = field(default_factory=list)
    error: str | None = None

    @property
    def module(self) -> str:
        return "linecaster.core" if self.family == "base" else f"linecaster.components.{self.family}"

    @property
    def page(self) -> str:
        return f"{self.family}/{self.name}.md"


def _own_doc(cls) -> str:
    return cls.__dict__.get("__doc__") or ""


def collect(family: str) -> list[ComponentDoc]:
    """The public components of ``family`` (its ``__all__``), base classes left out unless the family is ``base``."""
    m = importlib.import_module("linecaster.core" if family == "base" else f"linecaster.components.{family}")
    out = []
    for name in sorted(m.__all__):
        obj = getattr(m, name)
        if not (inspect.isclass(obj) and issubclass(obj, Component)):
            continue
        if family != "base" and obj.__module__.startswith("linecaster.core"):
            continue
        out.append(ComponentDoc(name, family, obj, parse(_own_doc(obj)), Path(inspect.getsourcefile(obj))))
    return out


def _describe_backend(ref):
    """A preset ref as the docs build it: a model engine's preset as its ``InProcess`` backend without the engine
    installed (as describe mode does), anything else as given."""
    from linecaster.backends import InProcess
    from linecaster.catalog.registry import BUILTIN_ENGINES, engine_spec
    from linecaster.errors import CatalogError

    if not isinstance(ref, str):
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
    kwargs = {**cls.docs_args, **extra}
    if ".servers." not in cls.__module__:       # a server component takes a preset's id, never a backend
        kwargs = {k: _describe_backend(v) for k, v in kwargs.items()}
    return cls(**kwargs)


def contracts(b: ComponentDoc) -> None:
    try:
        b.contract = contract_of(instance(b.cls))
    except Exception as e:                  # shown on the page: the docs need not fail for one component
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


def positions(components: list[ComponentDoc]) -> dict[str, tuple[list[str], list[str]]]:
    """Per component: the components whose adds cover its reads (comes after), and those that read what it adds (comes
    before), from every contract of every component."""
    out = {}
    for b in components:
        reads = {p for c in b.contracts for p in c.reads}
        adds = {p for c in b.contracts for p in c.adds}
        after = [o.name for o in components if o is not b and any(
            _covers(a, r) for c in o.contracts for a in c.adds for r in reads)]
        before = [o.name for o in components if o is not b and any(
            _covers(a, r) for c in o.contracts for r in c.reads for a in adds)]
        out[b.name] = (after, before)
    return out


def used_in(repo: Path | None) -> dict[str, list[code.Pipeline | Path]]:
    """Component name -> the pipelines whose shapes (``linecaster.pipelines``) construct it (a call of the name), found
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
    """A model component's backends, from the annotation of its ``backend`` parameter."""
    p = inspect.signature(cls).parameters.get("backend")
    if p is None:
        return None
    ann = p.annotation if isinstance(p.annotation, str) else str(p.annotation)
    names = re.findall(r"\w+", ann)
    found = [f"{BACKENDS[n]} (`{n}`)" for n in names if n in BACKENDS]
    if "str" in names:
        found.append("a preset ref (`id`) builds one")
    return ", ".join(found)


def _presets(b: ComponentDoc, catalog, links: Links, here: Path, catalog_dir: Path) -> list[str]:
    """The catalog's presets for the component's step (recognition: those of the unit the component reads; chat components:
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


def _names(names: list[str], components: dict[str, ComponentDoc], here: Path, root: Path, links: Links) -> str:
    readers = sorted(n for n, b in components.items() if b.contract and b.contract.role == "reader")
    shown = list(names)
    if readers and all(r in shown for r in readers):
        shown = ["any reader", *[n for n in shown if n not in readers]]
    return ", ".join(n if n == "any reader" else f"[`{n}`]({links.to(root / components[n].page, here)})" for n in shown) \
        or "-"


def _mermaid(b: ComponentDoc) -> list[str]:
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


def component_page(b: ComponentDoc, components: dict[str, ComponentDoc], position: tuple[list[str], list[str]],
               scripts: list, catalog, links: Links, root: Path, catalog_dir: Path) -> str:
    here = root / b.family
    lines = [f"# {b.name}", "", f"*Component · {b.family} · `{b.module}`*", "", markdown(b.doc.summary), ""]
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
    rows.append(("Comes after", _names(after, components, here, root, links)))
    rows.append(("Comes before", _names(before, components, here, root, links)))
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
                  "every component's contract.", ""]
    else:
        lines += ["The comes-after and comes-before rows are derived from every component's contract.", ""]
    if opts := options(b.cls):
        lines += ["## Options", "", *table(("Option", "Type", "Default", "Description"), opts)]
    if b.doc.body:
        lines += ["## Behavior", "", markdown(b.doc.body), ""]
    lines += ["## Contract", "", *_mermaid(b)]
    if b.doc.example:
        lines += ["## Example", "", "```python", b.doc.example, "```", ""]
    return "\n".join(lines)


def index_page(families: dict[str, list[ComponentDoc]], base: list[ComponentDoc], links: Links, root: Path) -> str:
    lines = ["# Components", "", "Every public component, by family: one page each with its contract, backends, options, "
             "behavior and where it comes in a pipeline. Terms are the [glossary](../reference/glossary.md)'s; "
             "contracts and the builder are in [pipelines](../reference/pipelines.md).", ""]
    for family, components in families.items():
        if not components:
            continue
        lines += [f"## {TITLES[family]}", "", f"`linecaster.components.{family}`", "",
                  *table(("Component", "What it does"), [(f"[`{b.name}`]({b.page})", markdown(b.doc.summary))
                                                     for b in components])]
    if base:
        lines += ["## Base classes", "", "`linecaster.core`: what the components above are built on; no pages of "
                  "their own.", "",
                  *table(("Class", "What it is for"), [(f"[`{b.name}`]({links.to(b.source, root)})",
                                                        markdown(b.doc.summary)) for b in base])]
    return "\n".join(lines)


def build(repo: Path | None = code.REPO):
    """The components by family with their contracts, the base classes, the derived positions and the scripts."""
    families = {f: collect(f) for f in FAMILIES}
    every = [b for components in families.values() for b in components]
    for b in every:
        contracts(b)
    return families, collect("base"), positions(every), used_in(repo)


def pages(out: str | Path, links: Links, catalog=None, catalog_dir: str | Path | None = None,
          repo: Path | None = code.REPO, built=None) -> dict[str, str]:
    """Every component page and the index, by path below ``out`` (``docs/components``), each with the generated header."""
    out = Path(out)
    catalog_dir = Path(catalog_dir) if catalog_dir is not None else out.parent / "catalog"
    families, base, position, scripts = built or build(repo)
    components = {b.name: b for bs in families.values() for b in bs}
    found = {"README.md": index_page(families, base, links, out)}
    for b in components.values():
        found[b.page] = component_page(b, components, position[b.name], scripts.get(b.name, []), catalog, links, out,
                                   catalog_dir)
    return {rel: f"{HEADER}\n{text.rstrip(chr(10))}\n" for rel, text in sorted(found.items())}
