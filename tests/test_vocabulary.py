"""One vocabulary: the terms linecaster retired stay out of the code, the catalog and the docs, and the glossary
defines each of its terms once. A retired term may appear where a file reads or names what was (``ALLOWED``);
CHANGELOG.md and NOTES.md are history and are not read."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHERE = ("src", "engines", "pipelines", "recipes", "docs/reference", "README.md", "CLAUDE.md", "launch.py")
SUFFIXES = {".py", ".md", ".yaml", ".toml"}

#: retired term (a regular expression) -> what to write instead
RETIRED = {
    r"\b(Page|Model|Rule)Block\b|\bcheck_block\b|linecaster\.blocks\b": "components (linecaster.components, linecaster.core)",
    r"\b(pipeline|model|rule|composite|server|served|item|public) blocks?\b": "component",
    r"\bTypographer\b|\bRecomposer\b|\bComposer\b|\bBinder\b": "HierarchyDetector, ParagraphBuilder, DocumentComposer, ItemAssembler",
    r"\bChatModelServer\b|\bModelServer\b|\bServiceServer\b": "VLMServer, EngineServer, VendorServer",
    r"\bSourceDocument\b": "SourceFile",
    r"linecaster\.(runtime|pipelines|markup|scoring|adapters|serve)\b(?!/)": "execution, templates, conventions, evaluation, "
                                                                           "engines.chat, serving",
    r"\bpipeline shapes?\b": "pipeline template",
    r"id@edition|\bpreset editions?\b|\brecipe editions?\b": "a catalog entry's id",
    r"\bRetyper\b|\bStepInfo\b": "the hierarchy step, Annotator",
    r"\bderivatives?\b(?! of a master)": "downstream project",
    r"linecaster (models|truth)\b|--truth\b|--trace-sample\b": "linecaster presets, linecaster ground-truth, --ground-truth, "
                                                              "--trace-share",
    r"--(typography|recomposition|composition)\b": "--hierarchy, --paragraphs, --document",
    r"\b(typography|recomposition|composition)\.[a-z-]+\.v\d\b|unicode-recomposition|linked-composition":
        "hierarchy.*, paragraphs.*, document.* engines; unicode-paragraphs, linked-document",
}
#: files that read or name what was: (path prefix, the retired terms' patterns it may hold, or None for all)
ALLOWED = (
    ("src/linecaster/data/upgrade.py", None),               # the formats of earlier page records
    ("src/linecaster/catalog/registry.py", None),           # RENAMED: ids of earlier releases
    ("src/linecaster/catalog/data/models/", None),          # upstream cards, verbatim
    ("docs/reference/compatibility.md", None),
    ("src/linecaster/evaluation/evidence_format.py", r"edition"),   # evidence records of earlier formats named editions
    ("src/linecaster/evaluation/benchmark.py", r"edition"), # a benchmark has editions
    ("docs/reference/evaluation.md", r"edition"),
    ("docs/reference/catalog.md", r"edition"),              # how a reference from before 0.10 resolves
    ("src/linecaster/execution/record.py", r"edition"),
    ("src/linecaster/data/transcription.py", r"edition"),
    ("docs/reference/data-model.md", r"StepInfo|derivative"),   # the page/2 upgrade table; an image's derivative
    ("docs/reference/serialization.md", r"derivative"),     # an access derivative: an image's
    ("src/linecaster/data/page.py", r"derivative"),         # a scaled derivative: an image's
)


def files():
    for where in WHERE:
        root = ROOT / where
        for p in ([root] if root.is_file() else sorted(root.rglob("*"))):
            if p.is_file() and p.suffix in SUFFIXES and not {"__pycache__", ".venv", "upstream"} & set(p.parts):
                yield p


def allowed(rel: str, pattern: str) -> bool:
    return any(rel.startswith(prefix) and (only is None or re.search(only, pattern)) for prefix, only in ALLOWED)


def test_retired_terms_stay_out():
    found = []
    for p in files():
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pattern, instead in RETIRED.items():
            if allowed(rel, pattern):
                continue
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                found.append(f"{rel}:{line}: {m.group(0)!r} (write: {instead})")
    assert found == []


def test_the_glossary_defines_each_term_once():
    glossary = (ROOT / "docs" / "reference" / "glossary.md").read_text(encoding="utf-8")
    terms = [t for row in re.findall(r"^\| (\*\*.+?\*\*(?:, \*\*.+?\*\*)*) \|", glossary, flags=re.M)
             for t in re.findall(r"\*\*(.+?)\*\*", row)]
    assert len(terms) > 100
    assert sorted(t for t in set(terms) if terms.count(t) > 1) == []
