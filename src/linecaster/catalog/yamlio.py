"""YAML with YAML 1.2 semantics, and Markdown documents with YAML front matter.

PyYAML implements YAML 1.1, where ``yes``, ``no``, ``on`` and ``off`` are booleans (the "Norway problem":
the language code ``NO`` becomes ``False``). ``load`` keeps 1.2's core schema for booleans: only ``true`` and
``false``. ``dump`` writes block style, keys in the given order, Unicode as is.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class Loader(yaml.SafeLoader):
    pass


# drop PyYAML's 1.1 bool resolver and add 1.2's (true/false in any capitalisation)
Loader.yaml_implicit_resolvers = {k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
                                  for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
                             list("tTfF"))


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):   # never &anchors in written files
        return True


def _str(dumper, s: str):
    # multi-line strings as literal blocks; strings PyYAML 1.1 would read as bools/numbers are quoted anyway
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)


Dumper.add_representer(str, _str)


def load(text: str) -> Any:
    return yaml.load(text, Loader=Loader)


def dump(data: Any) -> str:
    return yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


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
