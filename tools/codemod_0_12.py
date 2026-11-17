"""Renames code written for linecaster 0.11 to the names of 0.12.

    python tools/codemod_0_12.py PATH [PATH ...]        # rewrites the .py, .md, .yaml, .yml and .toml files below
    python tools/codemod_0_12.py --dry-run PATH         # lists the files it would change

It moves imports to the modules' new places, splits imports from packages that were divided, and renames classes,
functions, options and ids. It changes names only where they are whole words; prose that used a renamed word in
another sense needs a look afterwards (``git diff``). CHANGELOG.md's upgrade notes for 0.12 say what each rename
means.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml"}
SKIP_NAMES = {"CHANGELOG.md", "NOTES.md", "codemod_0_12.py"}
SKIP_PARTS = {".git", ".venv", "site", "__pycache__", "upstream", "node_modules"}

#: modules, old dotted path -> new one; the first match wins, so the longer paths come first
MODULES: list[tuple[str, str]] = [
    ("linecaster.blocks.base.block", "linecaster.core.component"),
    ("linecaster.blocks.base", "linecaster.core"),
    ("linecaster.blocks.binding.binder", "linecaster.components.items.item_assembler"),
    ("linecaster.blocks.binding.splitter", "linecaster.components.items.item_splitter"),
    ("linecaster.blocks.binding", "linecaster.components.items"),
    ("linecaster.blocks.composition.composer", "linecaster.components.document.document_builder"),
    ("linecaster.blocks.composition.recomposer", "linecaster.components.paragraphs.paragraph_builder"),
    ("linecaster.blocks.composition.typographer", "linecaster.components.hierarchy.hierarchy_detector"),
    ("linecaster.blocks.conversion.images", "linecaster.components.images.image_converter"),
    ("linecaster.blocks.conversion.transcriptions", "linecaster.components.importers.transcription_importer"),
    ("linecaster.blocks.layout.detector", "linecaster.components.layout.layout_detector"),
    ("linecaster.blocks.lines.assigner", "linecaster.components.lines.line_assigner"),
    ("linecaster.blocks.lines.detector", "linecaster.components.lines.line_detector"),
    ("linecaster.blocks.recognition.chat", "linecaster.components.recognition.page_recognizer"),
    ("linecaster.blocks.scoring.pages", "linecaster.components.scoring.page_scorer"),
    ("linecaster.blocks.validation.pages", "linecaster.components.validation.page_validator"),
    ("linecaster.blocks.validation.recipe", "linecaster.components.validation.recipe_stamper"),
    ("linecaster.blocks.composites.modular", "linecaster.components.composites.modular_transcriber"),
    ("linecaster.blocks", "linecaster.components"),
    ("linecaster.runtime", "linecaster.execution"),
    ("linecaster.pipelines", "linecaster.templates"),
    ("linecaster.markup", "linecaster.conventions"),
    ("linecaster.scoring", "linecaster.evaluation"),
    ("linecaster.adapters", "linecaster.engines.chat"),
    ("linecaster.broker", "linecaster.net.broker"),
    ("linecaster.serve", "linecaster.serving"),
    ("linecaster.text.normalize", "linecaster.normalization.rules"),
    ("linecaster.text.latex", "linecaster.normalization.latex"),
    ("linecaster.text.formulas", "linecaster.normalization.formulas"),
    ("linecaster.text.recomposition", "linecaster.engines.paragraphs.rules"),
    ("linecaster.text.typography", "linecaster.engines.hierarchy.rules"),
    ("linecaster.engines.recomposition", "linecaster.engines.paragraphs.engine"),
    ("linecaster.engines.typography", "linecaster.engines.hierarchy.engine"),
    ("linecaster.engines.composition", "linecaster.engines.document"),
]

#: packages that were divided: old module -> the new module of each name imported from it
SPLIT: dict[str, dict[str, str]] = {
    "linecaster.components.composition": {
        "Composer": "linecaster.components.document", "Recomposer": "linecaster.components.paragraphs",
        "Typographer": "linecaster.components.hierarchy",
    },
    "linecaster.components.conversion": {
        "ImageConverter": "linecaster.components.images", "ImageFetcher": "linecaster.components.images",
        "TranscriptionImporter": "linecaster.components.importers",
    },
    "linecaster.components.recognition": {
        "TableRecognizer": "linecaster.components.tables", "FormulaRecognizer": "linecaster.components.formulas",
    },
    "linecaster.components.recognition.recognizers": {
        "LineRecognizer": "linecaster.components.recognition.line_recognizer",
        "TableRecognizer": "linecaster.components.tables.table_recognizer",
        "FormulaRecognizer": "linecaster.components.formulas.formula_recognizer",
    },
}

#: names, old -> new, as whole words
NAMES: list[tuple[str, str]] = [
    ("PageBlock", "PageComponent"), ("ModelBlock", "ModelComponent"), ("RuleBlock", "RuleComponent"),
    ("check_block", "check_component"),
    ("Typographer", "HierarchyDetector"), ("Recomposer", "ParagraphBuilder"), ("Composer", "DocumentComposer"),
    ("Binder", "ItemAssembler"), ("Splitter", "ItemSplitter"),
    ("ChatModelServer", "VLMServer"), ("ModelServer", "EngineServer"), ("ServiceServer", "VendorServer"),
    ("RatiosTypographyEngine", "RatiosHierarchyEngine"), ("UnicodeRecompositionEngine", "UnicodeParagraphsEngine"),
    ("ByScriptRecompositionEngine", "ByScriptParagraphsEngine"), ("LinkedCompositionEngine", "LinkedDocumentEngine"),
    ("unicode-recomposition", "unicode-paragraphs"), ("linked-composition", "linked-document"),
    ("SourceDocument", "SourceFile"), ("--trace-sample", "--trace-share"), ("trace_sample", "trace_share"),
    ("linecaster models", "linecaster presets"), ("linecaster truth", "linecaster ground-truth"),
    ("--truth", "--ground-truth"),
]

#: step ids, old -> new: renamed where they are ids (quoted, a flag, an attribute, a key), not in running prose
STEPS: list[tuple[str, str]] = [("typography", "hierarchy"), ("recomposition", "paragraphs"), ("composition", "document")]

#: modules whose ``Block`` is the pipeline's (a document's ``Block`` keeps its name)
BLOCK_HOMES = ("linecaster.core", "linecaster.core.component")


def _modules(text: str) -> str:
    for old, new in MODULES:
        text = re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w/])", new, text)
    return text


def _names(text: str) -> str:
    for old, new in NAMES:
        text = re.sub(rf"(?<![\w]){re.escape(old)}(?![\w])", new, text)
    return text


def _steps(text: str) -> str:
    for old, new in STEPS:
        text = re.sub(rf"(?<![\w-]){old}(\.[a-z-]+\.v\d+)", rf"{new}\1", text)                 # engine ids
        if old != "typography":                 # also a normalization's id, which keeps its name
            text = re.sub(rf"([\"'`]){old}(\1|\.[a-z_]+)", rf"\1{new}\2", text)                # "id", `id`, "id.option"
        text = re.sub(rf"--{old}(?![\w-])", f"--{new}", text)                                    # flags
        text = re.sub(rf"(?<!text)(?<!engines)(?<!\d)\.{old}(?![\w.(])", f".{new}", text)          # attributes
        text = re.sub(rf"^(\s*(?:step|{old}): ){old}$", rf"\1{new}", text, flags=re.M)            # step: id
        text = re.sub(rf"^(\s+){old}(: [\w-]+)$", rf"\1{new}\2", text, flags=re.M)               # a recipe's key
        text = re.sub(rf"\b{old}=", f"{new}=", text)                                             # keywords, --set
        text = re.sub(rf"presets/{old}\b", f"presets/{new}", text)
    return text


def _split_imports(text: str) -> str:
    """``from <divided package> import A, B`` as one import per new module."""
    if not any(m in text for m in SPLIT):
        return text
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.split("\n")
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module in SPLIT),
                       key=lambda n: -n.lineno):
        homes: dict[str, list[str]] = {}
        for alias in node.names:
            home = SPLIT[node.module].get(alias.name, node.module)
            homes.setdefault(home, []).append(alias.name + (f" as {alias.asname}" if alias.asname else ""))
        indent = " " * node.col_offset
        new = [f"{indent}from {home} import {', '.join(names)}" for home, names in sorted(homes.items())]
        lines[node.lineno - 1:node.end_lineno] = new
    return "\n".join(lines)


def _module_imports(text: str) -> str:
    """``from linecaster import broker`` and the like: a moved module imported by name from its package, under the
    name the code uses."""
    moved = dict(MODULES)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.split("\n")
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and not n.level),
                       key=lambda n: -n.lineno):
        if not any(f"{node.module}.{a.name}" in moved for a in node.names):
            continue
        indent, new, kept = " " * node.col_offset, [], []
        for a in node.names:
            target = moved.get(f"{node.module}.{a.name}")
            if target is None:
                kept.append(a.name + (f" as {a.asname}" if a.asname else ""))
                continue
            parent, _, leaf = target.rpartition(".")
            name = a.asname or a.name
            new.append(f"{indent}from {parent} import {leaf}" + (f" as {name}" if name != leaf else ""))
        if kept:
            new.insert(0, f"{indent}from {node.module} import {', '.join(kept)}")
        lines[node.lineno - 1:node.end_lineno] = new
    return "\n".join(lines)


def _pipeline_block(text: str) -> str:
    """``Block`` -> ``Component`` in a module that imports the pipeline's."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    if any(isinstance(n, ast.ImportFrom) and n.module in BLOCK_HOMES and any(a.name == "Block" for a in n.names)
           for n in ast.walk(tree)):
        text = re.sub(r"(?<![\w])Block(?![\w])", "Component", text)
    return text


def _fenced(text: str) -> str:
    """The Python code blocks of a Markdown file, their imports split like a module's."""
    return re.sub(r"(```python\n)(.*?)(```)", lambda m: m.group(1) + _split_imports(m.group(2)) + m.group(3), text,
                  flags=re.S)


def rewrite(text: str, python: bool) -> str:
    if python:
        text = _module_imports(text)
    text = _steps(_names(_modules(text)))
    return _pipeline_block(_split_imports(text)) if python else _fenced(text)


def files(paths: list[str]):
    for root in map(Path, paths):
        for p in ([root] if root.is_file() else sorted(root.rglob("*"))):
            if (p.is_file() and p.suffix in SUFFIXES and p.name not in SKIP_NAMES
                    and not SKIP_PARTS.intersection(p.parts)):
                yield p


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    for p in files(paths):
        try:
            old = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rewrite(old, p.suffix == ".py")
        if new != old:
            print(p)
            if not dry:
                p.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
