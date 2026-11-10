"""Engines and pipelines described from their source, for the docs. Engines are read with ``ast``: nothing of
them is imported, so they need not be installed (their pins conflict; there is no environment with all of them).

Engines: the entry points in ``engines/*/pyproject.toml`` plus linecaster's own (``chat.v1`` and the rule-based
engines of ``linecaster.engines``), each class's docstring, ``step``, ``capabilities``, ``scripts`` and ``Options``
fields. Pipelines: the pipeline shapes of ``linecaster.pipelines`` (imported; they import no engine), their
``PIPELINE`` id, docstring, ``SLOTS``, the options ``options()`` adds, and their scripts in ``pipelines/``.
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
    scripts: list[str] = field(default_factory=list)            # rule-based engines: ISO 15924 codes, * for all
    adapters: dict[str, Path] = field(default_factory=dict)     # chat.v1: adapter name -> source


@dataclass
class Pipeline:
    id: str
    source: Path | None             # the pipeline script (pipelines/<name>.py), None without the checkout
    doc: str
    slots: dict[str, str]
    options: list[Option] = field(default_factory=list)
    shape: Path | None = None       # the source file of its pipeline shape (linecaster.pipelines.<name>)


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
    core = repo / "src" / "linecaster" / "adapters"
    if core.exists():
        classes = _classes(core)
        f, cls = classes["ChatAdapter"]
        e = Engine("chat.v1", "linecaster.adapters:ChatAdapter", "linecaster", f, _doc(cls), "recognition")
        for name, (src, c) in sorted(classes.items()):
            adapter = _class_value(c, "adapter")
            if isinstance(adapter, str):
                e.adapters[adapter] = src
        found[e.id] = e
    builtin = repo / "src" / "linecaster" / "engines"
    if builtin.exists():
        for name, (f, cls) in sorted(_classes(builtin).items()):
            eid = _class_value(cls, "engine_id")
            if isinstance(eid, str):
                found[eid] = Engine(eid, f"linecaster.engines:{name}", "linecaster", f, _doc(cls),
                                    _class_value(cls, "step"), _class_value(cls, "capabilities") or {}, _options(cls),
                                    scripts=list(_class_value(cls, "scripts") or []))
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


def script_of(shape, repo: Path | None = REPO) -> Path | None:
    """The pipeline script that runs the pipeline shape ``shape`` (a module of ``linecaster.pipelines``): the
    checkout's ``pipelines/<name>.py``, or ``None`` without a checkout or such a script."""
    if repo is None:
        return None
    script = repo / "pipelines" / f"{shape.__name__.rpartition('.')[2]}.py"
    return script if script.is_file() else None


def pipelines(repo: Path | None = REPO) -> dict[str, Pipeline]:
    """The pipeline shapes of ``linecaster.pipelines`` by pipeline id (imported: they import no engine), each with
    its pipeline script in the checkout ``repo`` (``source``; ``None`` without one), its docstring, slots and the
    options ``options()`` adds (read from its source with ``ast``)."""
    from ..pipelines import shapes

    found = {}
    for pid, shape in shapes().items():
        fn = ast.parse(inspect.getsource(shape.options)).body[0]
        found[pid] = Pipeline(pid, script_of(shape, repo), inspect.cleandoc(shape.__doc__ or ""),
                              dict(getattr(shape, "SLOTS", None) or {}), _arguments(fn),
                              Path(inspect.getsourcefile(shape)))
    return found


def script_dependencies(script: Path) -> list[str]:
    """The names of the dependencies a pipeline script's PEP 723 block lists (``[]`` without one)."""
    import re

    block, inside = [], False
    for line in script.read_text(encoding="utf-8").splitlines():
        if line.strip() == "# /// script":
            inside = True
        elif inside and line.strip() == "# ///":
            break
        elif inside:
            block.append(line[2:] if line.startswith("# ") else line.lstrip("#"))
    if not block:
        return []
    deps = tomllib.loads("\n".join(block)).get("dependencies", [])
    return [re.split(r"[\[<>=!~; @]", d, maxsplit=1)[0].strip().lower() for d in deps]


def install_hint(engine: str, repo: Path = REPO) -> str:
    """What installs an engine that is not installed, for an error message: the engine package that provides it
    (``engines/*/pyproject.toml``) and the pipeline scripts whose environments install that package; ``""`` when
    the repository does not say (an installed linecaster without its checkout, or an unknown engine)."""
    if repo is None or not (repo / "engines").is_dir():
        return ""
    found = engines(repo).get(engine)
    if found is None or found.package == "linecaster":
        return ""
    scripts = [f.relative_to(repo).as_posix() for f in sorted(repo.glob("pipelines/*.py"))
               if found.package in script_dependencies(f)]
    where = (f", which {' and '.join(f'`{s}`' for s in scripts)} install{'s' if len(scripts) == 1 else ''}"
             if scripts else ", which no pipeline script here installs: run it in an environment that adds it "
             "(squiddleocr's `squiddle.py` for kraken, or a script of your own), or against a server started from "
             "one (`--backend served --endpoint URL`)")
    return (f"`{engine}` is in the engine package `{found.package}` (engines/{found.source.relative_to(repo / 'engines').parts[0]}, "
            f"not on PyPI){where}")

