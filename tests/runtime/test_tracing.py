"""Tracing (``linecaster.tracing``), on CPU with fake engines: sampling by page id, failed unsampled pages exported
and the others not, explicit parents for interleaved pages, the trace context reaching ``linecaster serve`` (a real
server process) and its spans joining the trace, one file per rank closed on failure, no OTLP export without the
``OTEL_*`` variables, log records with trace ids, fetch spans, and ``linecaster traces``."""
import gzip
import io
import json
import pickle
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from loguru import logger
from PIL import Image

from linecaster.backends import InProcess, Served
from linecaster.blocks.base.page import PageBlock, new_page_document
from linecaster.blocks.lines import LineDetector
from linecaster.blocks.readers import ImageFolderReader, PageRecordReader
from linecaster.blocks.servers import ChatModelServer, ModelServer
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.errors import ServerError
from linecaster.runtime.builder import build, run_plan
from linecaster.tracing import (DEFAULT_SAMPLE, PAGE_ID, TRACE_KEY, Tracing, otlp_configured, sampled,
                                task_provider, resource)
from linecaster.tracing.report import read_spans, render, summarize

OTEL_VARS = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_TRACES_EXPORTER")


@pytest.fixture(autouse=True)
def no_otlp(monkeypatch):
    for k in OTEL_VARS:
        monkeypatch.delenv(k, raising=False)


class FailsOn(PageBlock):
    """Fails on the pages named in ``ids`` (a per-page failure); logs every page it sees."""

    def __init__(self, ids=()):
        self.name = "fails on"
        super().__init__()
        self.ids = set(ids)

    def process_page(self, doc, page):
        logger.info("looking at {page_id}", page_id=doc.id)
        if doc.id in self.ids:
            raise RuntimeError("boom")
        return page


class Breaks(PageBlock):
    """Fails the task (a server error) on its second page."""

    def __init__(self):
        self.name = "breaks"
        super().__init__()
        self.seen = 0

    def process_page(self, doc, page):
        self.seen += 1
        if self.seen == 2:
            raise ServerError("the server is gone")
        return page


class Interleaves(PageBlock):
    """A stream block that takes every page in, builds their requests in order and finishes them in reverse, as a
    served window does when later requests come back first."""

    shape = "stream"

    def __init__(self):
        self.name = "interleaves"
        super().__init__()
        self.carriers = {}

    def run(self, data, rank=0, world_size=1):
        docs = list(data)
        for d in docs:
            self.notify(d, "prepare")
            carrier = {}
            self.notify(d, "request", carrier=carrier)
            self.carriers[d.id] = carrier.get("traceparent")
        for d in reversed(docs):
            self.notify(d, "done", prompt_tokens=3, completion_tokens=5, finish_reason="stop")
            yield d


def png(w: int, h: int = 30) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def images(folder: Path, n: int) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (folder / f"p{i:03d}.png").write_bytes(png(40 + i))
    return str(folder)


def spans_of(out: Path) -> list[dict]:
    return read_spans(str(out))


def by_name(spans, name):
    return [s for s in spans if s["name"] == name]


# ------------------------------------------------------------------------------------------------ sampling

def test_sampling_is_deterministic_and_the_share_right():
    ids = [f"item{i // 300}_{i % 300:04d}" for i in range(100_000)]
    picked = [i for i in ids if sampled(i, 0.01)]
    assert picked == [i for i in ids if sampled(i, 0.01)]               # the same pages every time
    assert 0.009 < len(picked) / len(ids) < 0.011
    assert 0.095 < sum(sampled(i, 0.1) for i in ids) / len(ids) < 0.105
    assert set(picked) <= {i for i in ids if sampled(i, 0.1)}           # a larger sample contains a smaller one
    assert not any(sampled(i, 0) for i in ids[:1000]) and all(sampled(i, 1) for i in ids[:1000])
    assert DEFAULT_SAMPLE == 0.01


def test_failed_unsampled_pages_are_exported_and_the_others_not(tmp_path: Path):
    src = images(tmp_path / "images", 20)
    out = tmp_path / "out"
    plan = build([ImageFolderReader(src), FailsOn({"p007"}), PageJsonlWriter(str(out / "pages"))],
                 run_folder=str(out), trace_sample=0)
    docs = run_plan(plan)
    assert len(docs) == 20
    spans = spans_of(out)
    pages = by_name(spans, "linecaster.page")
    assert [p["attrs"][PAGE_ID] for p in pages] == ["p007"] and pages[0]["error"]
    failed = {s["trace"] for s in spans if s["trace"] == pages[0]["trace"]}
    assert len(failed) == 1
    blocks = [s for s in spans if s["name"] == "linecaster.block" and s["trace"] == pages[0]["trace"]]
    assert {b["attrs"]["linecaster.block"] for b in blocks} >= {"FailsOn", "PageJsonlWriter"}
    assert [b for b in blocks if b["attrs"]["linecaster.block"] == "FailsOn"][0]["attrs"][
        "linecaster.error.type"] == "RuntimeError"
    assert len(by_name(spans, "linecaster.task")) == 1                  # task spans always
    # no page record carries a trace id: none was sampled
    rows = [json.loads(x) for f in (out / "pages").glob("*.jsonl.gz") for x in gzip.open(f, "rt")]
    assert not any("trace_id" in r["page"]["metadata"] for r in rows)
    assert all(TRACE_KEY in d.metadata for d in docs)
    tracing = plan.stages[0].observers.observers[-1]
    assert tracing.provider is None                                      # shut down at the task's end


def test_sampled_pages_carry_their_trace_id(tmp_path: Path):
    src = images(tmp_path / "images", 5)
    out = tmp_path / "out"
    run_plan(build([ImageFolderReader(src), PageJsonlWriter(str(out / "pages"))], run_folder=str(out), trace_sample=1))
    rows = {json.loads(x)["id"]: json.loads(x) for f in (out / "pages").glob("*.jsonl.gz") for x in gzip.open(f, "rt")}
    traces = {s["attrs"][PAGE_ID]: s["trace"] for s in by_name(spans_of(out), "linecaster.page")}
    assert sorted(traces) == sorted(rows) and all(rows[p]["page"]["metadata"]["trace_id"] == traces[p] for p in rows)


def test_interleaved_pages_have_the_right_parents(tmp_path: Path):
    src = images(tmp_path / "images", 4)
    out = tmp_path / "out"
    block = Interleaves()
    docs = run_plan(build([ImageFolderReader(src), block, PageJsonlWriter(str(out / "pages"))], run_folder=str(out),
                          trace_sample=1))
    assert [d.id for d in docs] == ["p003", "p002", "p001", "p000"]
    spans = spans_of(out)
    ids = {(s["trace"], s["span"]): s for s in spans}
    roots = {s["trace"]: s for s in by_name(spans, "linecaster.page")}
    assert len(roots) == 4
    for req in by_name(spans, "linecaster.request"):
        parent = ids[(req["trace"], req["parent"])]
        assert parent["name"] == "linecaster.block" and parent["attrs"]["linecaster.block"] == "Interleaves"
        assert parent["attrs"][PAGE_ID] == roots[req["trace"]]["attrs"][PAGE_ID]
        assert ids[(parent["trace"], parent["parent"])] is roots[req["trace"]]
        assert req["attrs"]["linecaster.tokens.completion"] == 5 and req["attrs"]["linecaster.finish_reason"] == "stop"
        # the carrier got this request span's context
        page = roots[req["trace"]]["attrs"][PAGE_ID]
        assert block.carriers[page].split("-")[1:3] == [req["trace"], req["span"]]
    for prep in by_name(spans, "linecaster.request.prepare"):
        assert ids[(prep["trace"], prep["parent"])]["attrs"]["linecaster.block"] == "Interleaves"
    # every block span of a page hangs off that page's root
    for b in by_name(spans, "linecaster.block"):
        assert b["parent"] == roots[b["trace"]]["span"]
    assert all(r["start"] <= b["start"] and b["end"] <= r["end"] + 1e-6
               for b in by_name(spans, "linecaster.block") for r in [roots[b["trace"]]])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_trace_context_reaches_linecaster_serve_and_its_spans_join(tmp_path: Path, monkeypatch):
    """A real ``linecaster serve`` process started by ``ModelServer`` in the task, with a fake engine."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent) + ":" + __import__("os").environ.get("PYTHONPATH", ""))
    src = images(tmp_path / "images", 3)
    out = tmp_path / "out"
    port = _free_port()
    endpoint = f"http://127.0.0.1:{port}/v1"
    server = ModelServer([{"name": "lines", "spec": "linecaster.testing:FakeLineEngine", "kwargs": {}}], port=port,
                         python=sys.executable, boot_timeout=120)
    plan = build([ImageFolderReader(src), LineDetector(Served(endpoint, model="lines", max_window=4)),
                  PageJsonlWriter(str(out / "pages")), server], run_folder=str(out), trace_sample=1)
    plan.check()
    docs = run_plan(plan)
    assert len(docs) == 3 and not any(d.metadata.get("errors") for d in docs)
    assert sorted(p.name for p in (out / "traces").iterdir()) == ["00000.jsonl.gz", "00000.serve.jsonl.gz"]
    spans = spans_of(out)
    ids = {(s["trace"], s["span"]): s for s in spans}
    requests = by_name(spans, "linecaster.request")
    assert len(requests) == 3
    for kind in ("queue", "decode", "model"):
        served = by_name(spans, f"linecaster.serve.{kind}")
        assert len(served) == 3
        for s in served:
            parent = ids[(s["trace"], s["parent"])]
            assert parent["name"] == "linecaster.request"         # the server's spans hang off the request
            assert s["resource"]["linecaster.process"] == "serve" and s["resource"]["linecaster.task"] == 0
    model = by_name(spans, "linecaster.serve.model")[0]
    assert model["attrs"]["linecaster.lines"] == 2 and model["attrs"]["linecaster.model"] == "lines"
    assert len(by_name(spans, "linecaster.server.start")) == 1
    report = summarize(spans)
    served = report["blocks"]["lines (served http://127.0.0.1:%d/v1 (lines))" % port]["served"]
    assert set(served) == {"prepare", "request", "queue", "decode", "model"}


def test_files_per_rank_closed_when_the_task_fails(tmp_path: Path):
    src = images(tmp_path / "images", 6)
    out = tmp_path / "out"
    plan = build([ImageFolderReader(src), PageJsonlWriter(str(out / "pages"))], run_folder=str(out), tasks=2,
                 trace_sample=1)
    for rank in (0, 1):
        data = None
        for step in plan.stages[0].pipeline:
            data = step(data, rank, 2)
        list(data)
    assert sorted(p.name for p in (out / "traces").iterdir()) == ["00000.jsonl.gz", "00001.jsonl.gz"]
    pages = {s["resource"]["linecaster.task"]: [] for s in spans_of(out)}
    for s in by_name(spans_of(out), "linecaster.page"):
        pages[s["resource"]["linecaster.task"]].append(s["attrs"][PAGE_ID])
    assert sorted(pages[0]) == ["p000", "p002", "p004"] and sorted(pages[1]) == ["p001", "p003", "p005"]
    # a failing task: its file is complete, with the task span marked failed and the unfinished page
    out2 = tmp_path / "out2"
    plan = build([ImageFolderReader(src), Breaks(), PageJsonlWriter(str(out2 / "pages"))], run_folder=str(out2),
                 trace_sample=1)
    with pytest.raises(ServerError):
        run_plan(plan)
    raw = (out2 / "traces" / "00000.jsonl.gz").read_bytes()
    gzip.decompress(raw)                                              # a complete gzip stream: closed
    spans = spans_of(out2)
    task = by_name(spans, "linecaster.task")[0]
    assert task["error"] and task["attrs"]["linecaster.error.type"] == "ServerError"
    assert any(s["attrs"].get("linecaster.unfinished") for s in by_name(spans, "linecaster.page"))


def test_no_otlp_without_the_variables(tmp_path: Path, monkeypatch):
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp

    made = []

    class Recording:
        def __init__(self, *a, **kw):
            made.append(kw)

        def export(self, spans):
            from opentelemetry.sdk.trace.export import SpanExportResult

            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=30000):
            return True

    monkeypatch.setattr(otlp, "OTLPSpanExporter", Recording)
    assert not otlp_configured()
    src = images(tmp_path / "images", 2)
    out = tmp_path / "out"
    run_plan(build([ImageFolderReader(src), PageJsonlWriter(str(out / "pages"))], run_folder=str(out)))
    assert made == [] and [p.name for p in (out / "traces").iterdir()] == ["00000.jsonl.gz"]
    # nothing at all without a run folder or OTLP: no observers, no boundaries
    p = build([ImageFolderReader(src), PageJsonlWriter(str(out / "p2"))])
    assert p.stages[0].observers is None
    # with the standard variable: the OTLP exporter too
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    assert otlp_configured()
    provider, buffer = task_provider(resource(), path=None)
    assert len(made) == 1 and len(buffer.inner) == 1
    provider.shutdown()
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    assert not otlp_configured()


def test_vllm_traces_to_otlp_when_configured(monkeypatch):
    from linecaster.adapters import chat_model

    block = ChatModelServer(chat_model("lightonocr-2-1b"))
    assert "--otlp-traces-endpoint" not in block.launch_command()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    cmd = block.launch_command()
    assert cmd[cmd.index("--otlp-traces-endpoint") + 1] == "http://collector:4318/v1/traces"
    assert "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf" in cmd


def test_log_records_carry_trace_ids(tmp_path: Path):
    src = images(tmp_path / "images", 3)
    out = tmp_path / "out"
    records = []
    sink = logger.add(lambda m: records.append(m.record), level="INFO")
    try:
        run_plan(build([ImageFolderReader(src), FailsOn(), PageJsonlWriter(str(out / "pages"))], run_folder=str(out),
                       trace_sample=1))
    finally:
        logger.remove(sink)
    traces = {s["attrs"][PAGE_ID]: s["trace"] for s in by_name(spans_of(out), "linecaster.page")}
    seen = {r["extra"]["page_id"]: r["extra"].get("trace_id") for r in records if r["message"].startswith("looking")}
    assert seen == traces
    task = by_name(spans_of(out), "linecaster.task")[0]
    later = [r for r in records if r["message"].startswith("looking")]
    assert all(len(r["extra"]["span_id"]) == 16 for r in later)
    assert task["trace"] not in seen.values()


def test_the_tracing_observer_pickles_without_state(tmp_path: Path):
    t = Tracing(str(tmp_path), 0.5)
    t.on_task_start(0, 1)
    try:
        copy = pickle.loads(pickle.dumps(t))
    finally:
        t.on_task_end()
    assert copy.provider is None and copy.sample == 0.5 and copy.run_folder == str(tmp_path)
    assert copy.environment()["LINECASTER_TRACES"].endswith("traces/00000.serve.jsonl.gz")
    with pytest.raises(Exception):
        Tracing(str(tmp_path), 1.5)
    assert build([ImageFolderReader("x")], run_folder=str(tmp_path), trace_sample=2).problems == [
        "--trace-sample is a share from 0 to 1, not 2"]


class _Images(BaseHTTPRequestHandler):
    def do_GET(self):
        body = png(41)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_fetches_become_spans_of_their_page(tmp_path: Path):
    pytest.importorskip("pybookget")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Images)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/p.png"
        doc = new_page_document("p1", png(41), uri=url)
        records = tmp_path / "records"
        records.mkdir()
        row = {"schema": "linecaster.page/1", "id": "p1", "text": "", "page": doc.metadata["page"]}
        with gzip.open(records / "00000.jsonl.gz", "wt") as f:
            f.write(json.dumps(row) + "\n")
        out = tmp_path / "out"
        run_plan(build([PageRecordReader(str(records)), PageJsonlWriter(str(out / "pages"))], run_folder=str(out),
                       trace_sample=1))
    finally:
        httpd.shutdown()
    spans = spans_of(out)
    fetch = by_name(spans, "linecaster.http.fetch")
    page = by_name(spans, "linecaster.page")[0]
    assert len(fetch) == 1 and fetch[0]["parent"] == page["span"] and fetch[0]["trace"] == page["trace"]
    a = fetch[0]["attrs"]
    assert a["linecaster.http.host"] == "127.0.0.1" and a["linecaster.http.status"] == 200
    assert a["linecaster.http.attempts"] == 1 and a["linecaster.http.retries"] == 0
    assert page["start"] <= fetch[0]["start"]
    files = by_name(spans, "linecaster.reader.file")
    assert len(files) == 1 and files[0]["attrs"]["linecaster.pages"] == 1
    assert len(by_name(spans, "linecaster.writer.flush")) == 1


def test_the_traces_command(tmp_path: Path, capsys):
    from linecaster.cli import main

    src = images(tmp_path / "images", 8)
    out = tmp_path / "out"
    run_plan(build([ImageFolderReader(src), FailsOn({"p003"}), LineDetector(InProcess("linecaster.testing:FakeLineEngine")),
                    PageJsonlWriter(str(out / "pages"))], run_folder=str(out), trace_sample=1))
    main(["traces", str(out), "--slowest", "3"])
    text = capsys.readouterr().out
    assert "fails on" in text and "lines (in-process)" in text and "slowest units" in text
    assert "gaps (time a block had no page" in text and "task 0:" in text and "warm-up" in text
    main(["traces", str(out), "--json", "--by", "task"])
    report = json.loads(capsys.readouterr().out)
    assert report["units"] == {"traced": 8, "failed": 1} and list(report["blocks"]) == ["task 0"]
    assert report["blocks"]["task 0"]["seconds"]["n"] == 8 * 4      # the blocks and the rejects writer
    assert len(report["slowest"]) == 8 and report["per_task"]["task 0"]["sample"] == 1
    r = summarize(read_spans(str(out)), slowest=2)
    assert r["blocks"]["fails on"]["errors"] == 1 and len(r["slowest"]) == 2
    assert render(r).splitlines()[0].endswith("(1 failed)")
    with pytest.raises(SystemExit):
        main(["traces", str(tmp_path / "nothing")])


def test_the_buffer_holds_only_the_pages_in_flight():
    from opentelemetry import trace
    from opentelemetry.context import Context
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    from linecaster.tracing import UnitSampler
    from linecaster.tracing.export import PageBuffer

    exported = InMemorySpanExporter()
    buffer = PageBuffer([SimpleSpanProcessor(exported)])
    provider = TracerProvider(sampler=UnitSampler(0), shutdown_on_exit=False)
    provider.add_span_processor(buffer)
    tracer = provider.get_tracer("test")
    open_pages = []
    for i in range(50):
        root = tracer.start_span("linecaster.page", context=Context(), attributes={PAGE_ID: f"p{i}"})
        for _ in range(3):
            tracer.start_span("linecaster.block", context=trace.set_span_in_context(root)).end()
        open_pages.append(root)
        if len(open_pages) > 4:                       # five pages in flight at most
            done = open_pages.pop(0)
            if i == 20:
                done.set_status(StatusCode.ERROR)
            done.end()
        assert buffer.held() <= 5 * 3
    for root in open_pages:
        root.end()
    assert buffer.held() == 0
    names = [s.name for s in exported.get_finished_spans()]
    assert names == ["linecaster.block"] * 3 + ["linecaster.page"] and buffer.exported_failed == 1
    provider.shutdown()


def test_a_second_stop_signal_does_not_cut_the_servers_end_short():
    from aiohttp import web

    from linecaster.serve import app

    app._STOPPING.clear()
    try:
        with pytest.raises(web.GracefulExit):
            app._raise_graceful_exit()
        assert app._raise_graceful_exit() is None          # the second one (from uv run, passing it on) is ignored
    finally:
        app._STOPPING.clear()


def test_trace_ids_follow_the_run_and_the_page(tmp_path):
    """A sampled page gets the same trace id in a rerun of the same run (its page record stays the same), another
    run gives it another."""
    def trace_id(run_folder: Path) -> str:
        t = Tracing(str(run_folder), sample=1.0, run="r1" if run_folder.name != "other" else "r2")
        t.on_task_start(0, 1)
        doc = new_page_document("b_0001", png(40), uri="b_0001.png", item_id="b")
        t.on_enter(_Noop(), doc)
        t.on_leave(doc)
        t.on_task_end()
        return doc.metadata["page"]["metadata"]["trace_id"]

    first, again, other = trace_id(tmp_path / "a"), trace_id(tmp_path / "b"), trace_id(tmp_path / "other")
    assert first == again != other


def test_a_dropped_page_is_not_held_in_memory(tmp_path):
    """A page a per-unit block drops never comes out of it: when the next page goes in, the dropped one's trace ends
    (unfinished) and nothing of it stays with the observer; documents are never held."""
    t = Tracing(str(tmp_path), sample=1.0, run="r")
    t.on_task_start(0, 1)
    block = _Noop()
    dropped = new_page_document("b_0001", png(40), uri="b_0001.png", item_id="b")
    t.on_enter(block, dropped)                      # the block drops it: no on_exit
    kept = new_page_document("b_0002", png(40), uri="b_0002.png", item_id="b")
    t.on_enter(block, kept)
    assert [u.id for u in t._units.values()] == ["b_0002"]
    assert not any(getattr(v, "doc", None) for v in t._units.values())   # no document is held
    t.on_exit(block, kept)
    t.on_leave(kept)
    t.on_task_end()


class _Noop(PageBlock):
    name = "noop"

    def process_page(self, doc, page):
        return page
