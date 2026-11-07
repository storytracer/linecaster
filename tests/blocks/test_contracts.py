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
from linecaster.errors import PipelineConfigError

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
    with pytest.raises(PipelineConfigError):
        Part("paragraph", "ocr_new")
    with pytest.raises(PipelineConfigError):
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

    monkeypatch.setattr(registry, "engine_spec", lambda ref, installed=True, served=False: ("linecaster_paddlex:PaddleLayoutEngine", {}, R()))
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["images", "out", "--backend", "served"]))
    backends, servers = run.engines(a, [{"name": "layout", "preset": "pp-doclayoutv3"}], "script.py")
    b = backends["layout"]
    assert (b.preset, b.engine, b.model) == ("pp-doclayoutv3@1", "linecaster_paddlex:PaddleLayoutEngine", "layout")
    assert type(servers[0]).__name__ == "ModelServer"


def test_chat_recognizers():
    from linecaster.adapters import chat_model
    from linecaster.blocks.recognition import PageRecognizer, RegionRecognizer

    from linecaster.backends import Chat

    page = PageRecognizer(Chat(chat_model("lightonocr-2-1b"))).contract()
    assert page.reads == {Part("image")} and {str(p) for p in page.adds} == {"ocr_new:text", "ocr_new:markdown"}
    regions = RegionRecognizer(Chat("lightonocr-2-1b-regions")).contract()
    assert regions.reads == {Part("image"), Part("regions", "ocr_new")}
    assert {p.name for p in regions.adds} == {"lines", "text", "markdown"}
    assert PageRecognizer("lightonocr-2-1b").shape == "stream"
    with pytest.raises(PipelineConfigError, match="needs a Chat backend"):
        RegionRecognizer(Served("http://127.0.0.1:8000/v1", model="m"))
    engine = PageRecognizer(Served("http://127.0.0.1:8100/v1", model="recognition", preset="indra-ocr@1")).contract()
    assert engine.reads == {Part("image")} and {p.name for p in engine.adds} == {"lines", "text", "markdown"}


def test_contracts_of_the_blocks_without_a_model(tmp_path):
    from linecaster.blocks.binding import Binder, Splitter
    from linecaster.blocks.composition import Composer, Recomposer, Typographer
    from linecaster.blocks.conversion import ImageConverter
    from linecaster.blocks.lines import LineAssigner
    from linecaster.blocks.readers import ImageFolderReader, ManifestReader, PageRecordReader
    from linecaster.blocks.servers import ModelServer
    from linecaster.blocks.text import CharacterNormalizer, UnicodeNormalizer
    from linecaster.blocks.writers import ItemDocumentWriter, ItemTextWriter, PageFileWriter, PageJsonlWriter

    def names(ps):
        return sorted(map(str, ps))

    assert names(ImageFolderReader("x").contract().adds) == ["image", "metadata"]
    assert ManifestReader(str(tmp_path), existing_ocr=True).contract().adds >= {Part("transcription_file")}
    assert ManifestReader(str(tmp_path)).contract().adds == {Part("image"), Part("metadata")}
    assert PageRecordReader(str(tmp_path)).contract().adds == {Part("*"), Part("image"), Part("metadata")}
    r = PageRecordReader(str(tmp_path), fetch_images=False, provides=["ocr_new:lines", Part("text", "ocr_new")])
    assert names(r.contract().adds) == ["metadata", "ocr_new:lines", "ocr_new:text"] and not r.whole_items
    assert PageRecordReader(str(tmp_path), item_shards=True).whole_items
    a = LineAssigner().contract()
    assert names(a.adds) == ["ocr_new:line_regions"] and Part("lines", "ocr_new") in a.replaces
    assert names(UnicodeNormalizer().contract().adds) == ["ocr_new:nfc"]
    assert names(Typographer("ratios@1").contract().adds) == ["ocr_new:hierarchy"]
    assert names(Composer("docling-composition@1").contract().adds) == ["ocr_new:document"]
    assert names(Composer("docling-composition@1").contract().reads) == ["ocr_new:lines", "ocr_new:regions"]
    assert Composer("docling-composition@1", unit="item").contract().adds == {Part("document")}
    assert Composer("docling-composition@1", unit="item").contract().unit == "item"
    r = Recomposer("unicode-recomposition@1").contract()
    assert names(r.adds) == ["ocr_new:paragraphs"] and names(r.reads) == ["ocr_new:lines", "ocr_new:regions"]
    assert r.replaces == r.adds                    # paragraphs made anew where they exist
    assert Recomposer("unicode-recomposition@1", unit="item").contract().unit == "item"
    assert names(CharacterNormalizer("latin-historic@1").contract().adds) == ["ocr_new:normalized"]
    assert CharacterNormalizer("latin-historic@1", unit="item").contract().unit == "item"
    assert Binder().contract() == Contract(unit="page", unit_out="item", role="binder")
    assert Splitter().contract() == Contract(unit="item", unit_out="page", role="splitter")
    assert names(ItemTextWriter(str(tmp_path)).contract().reads) == [
        "ocr_new:lines", "ocr_new:normalized", "ocr_new:paragraphs"]
    assert ItemDocumentWriter(str(tmp_path)).contract() == Contract(unit="item", role="writer",
                                                                   reads=frozenset({Part("document")}))
    files = PageFileWriter(str(tmp_path), formats=("hocr", "md", "json", "plot", "transcription")).contract()
    assert names(files.reads) == ["image", "ocr_new:document", "ocr_new:lines", "ocr_new:text"]
    assert PageJsonlWriter(str(tmp_path)).contract() == Contract(unit="page", role="writer")
    assert ModelServer([]).contract().unit == "any" and ModelServer([]).contract().role == "server"
    assert names(ImageConverter(str(tmp_path), "working-image@1", keep_bytes=True).contract().replaces) == [
        "image", "metadata"]
    assert ImageConverter(str(tmp_path), "working-image@1", keep_bytes=True).contract().removes == frozenset()
    without = ImageConverter(str(tmp_path), "working-image@1").contract()      # the page leaves without its bytes
    assert names(without.replaces) == ["metadata"] and names(without.removes) == ["image"]
    assert without.describe()["removes"] == ["image"]
    from linecaster.blocks.writers import ImageFilesWriter

    files = ImageFilesWriter(str(tmp_path)).contract()           # image.uri and extra name the copy
    assert names(files.reads) == ["image"] and names(files.replaces) == ["metadata"]
    assert contract_of(object()) == Contract(unit="page", role="transform")


# ------------------------------------------------------------------------------------------------ block shapes

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
        if family(cls) in ("readers", "writers"):
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
    assert task_uses(importlib.import_module("linecaster.blocks.writers.rejects").RejectWriter)  # a writer may


def test_the_two_shapes():
    from linecaster.blocks.base.page import PageBlock
    from linecaster.blocks.lines import LineAssigner, LineDetector

    assert PageBlock.shape == "unit" and LineAssigner().shape == "unit"
    assert LineDetector(InProcess("x:Y")).shape == "unit"
    assert LineDetector(Served("http://127.0.0.1:8100/v1", model="lines")).shape == "stream"


# ------------------------------------------------------------------------------------------------ to_dict

def _one_of_each(tmp_path) -> list:
    """One block of every class in ``linecaster.blocks``, with what its constructor needs."""
    from linecaster.adapters import chat_model
    from linecaster.backends import Chat
    from linecaster.runtime.secrets import EnvVar

    served = Served("https://api.example.org/v1", model="m", api_key=EnvVar("LC_TEST_KEY"), headers={"X-Team": "ocr"})
    needs = {
        "ModelBlock": {"backend": InProcess("pkg:Engine", size=3)},
        "LayoutDetector": {"backend": InProcess("pkg:Layout")}, "LineDetector": {"backend": InProcess("pkg:Lines")},
        "LineRecognizer": {"backend": served}, "TableRecognizer": {"backend": InProcess("pkg:Tables")},
        "FormulaRecognizer": {"backend": InProcess("pkg:Formulas")},
        "PageRecognizer": {"backend": Chat(chat_model("lightonocr-2-1b"), api_key=EnvVar("LC_TEST_KEY"))},
        "RegionRecognizer": {"backend": "lightonocr-2-1b-regions"},
        "ChatModelServer": {"spec": "lightonocr-2-1b"}, "ServiceServer": {"preset": "falcon-ocr@1"},
        "ModelServer": {"models": [{"name": "lines", "spec": "pkg:Lines", "kwargs": {"x": 1}}]},
        "RecipeStamper": {"recipe": "squiddle@1", "recipe_sha256": "sha256:" + "0" * 64},
        "ManifestReader": {"data_folder": str(tmp_path)},
        "ResourceReader": {"data_folder": str(tmp_path / "in"), "item_key": "lccn",
                           "templates": {"marcxml": "https://lccn.loc.gov/{item}/marcxml"}},
        "RuleBlock": {"preset": InProcess("pkg:Rules", x=1)}, "Typographer": {"preset": "ratios@1"},
        "Recomposer": {"preset": "unicode-recomposition@1", "unit": "item"},
        "Composer": {"preset": "docling-composition@1", "options": {"sections": True}},
        "CharacterNormalizer": {"preset": "latin-historic@1"},
        "ImageConverter": {"output_folder": str(tmp_path / "webp"), "preset": "working-image@1"},
    }
    out = []
    for cls in block_classes():
        if cls.__name__ in needs:
            out.append(cls(**needs[cls.__name__]))
        elif "data_folder" in inspect.signature(cls.__init__).parameters:
            out.append(cls(str(tmp_path / "in")))
        elif "output_folder" in inspect.signature(cls.__init__).parameters:
            out.append(cls(str(tmp_path / cls.__name__)))
        else:
            out.append(cls())
    return out


def test_every_block_family_goes_into_the_run_record_as_built(tmp_path, monkeypatch):
    import json

    from linecaster.blocks.composites import ModularTranscriber
    from linecaster.catalog import yamlio
    from linecaster.runtime import provenance
    from linecaster.runtime.builder import build
    from linecaster.runtime.record import RunRecord

    monkeypatch.setenv("LC_TEST_KEY", "s3cret-value")
    blocks = _one_of_each(tmp_path)
    assert {family(type(b)) for b in blocks} >= {"base", "binding", "composition", "conversion", "layout", "lines",
                                                 "readers", "recognition", "servers", "text", "validation", "writers"}
    composite = ModularTranscriber(InProcess("pkg:Lines"), InProcess("pkg:Text"), "single-region@1")
    plan = build([*blocks, composite])            # contracts need not fit: every block is described
    rec = provenance.run_record({"on": "local", "tasks": 1}, plan)
    back = yamlio.load(yamlio.dump(rec))
    assert back == rec == json.loads(json.dumps(rec))       # JSON-compatible, and the YAML round trip is exact
    RunRecord.model_validate(back)
    entries = rec["pipeline"][0]["blocks"]
    assert "s3cret-value" not in yamlio.dump(rec)
    for block, entry in zip([*blocks, *[b for b, _ in composite.expanded()]], entries):
        d = block.to_dict()
        assert entry["block"] == d["block"] == type(block).__name__ and entry["class"] == d["class"]
        assert entry["params"] == json.loads(json.dumps(d["params"]))
        own = [p for p, x in list(inspect.signature(type(block).__init__).parameters.items())[1:]
               if x.kind not in (x.VAR_KEYWORD, x.VAR_POSITIONAL)]
        assert set(own) <= set(d["params"]), type(block).__name__        # every constructor parameter
        assert entry["contract"]["role"] == block.contract().role
    by_name = {e["block"]: e for e in entries[:len(blocks)]}
    assert by_name["LineRecognizer"]["params"]["backend"] == {
        "backend": "served", "endpoint": "https://api.example.org/v1", "model": "m", "max_window": 32,
        "initial_window": 4, "read_timeout": 600.0, "api_key": {"env": "LC_TEST_KEY"}, "headers": {"X-Team": "ocr"}}
    assert by_name["ModelBlock"]["params"]["backend"] == {"backend": "in-process", "engine": "pkg:Engine",
                                                          "options": {"size": 3}}
    chat = by_name["PageRecognizer"]["params"]["backend"]
    assert chat["backend"] == "chat" and chat["preset"].startswith("lightonocr-2-1b@")
    assert chat["endpoint"] == "http://127.0.0.1:8000/v1" and chat["api_key"] == {"env": "LC_TEST_KEY"}
    assert by_name["RegionRecognizer"]["params"]["backend"]["preset"].startswith("lightonocr-2-1b-regions@")
    from linecaster.catalog.registry import catalog

    composer = by_name["Composer"]["params"]
    assert composer["preset"] == {"backend": "in-process", "engine": "linecaster.engines:DoclingCompositionEngine",
                                  "options": {"sections": True}, "preset": "docling-composition@1",
                                  "preset_sha256": catalog().resolve("docling-composition@1").sha256,
                                  "overrides": {"sections": True}}
    assert composer["unit"] == "page" and by_name["Recomposer"]["params"]["unit"] == "item"
    assert by_name["RuleBlock"]["params"]["preset"] == {"backend": "in-process", "engine": "pkg:Rules",
                                                        "options": {"x": 1}}
    assert by_name["ImageFolderReader"]["params"]["data_folder"] == str(tmp_path / "in")
    # composites as groups: their blocks carry the group in the record, and the composite's own dict lists them
    assert [e.get("composite") for e in entries[-4:]] == ["modular transcriber"] * 4
    group = composite.to_dict()
    assert group["composite"] == "modular transcriber" and [b["block"] for b in group["blocks"]] == [
        "LayoutDetector", "LineDetector", "LineAssigner", "LineRecognizer"]
    assert group["params"]["lines"] == {"backend": "in-process", "engine": "pkg:Lines", "options": {}}
