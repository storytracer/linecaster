"""Engines and pipelines described from their source (``ast``), for the docs: nothing is imported, so the
engines need not be installed (their pins conflict; there is no environment with all of them).

Engines: the entry points in ``engines/*/pyproject.toml`` plus linecaster's own (``chat.v1``), each class's
docstring, ``step``, ``capabilities`` and ``Options`` fields. Pipelines: ``pipelines/*.py`` with a
``PIPELINE`` id, their docstring, ``SLOTS`` and the options ``options()`` adds.
"""
from __future__ import annotations

import ast
import inspect
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: the repository checkout this package lives in (``None`` when installed from a wheel)
REPO = Path(__file__).resolve().parents[3]


@dataclass
class Option:
    name: str
    type: str
    default: str
    description: str


@dataclass
class Engine:
    id: str
    target: str                 # module:Class
    package: str
    source: Path
    doc: str
    step: str | None
    capabilities: dict = field(default_factory=dict)
    options: list[Option] = field(default_factory=list)
    adapters: dict[str, Path] = field(default_factory=dict)     # chat.v1: adapter name -> source


@dataclass
class Pipeline:
    id: str
    source: Path
    doc: str
    slots: dict[str, str]
    options: list[Option] = field(default_factory=list)


def _doc(node) -> str:
    return inspect.cleandoc(ast.get_docstring(node, clean=False) or "")


def _literal(node):
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


def _classes(root: Path) -> dict[str, tuple[Path, ast.ClassDef]]:
    out = {}
    for f in sorted(root.rglob("*.py")):
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                out.setdefault(node.name, (f, node))
    return out


def _class_value(cls: ast.ClassDef, name: str):
    for node in cls.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign)
                                                                       else None)
        if isinstance(target, ast.Name) and target.id == name and node.value is not None:
            return _literal(node.value)
    return None


def _options(cls: ast.ClassDef) -> list[Option]:
    """The fields of the nested ``Options`` model: ``name: type = Field(default, description=...)``."""
    opts = next((n for n in cls.body if isinstance(n, ast.ClassDef) and n.name == "Options"), None)
    out = []
    for node in opts.body if opts else []:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        value, default, desc = node.value, "", ""
        if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Field":
            if value.args:
                default = ast.unparse(value.args[0])
            for kw in value.keywords:
                if kw.arg == "description":
                    desc = " ".join(str(_literal(kw.value) or "").split())
                elif kw.arg == "default_factory":
                    default = f"{ast.unparse(kw.value)}()"
        elif value is not None:
            default = ast.unparse(value)
        out.append(Option(node.target.id, ast.unparse(node.annotation), default, desc))
    return out


def engines(repo: Path = REPO) -> dict[str, Engine]:
    found = {}
    core = repo / "src" / "linecaster" / "models"
    if core.exists():
        classes = _classes(core)
        f, cls = classes["ChatModel"]
        e = Engine("chat.v1", "linecaster.models:ChatModel", "linecaster", f, _doc(cls), "page")
        for name, (src, c) in sorted(classes.items()):
            adapter = _class_value(c, "adapter")
            if isinstance(adapter, str):
                e.adapters[adapter] = src
        found[e.id] = e
    for pyproject in sorted(repo.glob("engines/*/pyproject.toml")):
        meta = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        classes = _classes(pyproject.parent / "src")
        for eid, target in meta["project"].get("entry-points", {}).get("linecaster.engines", {}).items():
            f, cls = classes[target.partition(":")[2]]
            found[eid] = Engine(eid, target, meta["project"]["name"], f, _doc(cls), _class_value(cls, "step"),
                                _class_value(cls, "capabilities") or {}, _options(cls))
    return found


def _arguments(fn: ast.FunctionDef) -> list[Option]:
    """The options ``fn(ap)`` adds: every ``*.add_argument("--flag", ..., help=...)``."""
    out = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument" and node.args):
            continue
        flag = _literal(node.args[0])
        if not (isinstance(flag, str) and flag.startswith("--")):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        typ = ""
        if "choices" in kw:
            typ = " \\| ".join(str(c) for c in (_literal(kw["choices"]) or []))
        elif "type" in kw:
            typ = ast.unparse(kw["type"])
        elif "action" in kw and _literal(kw["action"]) in ("store_true", "store_false"):
            typ = "flag"
        default = ast.unparse(kw["default"]) if "default" in kw else ""
        help_ = " ".join(str(_literal(kw["help"]) or "").split()) if "help" in kw else ""
        out.append(Option(flag, typ, default, help_))
    return out


def pipelines(repo: Path = REPO) -> dict[str, Pipeline]:
    found = {}
    for f in sorted(repo.glob("pipelines/*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        values = {t.id: _literal(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        if not isinstance(values.get("PIPELINE"), str):
            continue
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "options"), None)
        found[values["PIPELINE"]] = Pipeline(values["PIPELINE"], f, _doc(tree), values.get("SLOTS") or {},
                                             _arguments(fn) if fn else [])
    return found
