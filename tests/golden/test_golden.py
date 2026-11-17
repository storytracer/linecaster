"""Outputs do not change unseen: a pipeline of every rule-based step over the sample pages, with the fake engines,
gives the page records, page files, documents and texts stored in ``golden.json``. What may differ is scrubbed
(times, versions, hashes of catalog entries); a rename of a field or an id is applied to the stored side by
``RENAMED``, so a refactoring shows that it changed names only. ``python tests/golden/test_golden.py`` rewrites
the file, for a deliberate change of outputs (CHANGELOG.md, *Changed outputs*)."""
import json
import re
from pathlib import Path

from linecaster import document, formats
from linecaster.backends import InProcess
from linecaster.core.item import item_pages
from linecaster.core.page import page_of
from linecaster.components.items import ItemAssembler
from linecaster.components.document import DocumentComposer
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.layout import LayoutDetector
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.recognition import LineRecognizer
from linecaster.document import strategy
from linecaster.execution.builder import run_pages
from linecaster.testing import sample_documents
from linecaster.testing.samples import SAMPLE_TRANSCRIPTION

GOLDEN = Path(__file__).with_name("golden.json")
FAKE = "linecaster.testing:Fake{}Engine"
TEXTS = ("literal", "latin-historic+flow", "nfc+long-s+unicode-marks+flow")
LINES = ("Die Zeitung er-", "scheint täglich und", "koſtet vierteljähr-", "lich 2 Mark.", "Anzeigen 10 Pf.", "die Zeile.")

#: keys whose values differ from run to run or with the release
VOLATILE = {"seconds", "datetime", "linecaster", "decoder", "preset_sha256", "recipe_sha256", "producer"}
#: stored key -> today's key, and stored value -> today's value (ids of roles, engines and presets)
RENAMED: dict[str, str] = {}
RENAMED_VALUES: dict[str, str] = {
    "typography": "hierarchy", "recomposition": "paragraphs", "composition": "document",                 # 0.12: steps
    "typography.ratios.v1": "hierarchy.ratios.v1", "recomposition.unicode.v1": "paragraphs.unicode.v1",
    "composition.linked.v1": "document.linked.v1", "unicode-recomposition": "unicode-paragraphs",
    "linked-composition": "linked-document",
}

_VERSION = re.compile(r"\d+\.\d+\.\d+(?:\.dev\d+)? \([0-9a-f]{12}(?:, modified)?\)|\d+\.\d+\.\d+(?:\.dev\d+)?")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_HASH = re.compile(r"sha256:[0-9a-f]{64}")


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return _HASH.sub("sha256:#", _TIME.sub("TIME", _VERSION.sub("VERSION", value)))
    return value


def renamed(value):
    """The stored side as today's names give it."""
    if isinstance(value, dict):
        return {RENAMED.get(k, k): renamed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [renamed(v) for v in value]
    if isinstance(value, str):
        for old, new in RENAMED_VALUES.items():
            value = re.sub(rf"(?<![\w.-]){re.escape(old)}(?![\w-])", new, value)
    return value


def _models():
    """The model components, with the fake engines: the layout, the lines, their assignment and the readings."""
    return [LayoutDetector(InProcess(FAKE.format("Layout"), rows=2, cols=1)),
            LineDetector(InProcess(FAKE.format("Line"), split=3)), LineAssigner(),
            LineRecognizer(InProcess(FAKE.format("Recognition"), template="line {index}"))]


def _rules(unit: str = "page"):
    return [ParagraphBuilder("unicode-paragraphs", unit=unit), DocumentComposer("linked-document", unit=unit)]


def _samples():
    return sample_documents(3, text=True, lines=LINES)


def _texts(doc) -> dict:
    out = {"html": document.to_html(doc), "markdown": document.to_markdown(doc), "json": json.loads(document.to_json(doc))}
    for name in TEXTS:
        out[name] = document.to_text(doc if name == "literal" else strategy.apply(doc, name))
    return out


def _document(d):
    return document.load_document(d.metadata[document.DOCUMENT_KEY])


def outputs() -> dict:
    out: dict = {"modeled": [], "pages": [], "items": []}
    for d in run_pages(_models(), sample_documents(2, text=False)):
        out["modeled"].append(page_of(d).model_dump(mode="json", exclude_none=True))
    for d in run_pages([HierarchyDetector("ratios"), *_rules()], _samples()):
        page = page_of(d)
        t = page.transcriptions[SAMPLE_TRANSCRIPTION]
        size = {"image_width": page.image.width, "image_height": page.image.height}
        out["pages"].append({
            "record": page.model_dump(mode="json", exclude_none=True),
            "alto": formats.to_alto(t, **size).decode(), "page": formats.to_page(t, **size).decode(),
            "hocr": formats.to_hocr(t, **size).decode(), "document": _texts(_document(d)),
        })
    for d in run_pages([HierarchyDetector("ratios"), ItemAssembler(), *_rules("item")], _samples()):
        out["items"].append({"pages": [p.page_id for p in item_pages(d)], "document": _texts(_document(d))})
    return scrub(out)


def test_outputs_are_the_golden_ones():
    stored = renamed(json.loads(GOLDEN.read_text(encoding="utf-8")))
    now = outputs()
    assert now["items"] == stored["items"] and now["modeled"] == stored["modeled"]
    for a, b in zip(now["pages"], stored["pages"], strict=True):
        for key in b:
            assert a[key] == b[key], key


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(outputs(), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
