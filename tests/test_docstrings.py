"""The docstring standard (``docs/reference/conventions.md``, "Docstrings"): every public block, built-in engine,
backend, serializer, ``build``, ``run_pages``, ``runtime.run.main``, public catalog function and public name of the
engine API and the test helpers (``API_MODULES``) has a summary line,
and its ``Args:`` names every parameter of its signature (a class's constructor) and no other; the serializers,
``build``, ``main`` and the catalog functions have an ``Example:``. The docstrings are read from the source with
``ast`` (a dataclass's generated ``__doc__`` does not count); signatures with ``inspect``."""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from functools import lru_cache

from linecaster.blocks.base.block import Block
from linecaster.docs import docstrings
from linecaster.docs.blocks import FAMILIES

ENGINES = "linecaster.engines"
BACKENDS = ("linecaster.backends:InProcess", "linecaster.backends:Served", "linecaster.backends:Chat")
FUNCTIONS = ("linecaster.runtime.builder:build", "linecaster.runtime.builder:run_pages", "linecaster.runtime.run:main")
CATALOG = ("linecaster.catalog:catalog", "linecaster.catalog:engine_class", "linecaster.catalog:engine_ids",
           "linecaster.catalog:engine_spec")
SERIALIZERS = tuple(f"linecaster.formats:{n}" for n in importlib.import_module("linecaster.formats").__all__)
EXAMPLE_REQUIRED = (*FUNCTIONS[::2], *CATALOG, *SERIALIZERS)          # build and main, not run_pages
#: modules whose every public name (``__all__``, defined there) follows the standard
API_MODULES = ("linecaster.engines.api", "linecaster.testing", "linecaster.testing.markers")


def _get(target: str):
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def targets() -> dict[str, object]:
    out = {}
    for family in (*FAMILIES, "base"):
        m = importlib.import_module(f"linecaster.blocks.{family}")
        for name in m.__all__:
            obj = getattr(m, name)
            if inspect.isclass(obj) and issubclass(obj, Block):
                out[f"{obj.__module__}:{name}"] = obj
    engines = importlib.import_module(ENGINES)
    for name in engines.__all__:
        obj = getattr(engines, name)
        if inspect.isclass(obj) and hasattr(obj, "engine_id"):
            out[f"{obj.__module__}:{name}"] = obj
    for module in API_MODULES:
        m = importlib.import_module(module)
        for name in m.__all__:
            obj = getattr(m, name)
            if (inspect.isfunction(obj) or inspect.isclass(obj)) and obj.__module__.startswith(module):
                out[f"{obj.__module__}:{name}"] = obj
    for t in (*BACKENDS, *FUNCTIONS, *CATALOG, *SERIALIZERS):
        obj = _get(t)
        out[f"{obj.__module__}:{obj.__qualname__}"] = obj
    return out


@lru_cache(maxsize=None)
def _tree(path: str) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def source_doc(obj) -> str | None:
    """The docstring as written in the source, read with ``ast`` (a decorated function's own)."""
    obj = inspect.unwrap(obj)
    path = inspect.getsourcefile(obj)
    for node in _tree(path).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == obj.__name__:
            return ast.get_docstring(node)
    return None


#: a sentence's end inside the summary
ONE_SENTENCE = re.compile(r"\.\s+\S")


def constructs(obj) -> bool:
    """Whether ``obj`` is a function, or a class with a constructor of its own or of a linecaster base (a base
    class whose constructor is datatrove's, as ``PageBlock``, documents none)."""
    if not inspect.isclass(obj):
        return True
    if getattr(obj, "_is_protocol", False):         # a protocol is not constructed
        return False
    for c in obj.__mro__:
        if not c.__module__.startswith("linecaster."):
            return False
        if "__init__" in c.__dict__ or "__dataclass_fields__" in c.__dict__:
            return True
    return False


def parameters(obj) -> list[str]:
    return [p.name for p in inspect.signature(obj).parameters.values()]


def documented_args(obj) -> tuple[dict[str, str], dict[str, str]]:
    """The ``Args:`` of ``obj`` itself, and those it has with its bases': a class that keeps its base's constructor
    keeps its base's ``Args:`` (the classes of the MRO up to the one that defines ``__init__``)."""
    own = docstrings.parse(source_doc(obj)).args
    if not inspect.isclass(obj):
        return own, own
    merged: dict[str, str] = {}
    chain = []
    for c in obj.__mro__:
        if not c.__module__.startswith("linecaster."):
            break
        chain.append(c)
        if "__init__" in c.__dict__ or "__dataclass_fields__" in c.__dict__:
            break
    for c in reversed(chain):
        merged.update(docstrings.parse(source_doc(c)).args)
    return own, merged


def problems_of(target: str, obj) -> list[str]:
    raw = source_doc(obj)
    if not raw:
        return [f"{target}: no docstring"]
    d = docstrings.parse(raw)
    out = [f"{target}: {p}" for p in d.problems]
    if not d.summary:
        out.append(f"{target}: no summary line")
    elif not d.summary.endswith(".") or ONE_SENTENCE.search(d.summary.replace("e.g. ", "").replace("i.e. ", "")):
        out.append(f"{target}: the summary line is not one sentence: {d.summary!r}")
    own, merged = documented_args(obj)
    params = parameters(obj) if constructs(obj) else []
    missing = [p for p in params if p not in merged]
    unknown = [a for a in own if a not in params]
    if missing:
        out.append(f"{target}: Args: misses {', '.join(missing)}")
    if unknown:
        out.append(f"{target}: Args: names {', '.join(unknown)}, which the signature does not have")
    if any(_get(t) is obj for t in EXAMPLE_REQUIRED) and not d.example:
        out.append(f"{target}: no Example:")
    return out


def test_the_docstrings_follow_the_standard():
    problems = [p for target, obj in sorted(targets().items()) for p in problems_of(target, obj)]
    assert problems == [], "\n".join(problems)


def test_the_parser_reads_google_style():
    d = docstrings.parse('''Does a thing.

    More about it.

    Args:
        a: the first,
            continued.
        b, c: datatrove's arguments.
        **kwargs: the rest.

    Example:
        thing(1)
    ''')
    assert d.summary == "Does a thing." and d.body == "More about it."
    assert d.args == {"a": "the first, continued.", "b": "datatrove's arguments.", "c": "datatrove's arguments.",
                      "kwargs": "the rest."}
    assert d.example == "thing(1)" and d.problems == []
