"""``linecaster.testing``: the sample pages, the fake engines and the fake chat server, the conformance checks
(``check_engine``, ``check_block``) on engines and blocks built to break them, and every built-in engine and every
public block through them."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from linecaster.backends import Chat, InProcess
from linecaster.blocks.base.page import page_of
from linecaster.catalog.registry import BUILTIN_ENGINES, SERVED_ONLY, catalog, engine_class, engine_ids, engine_spec
from linecaster.data import Region, StepInfo
from linecaster.engines.normalization import TextNormalization
from linecaster.testing import (FAKE_ENGINES, FakeLineEngine, FakeRecognitionEngine, check_block, check_engine,
                                fake_chat_server, register_fakes, sample_boxes, sample_document, sample_documents,
                                sample_layout, sample_page, sample_png)

FAKES = "linecaster.testing"


def test_importing_the_helpers_loads_no_executor_torch_engine_or_pytest():
    check = ("import sys, linecaster.testing; print([m for m in sys.modules if m.split('.')[0] in "
             "('datatrove', 'saturate', 'torch', 'pytest') or m.startswith('linecaster_')])")
    out = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_the_sample_page():
    image = sample_page(400, 300, ["one", "two"])
    assert image.size == (400, 300) and image.mode == "RGB"
    boxes = sample_boxes(400, 300, ["one", "two"])
    assert boxes == [[40.0, 60.0, 320.0, 60.0], [40.0, 180.0, 320.0, 60.0]]
    x, y, w, h = map(int, boxes[0])
    assert min(image.crop((x, y, x + w, y + h)).convert("L").get_flattened_data()) < 100      # ink in the box
    assert min(image.crop((0, 0, 400, y)).convert("L").get_flattened_data()) == 255            # none above it
    t = sample_layout(400, 300, ["one", "two"], text=True)
    assert [ln.text for ln in t.lines] == ["one", "two"] and [ln.bbox for ln in t.lines] == boxes
    assert t.regions[0].id == "text_0" and all(ln.region_id == "text_0" for ln in t.lines)
    doc = sample_document("b_0001", transcription=t, item_id="b", sequence=1)
    page = page_of(doc)
    assert (page.page_id, page.item_id, page.image.width, page.image.format) == ("b_0001", "b", 800, "png")
    assert doc.text == "one\ntwo" and page.transcriptions["ocr_new"].lines[1].text == "two"
    assert [page_of(d).sequence for d in sample_documents(3)] == [1, 2, 3]


def test_the_fakes_are_engines_and_registered_only_on_request():
    assert not set(FAKE_ENGINES) & set(engine_ids()) or "fake.lines.v1" in engine_ids()
    assert register_fakes() == FAKE_ENGINES
    assert engine_class("fake.lines.v1") is FakeLineEngine and set(FAKE_ENGINES) <= set(engine_ids())
    for target in FAKE_ENGINES.values():
        check_engine(engine_class(next(k for k, v in FAKE_ENGINES.items() if v == target)))
    t = check_engine(FakeLineEngine, options={"boxes": sample_boxes()})
    assert [ln.bbox for ln in t.lines] == sample_boxes()
    out = check_engine(FakeRecognitionEngine, options={"template": "{line}@{width}x{height}"})
    assert out.lines[0].text == "text_0_l0@800x400"


def test_the_fake_chat_server_answers_from_its_function():
    import urllib.request

    with fake_chat_server(lambda body: body["model"].upper()) as server:
        assert server.url.startswith("http://127.0.0.1:")
        req = urllib.request.Request(f"{server.url}/chat/completions", data=json.dumps({"model": "m"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            answer = json.loads(r.read())
    assert answer["choices"][0]["message"]["content"] == "M" and server.requests == [{"model": "m"}]


# ------------------------------------------------------------------------- check_engine finds what is wrong

class _Base:
    engine_id, step = "test.recognition.v1", "recognition"
    capabilities = {"unit": "line", "produces": ["text"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")
        prefix: str = Field("x", description="what every text starts with")

    def __init__(self, **options):
        self.options = self.Options(**options)

    def load(self):
        pass

    def __call__(self, image, t, **params):
        for ln in t.lines:
            ln.text = self.options.prefix + ln.id
        t.steps.append(StepInfo(step=self.step, name="test"))
        return t


def test_check_engine_passes_a_good_engine():
    out = check_engine(_Base, options={"prefix": "y"})
    assert out.lines[0].text == "ytext_0_l0"


@pytest.mark.parametrize("change, problem", [
    ({"engine_id": "Test-Recognition"}, "is not a code id"),
    ({"engine_id": "test.layout.v1"}, "does not name its step"),
    ({"step": "page"}, "is not a catalog step"),
    ({"capabilities": {"unit": "line", "produces": ["texts"]}}, "capabilities"),
])
def test_check_engine_finds_a_wrong_declaration(change, problem):
    with pytest.raises(AssertionError, match=problem):
        check_engine(type("Wrong", (_Base,), change))


def test_check_engine_finds_wrong_behavior():
    class Undocumented(_Base):
        class Options(BaseModel):
            prefix: str = "x"

    class Baselines(_Base):             # adds what it does not declare
        def __call__(self, image, t, **params):
            for ln in t.lines:
                ln.baseline = [[0.0, 0.0], [1.0, 0.0]]
            return super().__call__(image, t)

    class Inks(_Base):                  # writes into the image it was given
        def __call__(self, image, t, **params):
            image[0, 0] = 0
            return super().__call__(image, t)

    class Moody(_Base):                 # not deterministic
        calls = 0

        def __call__(self, image, t, **params):
            Moody.calls += 1
            return super().__call__(image, t) if Moody.calls == 1 else t

    class Unknown(_Base):               # a measurement outside the vocabulary, a step record of another engine
        def __call__(self, image, t, **params):
            t.steps.append(StepInfo(step="recognition", name="x", engine="other.recognition.v1",
                                    measurements={"lines_read": 3}))
            return t

    for cls, problem in ((Undocumented, "without a description: prefix"),
                         (Baselines, r"changed lines.baseline, which needs one of \['baselines', 'lines'\]"),
                         (Inks, "changed the image array"), (Moody, "not deterministic"),
                         (Unknown, "measurements outside the vocabulary")):
        with pytest.raises(AssertionError, match=problem):
            check_engine(cls)
    with pytest.raises(AssertionError, match="StepInfo engine 'other.recognition.v1'"):
        check_engine(Unknown)


# ------------------------------------------------------------------------------ the built-in engines

class IdentityNormalizationEngine(TextNormalization):
    """A default normalization strategy for every script: changes nothing."""

    engine_id = "normalization.identity.v1"
    step = "normalization"
    capabilities = {"unit": "page", "produces": ["normalized"]}
    scripts = ("*",)

    def normalize(self, text):
        return text


#: a by-script engine needs strategies, which no preset gives yet
BY_SCRIPT = {
    "normalization.by-script.v1": {"Latn": {"engine": "linecaster.engines:LatinHistoricNormalizationEngine"},
                                   "*": {"engine": f"{__name__}:IdentityNormalizationEngine"}},
    "recomposition.by-script.v1": {"*": {"engine": "linecaster.engines:UnicodeRecompositionEngine"}},
}


def _builtin_options(engine: str) -> dict:
    """The options of the first preset of a built-in engine, or a by-script engine's strategies."""
    if engine in BY_SCRIPT:
        return {"strategies": BY_SCRIPT[engine]}
    for pid, (_, p) in sorted(catalog().presets.items()):
        if p.engine == engine:
            return engine_spec(pid)[1]
    return {}


@pytest.mark.parametrize("engine", sorted(set(BUILTIN_ENGINES) - SERVED_ONLY))
def test_every_builtin_engine_conforms(engine):
    check_engine(engine_class(engine), options=_builtin_options(engine))


# ------------------------------------------------------------------------------ check_block finds what is wrong

def test_check_block_finds_an_undeclared_change():
    from linecaster.blocks.base.page import PageBlock

    class Stamps(PageBlock):
        """Writes into the page record's metadata without declaring it."""

        parts_read = ("lines",)

        def process_page(self, doc, page):
            page.metadata["stamped"] = True
            return page

    with pytest.raises(AssertionError, match=r"changed metadata, which needs one of \['metadata'\]"):
        check_block(Stamps())

    class Declares(Stamps):
        parts_replaced = ("metadata",)

    assert len(check_block(Declares())) == 2


def test_check_block_finds_an_undeclared_removal(tmp_path):
    """``ImageConverter`` without ``keep_bytes`` passes pages on without their image: its contract must say so."""
    from linecaster.blocks.base.contract import Contract, parts
    from linecaster.blocks.conversion import ImageConverter

    class Hides(ImageConverter):
        def contract(self):
            return Contract(unit="page", role=self.role, reads=parts(("metadata",), None),
                            replaces=parts(("metadata",), None))

    with pytest.raises(AssertionError, match=r"removed \['image'\]; the contract removes nothing"):
        check_block(Hides(str(tmp_path / "webp"), "working-image@1"))
    out = check_block(ImageConverter(str(tmp_path / "webp"), "working-image@1"))
    assert [d.media for d in out] == [[], []]


# ------------------------------------------------------------------------------ every public block

def _on_disk(tmp_path: Path) -> list:
    """Sample pages whose image URIs name files that exist."""
    docs = sample_documents(2)
    (tmp_path / "scans").mkdir(exist_ok=True)
    for d in docs:
        page = page_of(d)
        path = tmp_path / "scans" / f"{d.id}.png"
        path.write_bytes(d.media[0].media_bytes)
        page.image.uri = str(path)
        from linecaster.blocks.base.page import set_page

        set_page(d, page)
    return docs


def _inputs(tmp_path: Path) -> dict[str, str]:
    """Folders for the readers: images, a Parquet table, a PDF, page records."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.blocks.writers import PageJsonlWriter

    images = tmp_path / "images" / "item1"
    images.mkdir(parents=True)
    for k in (1, 2):
        (images / f"item1_{k:04d}.png").write_bytes(sample_png(200, 100))
    (tmp_path / "parquet").mkdir()
    pq.write_table(pa.table({"id": ["p1"], "image": [{"bytes": sample_png(200, 100), "path": None}]}),
                   tmp_path / "parquet" / "part-0.parquet")
    (tmp_path / "pdf").mkdir()
    sample_page(200, 100).save(tmp_path / "pdf" / "a.pdf", format="PDF", resolution=72.0)
    list(PageJsonlWriter(str(tmp_path / "pages")).run(iter(_on_disk(tmp_path))))
    return {k: str(tmp_path / k) for k in ("images", "parquet", "pdf", "pages")}


def _alto_docs() -> list:
    from datatrove.data import Media, MediaType

    from linecaster.formats import to_alto

    docs = sample_documents(1)
    xml = to_alto(sample_layout(text=True), image_width=800, image_height=400)
    docs[0].media.append(Media(id=docs[0].id, type=MediaType.DOCUMENT, url="a.xml",
                               media_bytes=xml.encode() if isinstance(xml, str) else xml,
                               metadata={"format": "alto"}))
    return docs


def public_blocks(tmp_path: Path, chat_url: str) -> dict[str, tuple[object, dict]]:
    """One block of every public block class (and the composite), runnable here: fake engines, a fake chat server,
    sample inputs; with the ``check_block`` arguments each needs, by a label (the class, and what is special)."""
    from linecaster.blocks import binding, composites, composition, conversion, layout, lines, readers, recognition
    from linecaster.blocks import servers, text, validation, writers
    from linecaster.blocks.composition import Composer

    i = _inputs(tmp_path)
    fake = {step: InProcess(f"{FAKES}:{name}") for step, name in (
        ("layout", "FakeLayoutEngine"), ("lines", "FakeLineEngine"), ("recognition", "FakeRecognitionEngine"),
        ("tables", "FakeTableEngine"), ("formulas", "FakeFormulaEngine"))}
    tables = sample_documents(1)
    t = page_of(tables[0]).transcriptions["ocr_new"]
    t.regions += [Region(id="table_1", label="table", polygon=[[0, 0], [10, 0], [10, 10], [0, 10]], bbox=[0, 0, 10, 10]),
                  Region(id="formula_2", label="formula", polygon=[[0, 0], [10, 0], [10, 10], [0, 10]],
                         bbox=[0, 0, 10, 10])]
    from linecaster.blocks.base.page import set_page

    page = page_of(tables[0])
    page.transcriptions["ocr_new"] = t
    set_page(tables[0], page)
    item_docs = list(Composer("docling-composition@1", unit="item").run(
        iter(list(binding.Binder().run(iter(sample_documents(2)))))))
    out = tmp_path / "out"
    entries = [
        (readers.ImageFolderReader(i["images"], item_from_parent=True), {}),
        (readers.ImageParquetReader(i["parquet"]), {}),
        (readers.PdfReader(i["pdf"], dpi=72), {}),
        (readers.PageRecordReader(i["pages"]), {}),
        (readers.ManifestReader(str(tmp_path)), {"run": False}),       # its manifests come over http(s)
        (readers.ResourceReader(str(tmp_path), item_key="lccn",            # its resources come over http(s)
                                templates={"marcxml": "https://lccn.loc.gov/{item}/marcxml"}), {"run": False}),
        (layout.LayoutDetector(fake["layout"]), {}),
        (lines.LineDetector(fake["lines"]), {}),
        (lines.LineAssigner(), {}),
        (recognition.LineRecognizer(fake["recognition"]), {}),
        (recognition.TableRecognizer(fake["tables"]), {"docs": tables}),
        (recognition.FormulaRecognizer(fake["formulas"]), {"docs": tables}),
        (recognition.PageRecognizer(Chat("lightonocr-2-1b", chat_url, max_window=2)), {}),
        (recognition.PageRecognizer(InProcess(f"{FAKES}:FakePageEngine")), {}),
        (recognition.RegionRecognizer(Chat("lightonocr-2-1b-regions", chat_url, max_window=2)), {}),
        (conversion.ImageFetcher(), {"docs": _on_disk(tmp_path)}),
        (conversion.ImageConverter(str(out / "webp"), "working-image@1"), {}),
        (conversion.ImageConverter(str(out / "webp2"), "working-image@1", keep_bytes=True), {}),
        (conversion.TranscriptionConverter(), {"docs": _alto_docs()}),
        (text.UnicodeNormalizer(), {}),
        (text.CharacterNormalizer("latin-historic@1"), {}),
        (text.CharacterNormalizer("latin-historic@1", unit="item"), {}),
        (composition.Typographer("ratios@1"), {}),
        (composition.Recomposer("unicode-recomposition@1"), {}),
        (composition.Recomposer("unicode-recomposition@1", unit="item"), {}),
        (composition.Composer("docling-composition@1"), {}),
        (composition.Composer("docling-composition@1", unit="item"), {}),
        (binding.Binder(), {}),
        (binding.Splitter(), {}),
        (validation.PageValidator(required=("ocr_new",)), {}),
        (validation.RecipeStamper("squiddle@1", catalog().resolve_recipe("squiddle@1").sha256), {}),
        (servers.ModelServer([{"name": "lines", "spec": f"{FAKES}:FakeLineEngine", "kwargs": {}}]), {"run": False}),
        (servers.ChatModelServer("lightonocr-2-1b"), {"run": False}),
        (servers.ServiceServer("falcon-ocr@1"), {"run": False}),
        (writers.PageJsonlWriter(str(out / "jsonl")), {}),
        (writers.PageParquetWriter(str(out / "parquet")), {}),
        (writers.PageFileWriter(str(out / "files"), formats=("hocr", "alto", "page", "txt", "md")), {}),
        (writers.ImageFilesWriter(str(out / "images")), {}),
        (writers.RejectWriter(str(out / "rejects")), {}),
        (writers.ResourceFilesWriter(str(out / "resources")), {}),
        (writers.ResourceRecordWriter(str(out / "resources" / "records")), {}),
        (writers.ItemTextWriter(str(out / "texts")), {}),
        (writers.ItemDocumentWriter(str(out / "documents")), {"docs": item_docs}),
        (composites.ModularTranscriber(fake["lines"], fake["recognition"], "single-region@1"), {}),
    ]
    labels: dict[str, tuple[object, dict]] = {}
    for block, kwargs in entries:
        name = type(block).__name__
        while name in labels:
            name += "+"
        labels[name] = (block, kwargs)
    return labels


#: the labels of ``public_blocks`` (a class built twice: ``+``)
BLOCKS = ("ImageFolderReader", "ImageParquetReader", "PdfReader", "PageRecordReader", "ManifestReader", "ResourceReader",
          "LayoutDetector", "LineDetector", "LineAssigner", "LineRecognizer", "TableRecognizer", "FormulaRecognizer",
          "PageRecognizer", "PageRecognizer+", "RegionRecognizer", "ImageFetcher", "ImageConverter", "ImageConverter+",
          "TranscriptionConverter", "UnicodeNormalizer", "CharacterNormalizer", "CharacterNormalizer+",
          "Typographer", "Recomposer", "Recomposer+", "Composer", "Composer+", "Binder", "Splitter", "PageValidator",
          "RecipeStamper", "ModelServer", "ChatModelServer", "ServiceServer", "PageJsonlWriter", "PageParquetWriter",
          "PageFileWriter", "ImageFilesWriter", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter",
          "ItemTextWriter", "ItemDocumentWriter",
          "ModularTranscriber")


def test_every_public_block_class_is_covered(tmp_path):
    from linecaster.blocks.base.block import Block
    from linecaster.docs.blocks import FAMILIES

    public = set()
    for family in FAMILIES:
        m = __import__(f"linecaster.blocks.{family}", fromlist=["__all__"])
        public |= {name for name in m.__all__ if inspect.isclass(cls := getattr(m, name)) and issubclass(cls, Block)
                   and not cls.__module__.startswith("linecaster.blocks.base")}
    built = public_blocks(tmp_path, "http://127.0.0.1:1/v1")
    assert tuple(built) == BLOCKS
    assert public - {type(b).__name__ for b, _ in built.values()} == set()


@pytest.fixture(scope="module")
def chat_url():
    with fake_chat_server(lambda body: "a\nb") as server:
        yield server.url


#: blocks whose contract is known not to describe what they do
KNOWN = {"PageRecognizer": "it replaces the whole transcription with a text-only one (lines without geometry; "
                           "regions gone), which its contract (adds text and the preset's parts) does not declare",
         "PageRecognizer+": "a page engine's transcription replaces the whole transcription too (as PageRecognizer)"}


@pytest.mark.parametrize("label", [pytest.param(b, marks=pytest.mark.xfail(strict=True, reason=KNOWN[b]))
                                   if b in KNOWN else b for b in BLOCKS])
def test_every_public_block_conforms(label, tmp_path, chat_url):
    block, kwargs = public_blocks(tmp_path, chat_url)[label]
    check_block(block, **kwargs)

