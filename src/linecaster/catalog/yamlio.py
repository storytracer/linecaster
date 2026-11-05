"""YAML for every file linecaster reads or writes (the catalog, run records), with ``ruamel.yaml``.

YAML 1.2: only ``true`` and ``false`` are booleans (the language code ``NO`` stays a string), and a duplicate key
is an error. ``load`` / ``read`` give plain Python data; ``load_rt`` / ``read_rt`` a round-trip document that
keeps its comments, quotes and order, for tools that write a file back (``update`` merges new data into it,
``dump_rt`` writes it). ``dump`` writes plain data in block style, keys in the given order, Unicode as is,
multi-line strings as literal blocks.

A catalog file names its JSON Schema in its first line (``MODELINE``), for editors.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString

#: the first line of a catalog file: its JSON Schema, relative to the file
MODELINE = "# yaml-language-server: $schema={}"
_MODELINE = re.compile(r"^# yaml-language-server: \$schema=(\S+)\s*$")


def _yaml(typ: str) -> YAML:
    y = YAML(typ=typ, pure=True)
    y.allow_duplicate_keys = False
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 100
    y.indent(mapping=2, sequence=2, offset=0)
    if typ == "rt":
        y.preserve_quotes = True
    return y


def load(text: str) -> Any:
    """Plain data (dicts, lists, scalars) from YAML 1.2 text."""
    return _yaml("safe").load(text)


def read(path: str | Path) -> Any:
    return load(Path(path).read_text(encoding="utf-8"))


def load_rt(text: str) -> Any:
    """A round-trip document (``CommentedMap``...): its comments, quotes and order are kept by ``dump_rt``."""
    return _yaml("rt").load(text)


def read_rt(path: str | Path) -> Any:
    return load_rt(Path(path).read_text(encoding="utf-8"))


def _literal(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _literal(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_literal(v) for v in data]
    if isinstance(data, str) and "\n" in data and type(data) is str:
        return LiteralScalarString(data)
    return data


def _dump(y: YAML, data: Any) -> str:
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def dump(data: Any) -> str:
    """Plain data as YAML 1.2 text (no anchors: shared objects are written out each time)."""
    y = _yaml("rt")
    y.representer.ignore_aliases = lambda _data: True
    return _dump(y, _literal(data))


def dump_rt(doc: Any) -> str:
    """A round-trip document as text, with its comments."""
    return _dump(_yaml("rt"), doc)


def update(doc: Any, data: Any) -> Any:
    """``data`` merged into the round-trip document ``doc``, keeping the comments of what stays: mappings are
    updated key by key (new keys where they sort among the existing ones when those are sorted, else at the
    end; keys ``data`` lacks are removed), anything else is replaced unless equal. Returns the merged value."""
    if isinstance(doc, CommentedMap) and isinstance(data, dict):
        for k in [k for k in doc if k not in data]:
            del doc[k]
        ordered = list(doc) == sorted(doc)
        for k, v in data.items():
            if k in doc:
                doc[k] = update(doc[k], v)
            elif ordered:
                pos = sum(1 for x in doc if x < k)
                doc.insert(pos, k, _literal(v))
            else:
                doc[k] = _literal(v)
        return doc
    if isinstance(doc, CommentedSeq) and isinstance(data, (list, tuple)) and len(doc) == len(data):
        for i, v in enumerate(data):
            doc[i] = update(doc[i], v)
        return doc
    return doc if _plain(doc) == data else _literal(data)


def _plain(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def modeline(path: str | Path) -> str | None:
    """The ``$schema`` path a file's first line names, or ``None``."""
    with open(path, encoding="utf-8") as f:
        m = _MODELINE.match(f.readline())
    return m.group(1) if m else None


FRONT = re.compile(r"\A---\n(?P<meta>.*?)\n---\n?(?P<body>.*)\Z", re.S)


def read_front_matter(path: str | Path) -> tuple[dict, str]:
    """``(front matter, body)`` of a Markdown document that starts with ``---``."""
    text = Path(path).read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        raise ValueError(f"{path}: no YAML front matter (the file must start with ---)")
    meta = load(m.group("meta")) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: the front matter is not a mapping")
    return meta, m.group("body")


def write_front_matter(path: str | Path, meta: dict, body: str = "") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(f"---\n{dump(meta)}---\n{body if body.startswith(chr(10)) or not body else chr(10) + body}",
                          encoding="utf-8")
