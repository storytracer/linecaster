"""Provenance: the steps (annotators of kind model and rule) in ALTO, PAGE and hOCR (written and read back), METS
agents, the run record (its run id on every annotator the run adds, the hardware)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from linecaster.backends import InProcess, Served
from linecaster.catalog import yamlio
from linecaster.data import Annotator
from linecaster.errors import PipelineConfigError
from linecaster.formats import _provenance as P, from_alto, from_hocr, from_page, to_alto, to_hocr, to_page
from linecaster.runtime import provenance, run
from linecaster.runtime.record import RunRecord

from conftest import sample_transcription

SCHEMAS = Path(__file__).parents[1] / "schemas"
SHA = "sha256:" + "ab" * 32
STEPS = [
    Annotator(step="layout", name="PP-DocLayoutV3", backend="paddlex/onnxruntime", settings={"threshold": 0.5}),
    Annotator(step="recognition", name="kraken-ppocrv6-medium", engine="kraken.recognition.v1", revision="0123abcd",
              preset="kraken-ppocrv6-medium@1", preset_sha256=SHA, backend="in-process",
              settings={"batch_size": 8, "model": "medium", "n": "16"},
              measurements={"seconds": 1.25, "datetime": "2026-11-03T21:00:00Z"}),
    Annotator(kind="rule", step="unicode", name="unicodedata", settings={"form": "NFC"}),
]
#: the annotator of a set read from a file that names no steps
FILE = Annotator(kind="file", step="transcription", name="sample")


def _schema(name):
    return etree.XMLSchema(etree.parse(str(SCHEMAS / name)))


def _t():
    t = sample_transcription()
    t.annotators = [m.model_copy(deep=True) for m in STEPS]        # the sample's annotations name the first
    return t


def _untold():
    """The sample transcription read from a file that names no steps."""
    t = sample_transcription()
    t.annotators = [FILE.model_copy()]
    return t


def _files(t) -> list[str]:
    return [a.kind for a in t.annotators]


def _same_steps(got, want=STEPS):
    assert [m.model_dump(exclude={"measurements"}) for m in got] == [m.model_dump(exclude={"measurements"})
                                                                     for m in want]


# ------------------------------------------------------------------------------------------------ ALTO

def test_alto_processing_per_step():
    data = to_alto(_t())
    assert _schema("alto-4-4.xsd").validate(etree.fromstring(data))
    ns = {"a": "http://www.loc.gov/standards/alto/ns-v4#"}
    root = etree.fromstring(data)
    procs = root.findall("a:Description/a:Processing", ns)
    assert [p.findtext("a:processingStepDescription", namespaces=ns) for p in procs] == ["layout", "recognition",
                                                                                          "unicode"]
    rec = procs[1]
    assert [etree.QName(c).localname for c in rec] == ["processingCategory", "processingDateTime",
                                                       "processingStepDescription", "processingStepSettings",
                                                       "processingSoftware"]
    assert rec.findtext("a:processingCategory", namespaces=ns) == "contentGeneration"
    assert procs[2].findtext("a:processingCategory", namespaces=ns) == "contentModification"
    assert rec.findtext("a:processingDateTime", namespaces=ns) == "2026-11-03T21:00:00Z"
    settings = json.loads(rec.findtext("a:processingStepSettings", namespaces=ns))
    assert settings == {"engine": "kraken.recognition.v1", "revision": "0123abcd", "preset": "kraken-ppocrv6-medium@1", "preset_sha256": SHA,
                        "backend": "in-process", "settings": {"batch_size": 8, "model": "medium", "n": "16"}}
    sw = rec.find("a:processingSoftware", ns)
    assert [(etree.QName(c).localname, c.text) for c in sw] == [
        ("softwareCreator", "linecaster"), ("softwareName", "kraken-ppocrv6-medium"), ("softwareVersion", "0123abcd"),
        ("applicationDescription", f"{P.software()}; preset kraken-ppocrv6-medium@1; backend in-process")]
    page = root.find("a:Layout/a:Page", ns)
    assert page.get("PROCESSINGREFS") == " ".join(p.get("ID") for p in procs)
    got = from_alto(data)
    _same_steps(got.annotators)
    assert got.annotators[1].measurements == {"datetime": "2026-11-03T21:00:00Z"}


def test_alto_without_steps_has_no_processing():
    data = to_alto(_untold())
    assert b"Processing" not in data and b"PROCESSINGREFS" not in data
    assert _files(from_alto(data)) == ["file"]


ALTO_V2_OCR_PROCESSING = b"""<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Description><MeasurementUnit>pixel</MeasurementUnit>
    <OCRProcessing ID="OCR_0">
      <preProcessingStep><processingStepDescription>deskew</processingStepDescription></preProcessingStep>
      <ocrProcessingStep>
        <processingDateTime>2012-05-01</processingDateTime>
        <processingStepSettings>mode: fast</processingStepSettings>
        <processingSoftware><softwareCreator>ABBYY</softwareCreator><softwareName>FineReader</softwareName>
          <softwareVersion>10.0</softwareVersion></processingSoftware>
      </ocrProcessingStep>
    </OCRProcessing>
  </Description>
  <Layout><Page ID="p1" WIDTH="100" HEIGHT="100"><PrintSpace/></Page></Layout>
</alto>"""


def test_alto_foreign_ocr_processing():
    m = from_alto(ALTO_V2_OCR_PROCESSING).annotators
    assert [(x.step, x.name, x.revision, x.settings) for x in m] == [
        ("deskew", "unknown", None, {}), ("unknown", "FineReader", "10.0", {"raw": "mode: fast"})]
    assert m[1].measurements == {"datetime": "2012-05-01"}


# ------------------------------------------------------------------------------------------------ PAGE

def test_page_metadata_items():
    data = to_page(_t())
    assert _schema("pagecontent-2019-07-15.xsd").validate(etree.fromstring(data))
    ns = {"p": "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"}
    md = etree.fromstring(data).find("p:Metadata", ns)
    assert md.findtext("p:Creator", namespaces=ns) == P.software()
    assert md.findtext("p:Comments", namespaces=ns) == (
        "layout: PP-DocLayoutV3; recognition: kraken-ppocrv6-medium@0123abcd (preset kraken-ppocrv6-medium@1); "
        "unicode: unicodedata")
    items = md.findall("p:MetadataItem", ns)
    assert [(i.get("type"), i.get("name"), i.get("value")) for i in items] == [
        ("processingStep", "layout", "PP-DocLayoutV3"), ("processingStep", "recognition", "kraken-ppocrv6-medium@1"),
        ("processingStep", "unicode", "unicodedata")]
    assert items[1].get("date") == "2026-11-03T21:00:00Z"
    model, settings = items[1].findall("p:Labels", ns)
    assert (model.get("externalModel"), model.get("externalId")) == ("linecaster", "model")
    assert [(lb.get("type"), lb.get("value")) for lb in model] == [
        ("name", "kraken-ppocrv6-medium"), ("engine", "kraken.recognition.v1"), ("revision", "0123abcd"),
        ("preset", "kraken-ppocrv6-medium@1"), ("preset_sha256", SHA), ("backend", "in-process"),
        ("software", P.software())]
    assert [(lb.get("type"), lb.get("value")) for lb in settings] == [
        ("batch_size", "8"), ("model", "medium"), ("n", '"16"')]
    _same_steps(from_page(data).annotators)


PAGE_OCRD = b"""<?xml version="1.0" encoding="UTF-8"?>
<pc:PcGts xmlns:pc="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <pc:Metadata>
    <pc:Creator>OCR-D/core 2.67.2</pc:Creator><pc:Created>2024-01-01T00:00:00</pc:Created>
    <pc:LastChange>2024-01-01T00:00:00</pc:LastChange>
    <pc:MetadataItem type="processingStep" name="recognition/text-recognition" value="ocrd-tesserocr-recognize">
      <pc:Labels externalModel="ocrd-tool" externalId="parameters">
        <pc:Label value="deu" type="model"/>
        <pc:Label value="word" type="textequiv_level"/>
      </pc:Labels>
      <pc:Labels externalModel="ocrd-tool" externalId="version">
        <pc:Label value="0.17.0" type="ocrd-tesserocr-recognize"/>
      </pc:Labels>
    </pc:MetadataItem>
    <pc:MetadataItem type="other" name="x" value="y"/>
  </pc:Metadata>
  <pc:Page imageFilename="p.png" imageWidth="10" imageHeight="10"/>
</pc:PcGts>"""


def test_page_foreign_ocrd_processing_step():
    m = from_page(PAGE_OCRD).annotators
    assert len(m) == 1
    assert (m[0].step, m[0].name) == ("recognition/text-recognition", "ocrd-tesserocr-recognize")
    assert m[0].settings == {"model": "deu", "textequiv_level": "word", "ocrd-tesserocr-recognize": "0.17.0"}


# ------------------------------------------------------------------------------------------------ hOCR

def _metas(data: bytes) -> dict:
    root = etree.fromstring(data)
    return {m.get("name"): m.get("content") for m in root.iter("{http://www.w3.org/1999/xhtml}meta")}


def test_hocr_metadata_and_steps():
    t = _t()
    t.classify(0, "", "language", "de")
    metas = _metas(to_hocr(t))
    assert metas["ocr-system"] == P.software()
    assert metas["ocr-number-of-pages"] == "1" and metas["ocr-langs"] == "de"
    assert metas["ocr-capabilities"] == ("ocr_page ocr_carea ocr_header ocr_photo ocr_par ocr_line ocrx_word "
                                         "ocrp_lang ocrp_poly ocrp_wconf")
    assert json.loads(metas["linecaster-step-1"]) == {
        "step": "recognition", "name": "kraken-ppocrv6-medium", "engine": "kraken.recognition.v1", "revision": "0123abcd",
        "preset": "kraken-ppocrv6-medium@1", "preset_sha256": SHA, "backend": "in-process",
        "settings": {"batch_size": 8, "model": "medium", "n": "16"}}
    _same_steps(from_hocr(to_hocr(t)).annotators)


def test_hocr_capabilities_follow_the_content():
    t = _untold()
    t.regions, t.classifications = [], []
    for ln in t.lines:
        ln.region, ln.polygon = None, None
        if ln.reading is not None:
            ln.reading.words, ln.reading.confidence = [], None
    t.classify(0, "", "language", "deu")          # not ISO 639-1: no ocr-langs, but lang attributes
    metas = _metas(to_hocr(t))
    assert metas["ocr-capabilities"] == "ocr_page ocr_line ocrp_lang"
    assert "ocr-langs" not in metas and not any(k.startswith("linecaster-step-") for k in metas)
    assert _files(from_hocr(to_hocr(t))) == ["file"]


def test_hocr_foreign_ocr_system():
    html = (b"<html xmlns='http://www.w3.org/1999/xhtml'><head><meta name='ocr-system' content='tesseract 5.3.0'/>"
            b"</head><body><div class='ocr_page' title='bbox 0 0 10 10'></div></body></html>")
    assert [(m.step, m.name) for m in from_hocr(html).annotators] == [("recognition", "tesseract 5.3.0")]


# ------------------------------------------------------------------------------------------------ values

@pytest.mark.parametrize("v", [None, True, 0, 16, 0.1, "", "16", "true", "null", "medium", ' "x" ', "a\nb",
                               [1, "2"], {"k": {"n": None}}])
def test_setting_values_round_trip(v):
    assert P.decode_value(P.encode_value(v)) == v


# ------------------------------------------------------------------------------------------------ METS

def test_mets_agent():
    agent = provenance.mets_agent(STEPS[1])
    M, LC, OCRD = provenance.METS, provenance.LC, provenance.OCRD
    assert agent.tag == f"{{{M}}}agent"
    assert dict(agent.attrib) == {"TYPE": "OTHER", "OTHERTYPE": "SOFTWARE", "ROLE": "OTHER",
                                  "OTHERROLE": "recognition/text-recognition"}
    assert agent.findtext(f"{{{M}}}name") == f"{P.software()} kraken-ppocrv6-medium@0123abcd"
    notes = [(n.get(f"{{{OCRD}}}option") or n.get(f"{{{LC}}}option"), n.text) for n in agent.iter(f"{{{M}}}note")]
    assert notes == [("parameter", '{"batch_size":8,"model":"medium","n":"16"}'), ("step", "recognition"),
                     ("name", "kraken-ppocrv6-medium"), ("engine", "kraken.recognition.v1"), ("revision", "0123abcd"),
                     ("preset", "kraken-ppocrv6-medium@1"), ("preset_sha256", SHA), ("backend", "in-process")]
    _same_steps([provenance.from_mets_agent(a) for a in provenance.mets_agents(STEPS)])
    assert provenance.mets_agent(STEPS[2]).get("OTHERROLE") == provenance.OCRD_FALLBACK_STEP


def test_mets_agents_validate():
    M = provenance.METS
    mets = etree.Element(f"{{{M}}}mets", nsmap={"mets": M})
    hdr = etree.SubElement(mets, f"{{{M}}}metsHdr")
    for a in provenance.mets_agents(STEPS):
        hdr.append(a)
    smap = etree.SubElement(mets, f"{{{M}}}structMap")
    etree.SubElement(smap, f"{{{M}}}div")
    schema = _schema("mets-1-12-1.xsd")
    assert schema.validate(etree.fromstring(etree.tostring(mets))), schema.error_log


# ------------------------------------------------------------------------------------------------ run record

class StampModel:
    """A test engine: appends its annotator and adds nothing else."""

    engine_id, step, name = "stamp.recognition.v1", "recognition", "stamp"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def load(self):
        pass

    def __call__(self, image, t, **params):
        t.add_annotator(Annotator(step=self.step, name=self.name, revision="r1", backend="in-process",
                                  settings=dict(self.kwargs)))
        return t


class OneLineModel:
    """A test line engine: one line over the page, its annotator without engine, revision or settings."""

    step, name = "lines", "one-line"

    def __init__(self, **kwargs):
        pass

    def load(self):
        pass

    def __call__(self, image, t, **params):
        h, w = image.shape[:2]
        a = t.add_annotator(Annotator(step=self.step, name=self.name))
        t.add_line(a, "l0", [0, 0, w, h], [[0, 0], [w, 0], [w, h], [0, h]])
        return t


def _images(folder: Path) -> str:
    folder.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    (folder / "p1.png").write_bytes(buf.getvalue())
    return str(folder)


def _args(*argv):
    ap = run.parser(None)
    return run.check(ap, ap.parse_args(list(argv)))


def _pipeline(a, files: str):
    from linecaster.blocks.lines.detector import LineDetector
    from linecaster.blocks.recognition.recognizers import LineRecognizer
    from linecaster.blocks.writers.files import PageFileWriter

    backend = InProcess("test_provenance:StampModel", size=3)
    backend.preset, backend.preset_sha256 = "stamp@2", SHA
    return [run.reader(a), LineDetector(InProcess("test_provenance:OneLineModel")), LineRecognizer(backend),
            PageFileWriter(files, formats=("alto", "page", "hocr")), run.pages(a)]


def test_run_writes_the_record_and_the_files_carry_the_preset(tmp_path: Path):
    images, out, files = _images(tmp_path / "images"), str(tmp_path / "out"), str(tmp_path / "files")
    argv = [images, out, "--env", "HF_TOKEN=secret"]
    a = _args(*argv)
    run.run(a, _pipeline(a, files), __file__, argv=argv)
    text = (tmp_path / "out" / "run.yaml").read_text()
    assert "secret" not in text
    rec = yamlio.load(text)
    assert rec["schema"] == "linecaster.run-record/1" and rec["created"].endswith("Z")
    assert len(rec["run_id"]) == 32 and int(rec["run_id"], 16) >= 0
    assert isinstance(rec.get("hardware", {}), dict) and set(rec.get("hardware", {})) <= {
        "gpu", "gpu_count", "driver", "cuda", "cpu", "machine"}
    assert RunRecord.model_validate(rec).pipeline_sha256 == rec["pipeline_sha256"]
    assert rec["script"]["path"].endswith("tests/runtime/test_provenance.py")
    assert rec["script"]["sha256"].startswith("sha256:")
    assert rec["argv"] == [images, out, "--env", "HF_TOKEN=<redacted>"]
    assert rec["options"]["env"] == ["HF_TOKEN=<redacted>"] and rec["options"]["images"] == images
    assert (rec["on"], rec["executor"], rec["tasks"]) == ("local", "LocalPipelineExecutor", 1)
    (stage,) = rec["pipeline"]
    assert (stage["name"], stage["tasks"]) == ("pages", 1)
    assert [b["block"] for b in stage["blocks"]] == ["ImageFolderReader", "LineDetector", "LineRecognizer",
                                                     "RejectWriter", "PageFileWriter", "PageJsonlWriter"]
    recognizer = stage["blocks"][2]
    assert recognizer["class"] == "linecaster.blocks.recognition.recognizers:LineRecognizer"
    assert recognizer["params"]["backend"] == {"backend": "in-process", "engine": "test_provenance:StampModel",
                                               "options": {"size": 3}, "preset": "stamp@2", "preset_sha256": SHA}
    assert recognizer["contract"]["role"] == "model" and recognizer["contract"]["reads"] == ["image", "ocr_new:lines"]
    assert rec["pipeline_sha256"] == provenance.pipeline_sha256(run.build_plan(a, _pipeline(a, files)))
    sw = rec["software"]
    assert sw["linecaster"] == provenance.version() and sw["python"].startswith("3.")
    assert set(sw["packages"]) >= {"datatrove", "saturate", "docling-core"}
    # every page file carries the steps, the recognizer with its preset
    for name, reader in (("p1.alto.xml", from_alto), ("p1.page.xml", from_page), ("p1.hocr", from_hocr)):
        m = reader((tmp_path / "files" / name).read_bytes()).annotators
        assert [(x.step, x.name, x.engine, x.revision, x.preset, x.preset_sha256, x.settings) for x in m] == [
            ("lines", "one-line", None, None, None, None, {}),
            ("recognition", "stamp", "stamp.recognition.v1", "r1", "stamp@2", SHA, {"size": 3})]
    # every annotator the run added names it in the page records
    import gzip

    [row] = [json.loads(x) for f in (tmp_path / "out" / "pages").rglob("*.jsonl.gz") for x in gzip.open(f, "rt")]
    assert [a.get("run") for a in row["page"]["transcriptions"]["ocr_new"]["annotators"]] == [rec["run_id"]] * 2
    # a second launch of the same pipeline into the same OUT (a resume) keeps run.yaml and writes its own record next
    # to it
    again = _args(*argv)
    run.run(again, _pipeline(again, files), __file__, argv=argv)
    assert (tmp_path / "out" / "run.yaml").read_text() == text
    [later] = list((tmp_path / "out").glob("run-*.yaml"))
    assert yamlio.load(later.read_text())["run_id"] not in (None, rec["run_id"])        # each launch its own id


def test_a_run_into_a_folder_of_another_pipeline_or_tasks_is_refused(tmp_path: Path):
    images, out, files = _images(tmp_path / "images"), str(tmp_path / "out"), str(tmp_path / "files")
    a = _args(images, out)
    run.run(a, _pipeline(a, files), __file__, argv=[])
    other = _args(images, out)
    changed = _pipeline(other, files)
    changed[2].backend.kwargs["size"] = 4                      # a functional option: another pipeline
    with pytest.raises(PipelineConfigError, match="holds a run of another pipeline") as e:
        run.run(other, changed, __file__, argv=[])
    assert "--new-pipeline" in str(e.value)
    with pytest.raises(PipelineConfigError, match="--tasks 1"):
        run.run(_args(images, out, "--tasks", "2"), _pipeline(a, files), __file__, argv=[])
    # --dry-run says so too, after printing the plan
    with pytest.raises(PipelineConfigError, match="another pipeline"):
        run.run(_args(images, out, "--dry-run"), changed, __file__, argv=[])
    # an operational change (where the files go) is the same pipeline: a resume
    moved = _args(images, out)
    run.run(moved, _pipeline(moved, str(tmp_path / "elsewhere")), __file__, argv=[])
    assert len(list((tmp_path / "out").glob("run-*.yaml"))) == 1
    # --new-pipeline knowingly: its record is kept next to the first, and the next resume compares with it
    knowingly = _args(images, out, "--new-pipeline")
    run.run(knowingly, changed, __file__, argv=[])
    assert run.previous_record(out)["pipeline_sha256"] == provenance.pipeline_sha256(run.build_plan(other, changed))
    assert yamlio.load((tmp_path / "out" / "run.yaml").read_text())["pipeline_sha256"] != (
        run.previous_record(out)["pipeline_sha256"])
    with pytest.raises(PipelineConfigError, match="--tasks"):        # the tasks never change, not even knowingly
        run.run(_args(images, out, "--tasks", "3", "--new-pipeline"), changed, __file__, argv=[])


def test_dry_run_prints_the_record_and_writes_nothing(tmp_path: Path, capsys):
    images, out = _images(tmp_path / "images"), str(tmp_path / "out")
    a = _args(images, out, "--dry-run")
    run.run(a, _pipeline(a, str(tmp_path / "files")), __file__, argv=[images, out, "--dry-run"])
    printed = capsys.readouterr().out
    plan, end = json.JSONDecoder().raw_decode(printed)
    assert plan["record"]["schema"] == "linecaster.run-record/1"
    assert plan["record"]["pipeline"][0]["blocks"][2]["params"]["backend"]["preset"] == "stamp@2"
    assert plan["record"]["pipeline_sha256"].startswith("sha256:")
    assert [b["block"] for b in plan["plan"]["stages"][0]["blocks"]][:3] == ["ImageFolderReader", "LineDetector",
                                                                            "LineRecognizer"]
    assert plan["plan"]["problems"] == []
    assert printed[end:].strip().startswith("flowchart TD")
    assert not (tmp_path / "out").exists()


def test_record_on_any_fsspec_folder():
    rec = provenance.run_record({"on": "local", "tasks": 2}, None, created=__import__("datetime").datetime(
        2026, 11, 3, 12, 0, tzinfo=__import__("datetime").timezone.utc))
    assert rec["created"] == "2026-11-03T12:00:00Z" and rec["pipeline"] == []
    out = "memory://linecaster-tests/run-record"
    assert run.write_record(out, rec) == "run.yaml"
    assert run.write_record(out, rec) == "run-20261103T120000Z.yaml"
    from datatrove.io import get_datafolder

    with get_datafolder(out).open("run.yaml", "r") as f:
        assert yamlio.load(f.read()) == rec


def test_served_and_in_process_are_the_same_pipeline():
    """The hash covers what a block does: the engine, its options and preset, wherever it runs."""
    from linecaster.blocks.readers.images import ImageFolderReader
    from linecaster.blocks.recognition.recognizers import LineRecognizer
    from linecaster.blocks.servers.serve import ModelServer
    from linecaster.blocks.writers.records import PageJsonlWriter
    from linecaster.runtime.builder import build

    m = {"name": "recognition", "spec": "pkg:Rec", "kwargs": {"weights": {"model": "m"}}, "preset": "rec@3",
         "preset_sha256": SHA}
    local = InProcess(m["spec"], **m["kwargs"])
    local.preset, local.preset_sha256 = m["preset"], m["preset_sha256"]
    reader = ImageFolderReader("images")
    in_process = build([reader, LineRecognizer(local), PageJsonlWriter("out/pages")], run_folder="out")
    served = build([ImageFolderReader("elsewhere"), LineRecognizer(Served("http://127.0.0.1:8100/v1", model="recognition",
                                                                          max_window=8)),
                    PageJsonlWriter("other/pages"), ModelServer([m], port=8100)], run_folder="other")
    assert provenance.functional_pipeline(in_process) == provenance.functional_pipeline(served)
    assert provenance.pipeline_sha256(in_process) == provenance.pipeline_sha256(served)
    f = provenance.functional_pipeline(in_process)
    assert [b["block"] for b in f] == ["ImageFolderReader", "LineRecognizer", "RejectWriter", "PageJsonlWriter"]
    assert f[1]["params"]["backend"] == {"engine": "pkg:Rec", "options": {"weights": {"model": "m"}},
                                         "preset": "rec@3", "preset_sha256": SHA}
    assert "data_folder" not in f[0]["params"] and "output_folder" not in f[3].get("params", {})
    # a functional parameter changes it
    other = build([reader, LineRecognizer(local, transcription="mine"), PageJsonlWriter("out/pages")], run_folder="out")
    assert provenance.pipeline_sha256(other) != provenance.pipeline_sha256(in_process)


def test_chat_blocks_record_the_preset_model_and_revision():
    from linecaster.adapters import chat_model
    from linecaster.backends import Chat
    from linecaster.blocks.recognition import PageRecognizer

    spec = chat_model("lightonocr-2-1b")
    block = PageRecognizer(Chat(spec, "http://127.0.0.1:8000/v1", served_name="m"))
    adapter = {"adapter": f"{type(spec).__module__}:{type(spec).__qualname__}", "preset": spec.preset,
               "preset_sha256": spec.preset_sha256, "model": spec.model, "revision": spec.revision,
               "repetition_detection": {"min_pattern_size": 8, "max_pattern_size": 100, "min_count": 16}}          # on by default: in the hash
    assert block.to_dict()["params"]["backend"] == {
        "backend": "chat", **adapter, "served_name": "m", "endpoint": "http://127.0.0.1:8000/v1", "max_window": 32,
        "initial_window": 4, "read_timeout": 600.0}
    # the hash covers the adapter and the preset, not the server: another endpoint or served name is the same pipeline
    assert provenance.functional_block(block)["params"]["backend"] == adapter
    other = PageRecognizer(Chat(chat_model("lightonocr-2-1b"), "http://elsewhere:9000/v1", served_name="n"))
    assert provenance.functional_block(other) == provenance.functional_block(block)


def test_engines_carry_presets(monkeypatch):
    import linecaster.catalog.registry as registry

    class R:
        ref, sha256 = "rec@4", SHA

    monkeypatch.setattr(registry, "engine_spec", lambda ref, installed=True, served=False: ("pkg:Rec", {"weights": {"model": "m"}}, R()))
    models = [{"name": "recognition", "preset": "rec"}, {"name": "layout", "spec": "pkg:Layout"}]
    a = _args("images", "out")
    backends, servers = run.engines(a, models, "recipe.py")
    rec = backends["recognition"]
    assert (rec.spec, rec.kwargs) == ("pkg:Rec", {"weights": {"model": "m"}})
    assert (rec.preset, rec.preset_sha256) == ("rec@4", SHA)
    assert backends["layout"].preset is None and servers == []
    assert run.model_args(run.preset_models(models))[:2] == ["--preset", "recognition=rec@4"]


def test_redact_argv():
    assert provenance.redact_argv(["x", "--env", "A=1", "--env=B=2", "--on", "local"]) == [
        "x", "--env", "A=<redacted>", "--env=B=<redacted>", "--on", "local"]


def test_a_script_outside_a_checkout_is_recorded_by_its_name(tmp_path: Path):
    """A recipe script run from its URL is uv's temporary copy: the record names it ``recipes/<id>.py``. In a
    checkout, its path there wins."""
    from linecaster.runtime.provenance import script_entry

    copy = tmp_path / "squiddleAb12Cd.py"
    copy.write_text("print()\n")
    assert script_entry(str(copy))["path"] == "squiddleAb12Cd.py"
    named = script_entry(str(copy), "recipes/squiddle.py")
    assert named["path"] == "recipes/squiddle.py" and named["sha256"].startswith("sha256:")
    assert script_entry(__file__, "recipes/squiddle.py")["path"].endswith("tests/runtime/test_provenance.py")


def test_each_page_is_decoded_once_for_all_the_blocks_that_need_its_image(tmp_path: Path):
    """A line detector and a line recognizer both take the page's pixels: the file is decoded once (``decodes``), the
    second block gets the same read-only array."""
    from linecaster.blocks.base import page as base_page
    from linecaster.blocks.lines.detector import LineDetector
    from linecaster.blocks.readers.images import ImageFolderReader
    from linecaster.blocks.recognition.recognizers import LineRecognizer

    folder = Path(_images(tmp_path / "images"))
    for name, shade in (("p2.png", "gray"), ("p3.png", "black")):        # three files (pages are kept by content)
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), shade).save(buf, format="PNG")
        (folder / name).write_bytes(buf.getvalue())
    seen = []

    class Seeing(StampModel):
        def __call__(self, image, t, **params):
            seen.append(image)
            return super().__call__(image, t, **params)

    import sys

    sys.modules[__name__].Seeing = Seeing
    from linecaster.images import pixels

    pixels.clear()                       # pages are kept by content: an earlier test in this process may hold these
    before = base_page.decodes()
    lines, recognizer = LineDetector(InProcess("test_provenance:OneLineModel")), LineRecognizer(InProcess(f"{__name__}:Seeing"))
    docs = list(recognizer.run(lines.run(ImageFolderReader(str(folder)).run())))
    assert len(docs) == 3 and base_page.decodes() - before == 3                 # one decode per page, not per block
    assert lines.stats["image_decoded"].total == 3 and recognizer.stats["image_shared"].total == 3
    assert all(not a.flags.writeable for a in seen) and seen[0].shape == (30, 40, 3)
    for doc in docs:                     # each step names the decoder of the pixels it read (no GPU decodes a PNG)
        steps = base_page.page_of(doc).transcriptions["ocr_new"].annotators
        assert steps and all(s.measurements["decoder"].startswith("Pillow ") for s in steps)
    assert lines.stats["cpu_decoded"].total == 3 and recognizer.stats["cpu_decoded"].total == 0       # shared


def test_the_builder_sets_every_model_blocks_image_decode():
    from linecaster.blocks.lines.detector import LineDetector
    from linecaster.blocks.readers.images import ImageFolderReader
    from linecaster.blocks.recognition.recognizers import LineRecognizer
    from linecaster.runtime.builder import build

    blocks = [ImageFolderReader("images"), LineDetector(InProcess("test_provenance:OneLineModel")),
              LineRecognizer(InProcess("test_provenance:StampModel"))]
    assert [b.image_decode for b in blocks[1:]] == ["auto", "auto"]
    build(blocks, image_decode="cpu")
    assert [b.image_decode for b in blocks[1:]] == ["cpu", "cpu"]
