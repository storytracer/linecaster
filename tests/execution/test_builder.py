"""The builder (``linecaster.execution.builder``): checks with a broken pipeline per problem kind, branches,
composites, stage cutting, partial runs, taps and ``run_pages``, on CPU with fake engines."""
import gzip
import io
import json
from pathlib import Path

import pytest
from datatrove.pipeline.base import PipelineStep
from PIL import Image

from linecaster.backends import InProcess, Served
from linecaster.core.composite import Composite
from linecaster.core.contract import Contract, Part
from linecaster.core.page import PageComponent, new_page_document, page_of
from linecaster.components.items import ItemAssembler, ItemSplitter
from linecaster.components.composites import ModularTranscriber
from linecaster.components.document import DocumentComposer
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.layout import LayoutDetector
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.readers import ImageFolderReader, PageRecordReader
from linecaster.components.recognition import LineRecognizer
from linecaster.components.tables import TableRecognizer
from linecaster.components.servers import EngineServer
from linecaster.components.writers import ItemDocumentWriter, ItemTextWriter, PageFileWriter, PageJsonlWriter
from linecaster.catalog import yamlio
from linecaster.data import Line
from linecaster.errors import PipelineConfigError
from linecaster.execution import run
from linecaster.execution.builder import OTHERWISE, MetadataEquals, branch, build, run_pages, run_plan
from linecaster.core.observers import Observer


# ------------------------------------------------------------------------------------------------ fake engines

#: the fake engines (linecaster.testing): two lines per region (or page), and every line's text from the page size
#: and the line's position
LINES = "linecaster.testing:FakeLineEngine"
TEXT = "linecaster.testing:FakeRecognitionEngine"
TEMPLATE = "page {width}x{height} line {index}"


#: the variant the fake engines' pages make (no recomposition here)


def item_texts(folder: str) -> list:
    """An item stage for pages of lines only (no regions, so no document to write texts from): the item records
    split into pages again and written."""
    return [ItemSplitter(), PageJsonlWriter(f"{folder}/split")]


def _lines():
    return LineDetector(InProcess(LINES))


def _text():
    return LineRecognizer(InProcess(TEXT, template=TEMPLATE))


def _png(path: Path, w: int, h: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    path.write_bytes(buf.getvalue())


@pytest.fixture
def items(tmp_path: Path) -> str:
    """Two items of three and two pages, each page a different size."""
    for k, (item, page) in enumerate([("A", "a1"), ("A", "a2"), ("A", "a3"), ("B", "b1"), ("B", "b2")]):
        _png(tmp_path / "images" / item / f"{page}.png", 40 + k)
    return str(tmp_path / "images")


def _doc(page_id: str = "p1", w: int = 40, metadata: dict | None = None):
    buf = io.BytesIO()
    Image.new("RGB", (w, 30), "white").save(buf, format="PNG")
    return new_page_document(page_id, buf.getvalue(), uri=f"{page_id}.png", metadata=metadata)


def _problems(components, **kw) -> list[str]:
    return build(components, **kw).problems


def _records(folder: Path) -> dict[str, dict]:
    """The page records by id, without what varies from run to run (an annotator's and the page's ``seconds`` and
    ``datetime``, the run that added the annotator)."""
    out = {}
    for f in sorted(folder.rglob("*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            row = json.loads(line)
            row["page"].pop("measurements", None)
            for t in row["page"]["transcriptions"].values():
                for a in t.get("annotators") or []:
                    a.pop("run", None)
                    a.get("measurements", {}).pop("seconds", None)
                    a.get("measurements", {}).pop("datetime", None)
            out[row["id"]] = row
    return out


# ------------------------------------------------------------------------------------------------ checks

def test_a_valid_pipeline_has_no_problems():
    p = build([ImageFolderReader("x"), ModularTranscriber(_lines(), _text(), "single-region"),
               HierarchyDetector("ratios"), DocumentComposer("linked-document"),
               PageFileWriter("f", formats=("hocr", "md", "json")), PageJsonlWriter("o/pages")])
    assert p.problems == []
    p.check()
    assert [type(b).__name__ for b in p.stages[0].components] == [
        "ImageFolderReader", "LayoutDetector", "LineDetector", "LineAssigner", "LineRecognizer",
        "HierarchyDetector", "DocumentComposer", "PageFileWriter", "PageJsonlWriter"]


def test_a_recognizer_without_lines():
    problems = _problems([ImageFolderReader("x"), _text(), PageJsonlWriter("o")])
    assert problems == ["LineRecognizer (recognition (in-process)) reads ocr_new:lines, which no component before it in "
                        "the pipeline adds"]
    with pytest.raises(PipelineConfigError) as e:
        build([ImageFolderReader("x"), _text(), PageJsonlWriter("o")]).check()
    assert "reads ocr_new:lines" in str(e.value) and e.value.problems == problems


def test_a_part_added_twice():
    problems = _problems([ImageFolderReader("x"), LayoutDetector("single-region"), _lines(), _lines(), _text()])
    assert problems == ["LineDetector (lines (in-process)) adds ocr_new:lines, which LineDetector adds already (a "
                        "component that rewrites a part declares it in replaces)"]
    # a component that declares the part in replaces may rewrite it
    assert _problems([ImageFolderReader("x"), LayoutDetector("single-region"), _lines(), LineAssigner(), _text()]) == []


def test_parts_belong_to_their_transcription():
    problems = _problems([ImageFolderReader("x"), _lines(), LineRecognizer(InProcess(TEXT, template=TEMPLATE),
                                                                          transcription="other")])
    assert problems == ["LineRecognizer (recognition (in-process)) reads other:lines, which no component before it in "
                        "the pipeline adds"]


def test_a_removed_part_is_gone_for_later_components(tmp_path: Path):
    """``ImageConverter`` without ``keep_bytes`` passes the page on without image bytes: a later component that reads the
    image is a problem, even after a reader that provides anything; ``keep_bytes`` or an ``ImageFetcher`` fixes it."""
    from linecaster.components.images import ImageConverter, ImageFetcher

    convert = ImageConverter(str(tmp_path / "webp"), "working-image")
    problems = _problems([ImageFolderReader("x"), convert, _lines(), PageJsonlWriter("o")])
    assert problems == ["LineDetector (lines (in-process)) reads image, which ImageConverter (🖼️ image converter) "
                        "removes before it"]
    assert _problems([PageRecordReader("p"), convert, _lines()]) == problems[:1]
    assert _problems([ImageFolderReader("x"), convert, ImageFetcher(), _lines(), PageJsonlWriter("o")]) == []
    kept = ImageConverter(str(tmp_path / "webp"), "working-image", keep_bytes=True)
    assert _problems([ImageFolderReader("x"), kept, _lines(), PageJsonlWriter("o")]) == []


def test_a_page_component_after_an_item_stream():
    problems = _problems([ImageFolderReader("x"), _lines(), _text(), ItemAssembler(), DocumentComposer("linked-document")])
    assert "DocumentComposer (document) works on pages, but the stream carries items here" in problems
    # and an item writer before any binder
    assert _problems([ImageFolderReader("x"), _lines(), _text(), ItemTextWriter("t")]) == [
        "ItemTextWriter (📚 item texts) works on items, but the stream carries pages here",
        "ItemTextWriter (📚 item texts) reads document, which no component before it in the pipeline adds"]


def test_server_components_go_last():
    problems = _problems([ImageFolderReader("x"), EngineServer([{"name": "lines"}]), _lines(), PageJsonlWriter("o")])
    assert problems == [
        "LineDetector (lines (in-process)) comes after the server component EngineServer (🖥️ engine server): server components "
        "go last",
        "PageJsonlWriter (🐿 page records (jsonl)) comes after the server component EngineServer (🖥️ engine server): server "
        "components go last"]


def test_a_served_component_finds_its_model_at_its_server():
    served = LineDetector(Served("http://127.0.0.1:8100/v1", model="lines"))
    ok = [ImageFolderReader("x"), served, PageJsonlWriter("o"), EngineServer([{"name": "lines"}], port=8100)]
    assert _problems(ok) == []
    wrong = [ImageFolderReader("x"), served, PageJsonlWriter("o"), EngineServer([{"name": "layout"}], port=8100)]
    assert _problems(wrong) == ["LineDetector (lines (served http://127.0.0.1:8100/v1 (lines))) asks the model server "
                                "on port 8100 in the pipeline for 'lines', which it does not host (layout)"]
    # an explicit endpoint (no server component of this stage on its port) is the caller's
    elsewhere = [ImageFolderReader("x"), LineDetector(Served("http://gpu-box:8100/v1", model="lines")),
                 PageJsonlWriter("o")]
    assert _problems(elsewhere) == []


def test_a_pipeline_starts_with_a_reader():
    assert _problems([_lines(), PageJsonlWriter("o")]) == [
        "the pipeline starts with LineDetector (lines (in-process)), not a reader",
        "LineDetector (lines (in-process)) reads image, which no component before it in the pipeline adds"]


def test_every_problem_is_listed():
    problems = _problems([ImageFolderReader("x"), _text(), EngineServer([]), DocumentComposer("linked-document"),
                          ItemTextWriter("t")],
                         until="Nothing")
    assert len(problems) == 8
    assert problems[0].startswith("--until Nothing: no component of that name")
    assert sum("server components go last" in x for x in problems) == 2 and sum(" reads " in x for x in problems) == 4


def test_page_records_whose_parts_are_unknown_are_not_checked():
    assert _problems([PageRecordReader("p"), _text(), PageJsonlWriter("o")]) == []
    assert _problems([PageRecordReader("p", provides=["ocr_new:regions"]), _text()]) == [
        "LineRecognizer (recognition (in-process)) reads ocr_new:lines, which no component before it in the pipeline adds"]
    assert _problems([PageRecordReader("p", provides=["ocr_new:lines"]), _text()]) == []
    assert _problems([PageRecordReader("p", fetch_images=False, provides=["ocr_new:lines"]), _text()]) == [
        "LineRecognizer (recognition (in-process)) reads image, which no component before it in the pipeline adds"]


# ------------------------------------------------------------------------------------------------ branches

class Mark(PageComponent):
    """Sets ``metadata[key] = value`` (a per-unit transform)."""

    parts_added = ("hierarchy",)

    def __init__(self, value: str, key: str = "mark", name: str | None = None):
        self.name = name or f"mark {value}"
        super().__init__()
        self.key, self.value = key, value

    def process_page(self, doc, page):
        page.metadata[self.key] = self.value
        return page


class Shout(PipelineStep):
    """A plain datatrove step (one stream): upper-cases ``doc.text``; no contract of its own."""

    name = "shout"

    def run(self, data, rank: int = 0, world_size: int = 1):
        for doc in data:
            doc.text = doc.text.upper() + "!"
            yield doc


def test_a_group_sends_each_page_through_one_alternative():
    docs = [_doc(f"p{i}", metadata={"kind": k}) for i, k in enumerate(["print", "hand", "other", "print"])]
    out = run_pages([branch(Mark("P"), when=MetadataEquals("kind", "print"), group="script"),
                     branch(Mark("H"), when=MetadataEquals("kind", "hand"), group="script"),
                     branch(Mark("O"), when=OTHERWISE, group="script")], docs)
    assert [page_of(d).metadata["mark"] for d in out] == ["P", "H", "O", "P"]
    assert all("linecaster_branch" not in d.metadata for d in out)


def test_a_page_a_condition_rejects_passes_unchanged():
    docs = [_doc("a", metadata={"kind": "print"}), _doc("b", metadata={"kind": "hand"})]
    out = run_pages([branch(Mark("P"), when=MetadataEquals("kind", "print"))], docs)
    assert [page_of(d).metadata.get("mark") for d in out] == ["P", None]
    # a stream step: only the pages it takes, the others passed on, none lost
    docs = [_doc(x, metadata={"kind": k}) for x, k in [("a", "hand"), ("b", "print"), ("c", "hand"), ("d", "hand")]]
    for d in docs:
        d.text = d.id
    out = run_pages([branch(Shout(), when=MetadataEquals("kind", "print"))], docs)
    assert sorted(d.text for d in out) == ["B!", "a", "c", "d"]


def test_group_checks():
    reader = ImageFolderReader("x")
    differing = [reader, branch(Mark("P"), when=MetadataEquals("kind", "print"), group="g"),
                 branch(LayoutDetector("single-region"), when=OTHERWISE, group="g")]
    assert _problems(differing) == [
        "the alternatives of group 'g' add different parts (Mark (mark P): ocr_new:hierarchy; LayoutDetector "
        "(layout (in-process)): ocr_new:reading_order, ocr_new:regions)"]
    misplaced = [reader, branch(Mark("O"), when=OTHERWISE, group="g"),
                 branch(Mark("P"), when=MetadataEquals("kind", "print"), group="g")]
    assert _problems(misplaced) == ["Mark (mark O): OTHERWISE must be the last alternative of group 'g'"]
    no_condition = Mark("N")
    no_condition.group = "g"
    assert _problems([reader, no_condition, branch(Mark("P"), when=OTHERWISE, group="g")]) == [
        "Mark (mark N) is an alternative of group 'g' without a condition (when=)"]
    apart = [reader, branch(Mark("P"), when=OTHERWISE, group="g"), DocumentComposer("linked-document"),
             branch(Mark("Q"), when=OTHERWISE, group="g")]
    assert "the pipeline: the alternatives of group 'g' are not next to each other" in _problems(apart)
    with pytest.raises(PipelineConfigError):
        branch(Mark("X"), when=lambda page: True)


def test_conditions_pickle():
    import dill

    assert dill.loads(dill.dumps(OTHERWISE)) is OTHERWISE
    c = dill.loads(dill.dumps(MetadataEquals("kind", "print")))
    assert c.describe() == "metadata.kind == 'print'"
    p = build([ImageFolderReader("x"), branch(Mark("P"), when=c, group="g")])
    assert len(dill.dumps(p.stages[0].pipeline)) > 0


# ------------------------------------------------------------------------------------------------ composites

def test_modular_transcriber_expands_and_keeps_its_group():
    t = ModularTranscriber(_lines(), _text(), "single-region", formulas_separately=True)
    assert [type(b).__name__ for b in t.components] == ["LayoutDetector", "LineDetector", "LineAssigner",
                                                    "LineRecognizer"]
    assert t.components[2].formulas_separately is True
    c = t.contract()
    assert c.kind == "composite" and c.unit == "page" and c.unit_out is None
    assert c.reads == {Part("image")}
    assert {str(p) for p in c.adds} == {"ocr_new:regions", "ocr_new:reading_order", "ocr_new:lines",
                                        "ocr_new:line_regions", "ocr_new:text", "ocr_new:line_confidences"}
    p = build([ImageFolderReader("x"), t, PageJsonlWriter("o")])
    components = p.describe()["stages"][0]["components"]
    assert [b.get("composite") for b in components] == [None, *["modular transcriber"] * 4, None]
    mermaid = p.mermaid()
    assert 'subgraph c1_modular_transcriber["modular transcriber"]' in mermaid
    assert '-->|"ocr_new:lines"|' in mermaid
    # backends are wrapped into their components
    t = ModularTranscriber(InProcess(LINES), InProcess(TEXT, template=TEMPLATE),
                           layout=InProcess("x:Layout"), transcription="mine")
    assert [type(b).__name__ for b in t.components] == ["LayoutDetector", "LineDetector", "LineAssigner", "LineRecognizer"]
    assert {b.transcription for b in t.components} == {"mine"}


def test_nested_composites_and_given_contracts():
    inner = Composite("inner", [_lines(), LineAssigner()])
    outer = Composite("outer", [LayoutDetector("single-region"), inner, _text()])
    p = build([ImageFolderReader("x"), outer])
    assert p.problems == []
    assert [b.get("composite") for b in p.describe()["stages"][0]["components"]] == [
        None, "outer", "outer/inner", "outer/inner", "outer"]
    assert "subgraph c1_outer_inner" in p.mermaid()
    given = Contract(unit="page", kind="composite", reads=frozenset({Part("image")}))
    assert Composite("x", [_lines()], contract=given).contract() is given
    with pytest.raises(PipelineConfigError):
        Composite("empty", [])


def test_modular_transcriber_runs_as_its_components():
    out = run_pages([ModularTranscriber(_lines(), _text(), "single-region")], [_doc("p1", 40)])
    t = page_of(out[0]).transcriptions["ocr_new"]
    assert [(ln.id, t.region_of(ln), ln.reading.text) for ln in t.lines] == [("page_l0", "page", "page 40x30 line 0"),
                                                                 ("page_l1", "page", "page 40x30 line 1")]


# ------------------------------------------------------------------------------------------------ stages

def _transcribe(a, texts: str):
    """Pages, then the item stage of --item-texts: the parts the page stage added carry across the binder (and the
    stage cut) to the item-level recomposition and composition, and the texts written from the item's document."""
    return [run.reader(a), ModularTranscriber(_lines(), _text(), "single-region"), run.pages(a), ItemAssembler(),
            ParagraphBuilder("unicode-paragraphs", unit="item"), DocumentComposer("linked-document", unit="item"),
            ItemDocumentWriter(texts, texts=("literal:txt", "latin-historic+flow:md")),
            ItemTextWriter(texts, texts=("literal:txt", "latin-historic+flow:md"))]


def _args(*argv):
    ap = run.parser(None)
    return run.check(ap, ap.parse_args(list(argv)))


def _texts(folder: Path) -> dict[str, str]:
    return {f.relative_to(folder).as_posix(): f.read_text() for f in sorted(folder.rglob("*"))
            if f.is_file() and f.suffix in (".txt", ".md")}


def _jsonl_texts(folder: Path) -> list:
    rows = []
    for f in folder.rglob("*.jsonl.gz"):
        rows += [json.loads(line) for line in gzip.open(f, "rt")]
    return sorted((r["id"], r["text"], tuple(r["page_ids"])) for r in rows)


def test_two_tasks_cut_at_the_binder(items, tmp_path: Path):
    a = _args(items, str(tmp_path / "out2"), "--item-from-parent", "--tasks", "2", "--workers", "1")
    p = run.build_plan(a, _transcribe(a, str(tmp_path / "texts2")))
    assert [(s.name, s.tasks) for s in p.stages] == [("pages", 2), ("items", 2)]
    first, second = p.stages
    assert type(first.components[-1]).__name__ == "PageJsonlWriter" and first.components[-1].item_shards == 2
    assert type(second.components[0]).__name__ == "PageRecordReader" and second.components[0].item_shards
    assert {str(x) for x in second.components[0].provides} >= {"ocr_new:lines", "ocr_new:text", "metadata"}
    assert "subgraph stage2" in p.mermaid() and "page records (item shards)" in p.mermaid()
    run.run(a, _transcribe(a, str(tmp_path / "texts2")), __file__, argv=[])
    one = _args(items, str(tmp_path / "out1"), "--item-from-parent")
    assert [s.name for s in run.build_plan(one, _transcribe(one, "t")).stages] == ["pages and items"]
    run.run(one, _transcribe(one, str(tmp_path / "texts1")), __file__, argv=[])
    texts = _texts(tmp_path / "texts1")
    assert sorted(texts) == ["latin-historic+flow/A.md", "latin-historic+flow/B.md", "literal/A.txt", "literal/B.txt"]
    assert "page 40x30 line 0" in texts["literal/A.txt"] and "page 44x30 line 1" in texts["literal/B.txt"]
    assert _texts(tmp_path / "texts2") == texts
    assert _jsonl_texts(tmp_path / "texts2") == _jsonl_texts(tmp_path / "texts1")
    out2 = tmp_path / "out2"
    assert (out2 / "logs" / "pages" / "completions" / "00001").exists()
    assert (out2 / "logs" / "items" / "completions" / "00001").exists()
    shards = {f.relative_to(out2 / "pages").parts[0] for f in (out2 / "pages").rglob("*.jsonl.gz")}
    assert shards and shards <= {"00000", "00001"} and len(_records(out2 / "pages")) == 5
    rec = yamlio.load((out2 / "run.yaml").read_text())
    assert [(s["name"], s["tasks"]) for s in rec["pipeline"]] == [("pages", 2), ("items", 2)]


def test_one_task_or_whole_items_need_no_cut(tmp_path: Path):
    components = [PageRecordReader("p", item_shards=True), ItemAssembler(), *item_texts("t")]
    assert [s.name for s in build(components, tasks=4, run_folder=str(tmp_path)).stages] == ["pages and items"]
    components = [ImageFolderReader("x"), _lines(), _text(), ItemAssembler(), *item_texts("t")]
    p = build(components, tasks=4)
    assert p.problems == ["ItemAssembler (📚 item assembler) binds items from pages that 4 tasks read: the cut into stages "
                          "needs a run folder"]


def test_servers_go_with_the_model_stage(tmp_path: Path):
    components = [ImageFolderReader("x"), LineDetector(Served("http://127.0.0.1:8100/v1", model="lines")), _text(),
              PageJsonlWriter(str(tmp_path / "pages")), ItemAssembler(), *item_texts("t"),
              EngineServer([{"name": "lines"}])]
    p = build(components, tasks=3, run_folder=str(tmp_path))
    assert p.problems == []
    assert [type(b).__name__ for b in p.stages[0].components] == ["ImageFolderReader", "LineDetector", "LineRecognizer",
                                                             "RejectWriter", "PageJsonlWriter", "EngineServer"]
    assert p.stages[0].components[3].output_folder == f"{tmp_path}/rejects"    # the pages that failed, before the writer
    assert p.stages[0].components[4].item_shards == 3                 # the run's page writer, now in item shards
    assert [type(b).__name__ for b in p.stages[1].components] == ["PageRecordReader", "ItemAssembler", "ItemSplitter",
                                                             "PageJsonlWriter"]


# ------------------------------------------------------------------------------------------------ partial runs, taps

def _modular(a):
    return [run.reader(a), ModularTranscriber(_lines(), _text(), "single-region"), HierarchyDetector("ratios"),
            DocumentComposer("linked-document"), run.pages(a)]


def test_until_after_and_taps(items, tmp_path: Path):
    full = _args(items, str(tmp_path / "full"), "--item-from-parent", "--tap-after", "LineDetector",
                 str(tmp_path / "tap"))
    run.run(full, _modular(full), __file__, argv=[])
    first = _args(items, str(tmp_path / "first"), "--item-from-parent", "--until", "LineAssigner")
    p = run.build_plan(first, _modular(first))
    assert [type(b).__name__ for b in p.components] == ["ImageFolderReader", "LayoutDetector", "LineDetector",
                                                    "LineAssigner", "RejectWriter", "PageJsonlWriter"]
    run.run(first, _modular(first), __file__, argv=[])
    second = _args(str(tmp_path / "second"), "--pages", str(tmp_path / "first" / "pages"), "--after", "LineAssigner")
    p = run.build_plan(second, _modular(second))
    assert [type(b).__name__ for b in p.components] == ["PageRecordReader", "LineRecognizer", "HierarchyDetector", "DocumentComposer",
                                                    "RejectWriter", "PageJsonlWriter"]
    assert {str(x) for x in p.components[0].provides} >= {"ocr_new:lines", "ocr_new:regions", "ocr_new:line_regions"}
    run.run(second, _modular(second), __file__, argv=[])
    halfway = _records(tmp_path / "first" / "pages")
    assert all(not ln.get("reading") for r in halfway.values() for ln in r["page"]["transcriptions"]["ocr_new"]["lines"])
    done, whole = _records(tmp_path / "second" / "pages"), _records(tmp_path / "full" / "pages")
    assert len(whole) == 5 and done == whole
    tapped = _records(tmp_path / "tap")
    assert sorted(tapped) == sorted(whole)
    lines = tapped["a1"]["page"]["transcriptions"]["ocr_new"]["lines"]
    assert [ln["id"] for ln in lines] == ["page_l0", "page_l1"] and not any(ln.get("reading") for ln in lines)


def test_partial_run_problems(tmp_path: Path):
    components = [ImageFolderReader("x"), _lines(), _text(), PageJsonlWriter("o")]
    assert _problems(components, after="LineDetector") == [
        "--after LineDetector: the run must start from page records (--pages DIR)"]
    assert _problems([ImageFolderReader("x"), _lines(), _lines()], until="LineDetector")[0] == (
        "--until LineDetector: 2 components have that name (LineDetector (lines (in-process)), LineDetector (lines "
        "(in-process))); use the component's datatrove name")
    assert _problems(components, until="LineDetector") == ["--until LineDetector: needs a run folder for the page records"]
    assert _problems(components, taps={"PageJsonlWriter": "t"}) == []
    assert _problems(components + [ItemAssembler()], taps={"ItemAssembler": "t"}) == [
        "--tap-after ItemAssembler: page records can only be tapped after a page component"]
    # by datatrove name, and by composite (its last component)
    p = build([ImageFolderReader("x"), ModularTranscriber(_lines(), _text(), "single-region"), PageJsonlWriter("o")],
              until="modular transcriber", run_folder=str(tmp_path))
    assert p.problems == [] and [type(b).__name__ for b in p.components[-3:]] == ["LineRecognizer", "RejectWriter",
                                                                              "PageJsonlWriter"]
    assert build(components, until="lines (in-process)", run_folder=str(tmp_path)).problems == []


def test_the_recipe_is_stamped_before_the_first_writer():
    p = build([ImageFolderReader("x"), _lines(), PageFileWriter("f", formats=("hocr",)), PageJsonlWriter("o")],
              recipe=("r", "sha256:" + "0" * 64))
    assert [type(b).__name__ for b in p.components] == ["ImageFolderReader", "LineDetector", "RecipeStamper",
                                                    "PageFileWriter", "PageJsonlWriter"]


# ------------------------------------------------------------------------------------------------ observers

class Log(Observer):
    def __init__(self):
        self.events = []

    def on_task_start(self, rank, world_size):
        self.events.append(("start", rank, world_size))

    def on_enter(self, component, doc):
        self.events.append(("enter", type(component).__name__, doc.id))

    def on_exit(self, component, doc, error=None):
        self.events.append(("exit", type(component).__name__, doc.id, error))

    def on_task_end(self, error=None):
        self.events.append(("end",))


class Fails(PageComponent):
    def process_page(self, doc, page):
        doc.metadata.setdefault("errors", []).append({"step": "x", "error": "boom"})
        return page


def test_boundaries_call_the_observers(tmp_path: Path):
    log = Log()
    _png(tmp_path / "p1.png", 40)
    run_pages([ImageFolderReader(str(tmp_path)), Mark("M"), Fails()], observers=[log])
    assert log.events == [("start", 0, 1), ("exit", "ImageFolderReader", "p1", None), ("enter", "Mark", "p1"),
                          ("exit", "Mark", "p1", None), ("enter", "Fails", "p1"),
                          ("exit", "Fails", "p1", {"step": "x", "error": "boom"}), ("end",)]
    # no observers, no boundaries
    p = build([ImageFolderReader("x"), Mark("M")])
    assert p.stages[0].pipeline == p.stages[0].components and p.stages[0].observers is None


def test_run_pages_checks_first():
    with pytest.raises(PipelineConfigError):
        run_pages([_lines(), ItemAssembler(), DocumentComposer("linked-document")], [_doc()])
    out = run_pages([LayoutDetector("single-region"), _lines(), LineAssigner(), _text()], [_doc("p1"), _doc("p2", 50)])
    assert [d.id for d in out] == ["p1", "p2"]
    assert page_of(out[1]).transcriptions["ocr_new"].lines[0].reading.text == "page 50x30 line 0"


def test_contracts_with_tables_and_validation():
    from linecaster.components.validation import PageValidator

    p = build([ImageFolderReader("x"), PageValidator(required=("transcriptions.ocr_new",)), _lines()])
    assert p.problems == ["PageValidator (✅ page validator) reads ocr_new:*, which no component before it in the "
                          "pipeline adds"]
    assert build([ImageFolderReader("x"), _lines(), PageValidator(required=("transcriptions.ocr_new",))]).problems == []
    # "image" is the page record's image entry (metadata), still there after the bytes are removed
    from linecaster.components.images import ImageConverter
    assert build([ImageFolderReader("x"), ImageConverter("out", "working-image"),
                  PageValidator(required=("image",))]).problems == []
    assert build([ImageFolderReader("x"), TableRecognizer(InProcess("x:T"))]).problems == [
        "TableRecognizer (tables (in-process)) reads ocr_new:regions, which no component before it in the pipeline adds"]


# ------------------------------------------------------------------------------------------------ the command line

def test_a_broken_pipeline_fails_before_anything_is_written(tmp_path: Path):
    _png(tmp_path / "images" / "p1.png", 40)
    a = _args(str(tmp_path / "images"), str(tmp_path / "out"))
    with pytest.raises(PipelineConfigError) as e:
        run.run(a, [run.reader(a), _text(), ItemAssembler(), DocumentComposer("linked-document"), run.pages(a)], __file__,
                argv=[])
    assert len(e.value.problems) == 5 and not (tmp_path / "out").exists()


def test_one_page_in_this_process(tmp_path: Path, capsys):
    _png(tmp_path / "images" / "p1.png", 40)
    _png(tmp_path / "images" / "p2.png", 50)
    a = _args("--page", str(tmp_path / "images" / "p2.png"), str(tmp_path / "out"))
    assert run.executor_name(a) == "run_pages"
    run.run(a, _modular(a), __file__, argv=[])
    assert json.loads(capsys.readouterr().out) == {"out": str(tmp_path / "out"), "pages": ["p2"]}
    records = _records(tmp_path / "out" / "pages")
    assert list(records) == ["p2"]
    assert records["p2"]["page"]["transcriptions"]["ocr_new"]["lines"][0]["reading"]["text"] == "page 50x30 line 0"
    assert yamlio.load((tmp_path / "out" / "run.yaml").read_text())["executor"] == "run_pages"
    ap = run.parser(None)
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(["--page", "x.png", "out", "--tasks", "2"]))
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(["images", "out", "--after", "LineAssigner"]))


def test_linecaster_page_finds_the_script():
    from linecaster.cli import page_command

    cmd = page_command("p.png", "out", ["--recipe", "squiddle", "--files", "out/files"])
    assert cmd[:3] == ["uv", "run", "--script"] and cmd[3].endswith("pipelines/transcribe_modular.py")
    assert cmd[4:] == ["--page", "p.png", "out", "--recipe", "squiddle", "--files", "out/files"]
    assert page_command("p.png", "out", [], "transcribe_vlm.v1")[3].endswith("pipelines/transcribe_vlm.py")
    with pytest.raises(PipelineConfigError):
        page_command("p.png", "out", [], "nope.v1")


def test_the_cut_keeps_the_pipelines_item_shards_and_its_file_system():
    components = [ImageFolderReader("x"), _lines(), _text(), PageJsonlWriter("memory://lc/out/pages", item_shards=5),
              ItemAssembler(), *item_texts("memory://lc/texts")]
    first, second = build(components, tasks=3, run_folder="memory://lc/out").stages
    assert (first.tasks, second.tasks) == (3, 5)
    assert second.components[0].data_folder is first.components[-1].output_folder
    components = [ImageFolderReader("x"), _lines(), _text(), ItemAssembler(), *item_texts("memory://lc/texts")]
    first, second = build(components, tasks=3, run_folder="memory://lc/out2").stages
    assert "memory" in first.components[-1].output_folder.fs.protocol and first.components[-1].item_shards == 3
    assert "memory" in second.components[0].data_folder.fs.protocol


@pytest.mark.parametrize("on", ["local", "ray", "hf-jobs"])
def test_each_stage_gets_an_executor_that_depends_on_the_one_before(on):
    pytest.importorskip("ray") if on == "ray" else None
    out = f"memory://lc/stages-{on}"
    jobs = ["--namespace", "ns", "--commit", "abc"] if on == "hf-jobs" else []
    a = _args("images", out, "--tasks", "2", "--on", on, *jobs)
    components = [run.reader(a), ModularTranscriber(_lines(), _text(), "single-region"), run.pages(a), ItemAssembler(),
              *item_texts("memory://lc/texts"), EngineServer([])]
    p = run.build_plan(a, components)
    last = run._executors(a, p, out, None, ["linecaster"])
    first = last.depends
    assert first is not None and first.depends is None
    assert (first.logging_dir.path.endswith("/logs/pages"), last.logging_dir.path.endswith("/logs/items")) == (True, True)
    assert first.pipeline is p.stages[0].pipeline and last.pipeline is p.stages[1].pipeline
    if on == "ray":
        assert (type(first).__name__, type(last).__name__) == ("RayGPUExecutor", "RayExecutor")
    if on == "hf-jobs":
        assert (first.job_name, last.job_name) == ("linecaster-stages-hf-jobs-pages", "linecaster-stages-hf-jobs-items")
        assert type(first).__name__ == "JobsExecutor" and first.env["LINECASTER_LOG_JSON"] == "1"  # JSON lines
        assert first.namespace == "ns"


def test_hf_jobs_need_a_namespace_and_take_none_from_the_account():
    with pytest.raises(SystemExit):
        _args("images", "memory://lc/ns", "--on", "hf-jobs", "--commit", "abc")
    assert _args("images", "memory://lc/ns", "--on", "hf-jobs", "--commit", "abc", "--namespace", "org").namespace == "org"
    assert _args("images", "memory://lc/ns").namespace is None


def test_every_page_record_carries_its_time_in_the_run(tmp_path: Path):
    """``PageTiming``: a page's record has ``measurements.seconds`` (from its reader to its first writer, so the time of
    the components between; waiting included) and ``datetime`` (when the reader handed it over); a tap before the writer
    has none yet, and a stage that writes no page gets no timing."""
    import time

    from linecaster.components.writers.records import PageJsonlWriter
    from linecaster.core.observers import PageTiming

    class Slow(Mark):
        def process_page(self, doc, page):
            time.sleep(0.05)
            return super().process_page(doc, page)

    src = tmp_path / "images"
    src.mkdir()
    for name in ("p1", "p2"):
        _png(src / f"{name}.png", 40)
    src = str(src)
    run_plan(build([ImageFolderReader(src), Slow("S"), PageJsonlWriter(str(tmp_path / "out" / "pages"))],
                   taps={"S": str(tmp_path / "tap")}))
    for f in (tmp_path / "out" / "pages").rglob("*.jsonl.gz"):
        for line in gzip.open(f, "rt"):
            m = json.loads(line)["page"]["measurements"]
            assert set(m) == {"seconds", "datetime"} and 0.05 <= m["seconds"] < 5 and m["datetime"].endswith("Z")
    for f in (tmp_path / "tap").rglob("*.jsonl.gz"):
        assert all(json.loads(line)["page"]["measurements"] == {} for line in gzip.open(f, "rt"))
    assert build([ImageFolderReader(src), Mark("M")]).stages[0].observers is None
    hub = build([ImageFolderReader(src), PageJsonlWriter(str(tmp_path / "p"))]).stages[0].observers
    assert [type(o) for o in hub.observers] == [PageTiming]
    # a second run over the records adds its time and keeps the first run's start
    first = {r["id"]: r["page"]["measurements"] for f in (tmp_path / "out" / "pages").rglob("*.jsonl.gz")
             for r in map(json.loads, gzip.open(f, "rt"))}
    run_plan(build([PageRecordReader(str(tmp_path / "out" / "pages")), Slow("T", key="mark2"),
                    PageJsonlWriter(str(tmp_path / "again" / "pages"))]))
    again = {r["id"]: r["page"]["measurements"] for f in (tmp_path / "again" / "pages").rglob("*.jsonl.gz")
             for r in map(json.loads, gzip.open(f, "rt"))}
    assert again.keys() == first.keys()
    for k, m in again.items():
        assert m["datetime"] == first[k]["datetime"] and m["seconds"] >= first[k]["seconds"] + 0.05
