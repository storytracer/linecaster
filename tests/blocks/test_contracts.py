"""Block contracts and the two block shapes: every block of ``linecaster.blocks`` declares its contract; model
blocks take their parts from their preset or engine; only readers and writers know about tasks."""
import ast
import importlib
import inspect
import pkgutil
import re
import textwrap
from pathlib import Path

import pytest
from datatrove.pipeline.base import PipelineStep

import linecaster.blocks
from linecaster.backends import InProcess, Served
from linecaster.blocks.base.contract import Contract, Part, contract_of, parts
from linecaster.catalog.schema import PARTS, PRODUCES

ROOT = Path(__file__).resolve().parents[2]


def block_classes() -> list[type]:
    out = []
    for m in pkgutil.walk_packages(linecaster.blocks.__path__, "linecaster.blocks."):
        module = importlib.import_module(m.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, PipelineStep):
                out.append(cls)
    return sorted(set(out), key=lambda c: (c.__module__, c.__name__))


def family(cls: type) -> str:
    return cls.__module__.split(".")[2]


def test_every_block_has_a_contract():
    classes = block_classes()
    assert len(classes) >= 30
    missing = [c.__name__ for c in classes if not callable(getattr(c, "contract", None))]
    assert missing == []


def test_the_part_vocabulary():
    assert set(PRODUCES) < set(PARTS)
    assert {"image", "metadata", "line_regions", "hierarchy", "nfc", "document"} <= set(PARTS)
    assert str(Part("lines", "ocr_new")) == "ocr_new:lines" and str(Part("image")) == "image"
    assert Part.parse("ocr_original:*") == Part("*", "ocr_original") and Part.parse("metadata") == Part("metadata")
    assert Part("*", "ocr_original").covers(Part("lines", "ocr_original"))
    assert not Part("*", "ocr_original").covers(Part("lines", "ocr_new")) and Part("*").covers(Part("text", "x"))
    assert parts(("image", "lines"), "t") == {Part("image"), Part("lines", "t")}
    with pytest.raises(ValueError):
        Part("paragraph", "ocr_new")
    with pytest.raises(ValueError):
        Contract(unit="line")


def test_glossary_names_every_part():
    glossary = (ROOT / "docs" / "reference" / "glossary.md").read_text()
    missing = [p for p in ("image", "metadata", "line_regions", "hierarchy", "nfc", "document")
               if not re.search(rf"\| `{p}` \|", glossary)]
    assert missing == []


def test_model_blocks_take_their_parts_from_the_preset_or_the_engine():
    from linecaster.blocks.layout import LayoutDetector
    from linecaster.blocks.lines import LineDetector
    from linecaster.blocks.recognition import LineRecognizer, TableRecognizer

    rec = InProcess("x:Y")
    rec.preset = "kraken-ppocrv6-medium@1"
    c = LineRecognizer(rec).contract()
    assert c.role == "model" and c.unit == "page"
    assert c.reads == {Part("image"), Part("lines", "ocr_new")}
    assert {p.name for p in c.adds} == {"text", "words", "word_confidences", "line_confidences"}
    # an engine without a preset: its declared capabilities (read from its source, nothing imported)
    assert {p.name for p in TableRecognizer(InProcess("linecaster_paddlex:PaddleTableEngine")).contract().adds} == {
        "tables", "html"}
    # neither: the step's default
    assert {p.name for p in TableRecognizer(InProcess("nowhere:Engine")).contract().adds} == {"tables"}
    # served: the preset the server hosts
    layout = LayoutDetector(Served("http://127.0.0.1:8100/v1", model="layout", preset="pp-doclayoutv3@1"))
    assert {p.name for p in layout.contract().adds} == {"regions", "reading_order"} and layout.shape == "stream"
    assert LineDetector(InProcess("x:Y"), transcription="mine").contract().adds == {Part("lines", "mine")}


def test_served_backends_carry_the_preset(monkeypatch):
    import linecaster.catalog.registry as registry
    from linecaster.runtime import run

    class R:
        ref, sha256 = "pp-doclayoutv3@1", "sha256:" + "0" * 64

    monkeypatch.setattr(registry, "engine_spec", lambda ref: ("linecaster_paddlex:PaddleLayoutEngine", {}, R()))
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["images", "out", "--backend", "served"]))
    backends, servers = run.engines(a, [{"name": "layout", "preset": "pp-doclayoutv3"}], "script.py")
    b = backends["layout"]
    assert (b.preset, b.engine, b.model) == ("pp-doclayoutv3@1", "linecaster_paddlex:PaddleLayoutEngine", "layout")
    assert type(servers[0]).__name__ == "ModelServer"


def test_chat_recognizers():
    from linecaster.adapters import chat_model
    from linecaster.blocks.recognition import PageRecognizer, RegionRecognizer

    backend = Served("http://127.0.0.1:8000/v1", model="m")
    page = PageRecognizer(chat_model("lightonocr-2-1b"), backend).contract()
    assert page.reads == {Part("image")} and {str(p) for p in page.adds} == {"ocr_new:text", "ocr_new:markdown"}
    regions = RegionRecognizer(chat_model("lightonocr-2-1b-regions"), backend).contract()
    assert regions.reads == {Part("image"), Part("regions", "ocr_new")}
    assert {p.name for p in regions.adds} == {"lines", "text", "markdown"}
    assert PageRecognizer(chat_model("lightonocr-2-1b"), backend).shape == "stream"


def test_contracts_of_the_blocks_without_a_model(tmp_path):
    from linecaster.blocks.binding import BindItem, ItemTexts
    from linecaster.blocks.composition import Composer, Typographer
    from linecaster.blocks.conversion import ImageConverter
    from linecaster.blocks.lines import LineAssigner
    from linecaster.blocks.readers import ImageFolderReader, ManifestReader, PageRecordReader
    from linecaster.blocks.servers import ModelServer
    from linecaster.blocks.text import UnicodeNormalizer
    from linecaster.blocks.writers import ItemDocumentWriter, ItemTextWriter, PageFileWriter, PageJsonlWriter

    def names(ps):
        return sorted(map(str, ps))

    assert names(ImageFolderReader("x").contract().adds) == ["image", "metadata"]
    assert ManifestReader(str(tmp_path), existing_ocr=True).contract().adds >= {Part("*", "ocr_original")}
    assert ManifestReader(str(tmp_path)).contract().adds == {Part("image"), Part("metadata")}
    assert PageRecordReader(str(tmp_path)).contract().adds == {Part("*"), Part("image"), Part("metadata")}
    r = PageRecordReader(str(tmp_path), fetch_images=False, provides=["ocr_new:lines", Part("text", "ocr_new")])
    assert names(r.contract().adds) == ["metadata", "ocr_new:lines", "ocr_new:text"] and not r.whole_items
    assert PageRecordReader(str(tmp_path), item_shards=True).whole_items
    a = LineAssigner().contract()
    assert names(a.adds) == ["ocr_new:line_regions"] and Part("lines", "ocr_new") in a.replaces
    assert names(UnicodeNormalizer().contract().adds) == ["ocr_new:nfc"]
    assert names(Typographer().contract().adds) == ["ocr_new:hierarchy"]
    assert names(Composer().contract().adds) == ["ocr_new:document"]
    assert (ItemTexts().contract().unit, ItemTexts().contract().unit_out) == ("page", "item")
    assert BindItem().contract().adds == {Part("document")} and BindItem().contract().role == "binder"
    assert ItemTextWriter(str(tmp_path)).contract().reads == {Part("text")}
    assert ItemDocumentWriter(str(tmp_path)).contract() == Contract(unit="item", role="writer",
                                                                   reads=frozenset({Part("document")}))
    files = PageFileWriter(str(tmp_path), formats=("hocr", "md", "json", "plot", "transcription")).contract()
    assert names(files.reads) == ["image", "ocr_new:document", "ocr_new:lines", "ocr_new:text"]
    assert PageJsonlWriter(str(tmp_path)).contract() == Contract(unit="page", role="writer")
    assert ModelServer([]).contract().unit == "any" and ModelServer([]).contract().role == "server"
    assert names(ImageConverter(str(tmp_path), str(tmp_path), keep_bytes=True).contract().replaces) == [
        "image", "metadata"]
    assert contract_of(object()) == Contract(unit="page", role="transform")


# ------------------------------------------------------------------------------------------------ block shapes

#: blocks outside readers and writers that still name their task: they write rejects files named per task
#: (``RejectWriter(folder, rank)``), which move to the rejects writer with the per-page failures
TASK_AWARE = {"ImageConverter": "rejects file per task", "PageValidator": "rejects file per task"}


TASK = ("rank", "world_size")


def task_uses(cls: type) -> list[str]:
    """Where a class's methods use the ``rank`` or ``world_size`` they are given, other than passing them on to a
    ``run`` call (``super().run(data, rank, world_size)``)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        given = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]} & set(TASK)
        if not given:
            continue
        passed = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run":
                passed |= {id(a) for a in node.args} | {id(k.value) for k in node.keywords}
        out += [f"{cls.__name__} line {n.lineno}: {n.id}" for n in ast.walk(fn)
                if isinstance(n, ast.Name) and n.id in given and id(n) not in passed]
    return out


def test_only_readers_and_writers_know_about_tasks():
    offenders = []
    for cls in block_classes():
        if family(cls) in ("readers", "writers") or cls.__name__ in TASK_AWARE:
            continue
        offenders += task_uses(cls)
    assert offenders == []


def test_the_rule_finds_a_block_that_uses_its_rank():
    class Peeks(PipelineStep):
        def run(self, data, rank: int = 0, world_size: int = 1):
            for doc in data:
                doc.metadata["rank"] = rank
                yield doc

    class Passes(PipelineStep):
        def run(self, data, rank: int = 0, world_size: int = 1):
            yield from super().run(data, rank, world_size)

    assert task_uses(Peeks) == ["Peeks line 4: rank"] and task_uses(Passes) == []
    assert all(task_uses(importlib.import_module("linecaster.blocks." + m).__dict__[c])
               for m, c in (("conversion.images", "ImageConverter"), ("validation.pages", "PageValidator")))


def test_the_two_shapes():
    from linecaster.blocks.base.page import PageBlock
    from linecaster.blocks.lines import LineAssigner, LineDetector

    assert PageBlock.shape == "unit" and LineAssigner().shape == "unit"
    assert LineDetector(InProcess("x:Y")).shape == "unit"
    assert LineDetector(Served("http://127.0.0.1:8100/v1", model="lines")).shape == "stream"
