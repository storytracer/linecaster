"""`linecaster serve` with served blocks, end to end in one process: a step that reads only some regions sends
no image for a page without them, a malformed answer is that page's error, and saturate's readiness check
passes once the models are loaded."""
import asyncio
import io
import socket
import threading

import pytest
from PIL import Image

from linecaster.backends import Served
from linecaster.blocks.base import new_page_document, page_of, set_page
from linecaster.blocks.models import TablesStep
from linecaster.page import Page
from linecaster.transcription import ModelInfo, Region, Transcription

SEEN: dict = {}


class FakeTables:
    """A tables engine model that notes whether it got an image; for a page whose region is labelled ``bad``
    it answers something that is not a transcription."""

    step, name = "tables", "fake-tables"

    def load(self):
        pass

    def __call__(self, image, transcription, **params):
        SEEN[transcription.regions[0].id] = image is not None
        if transcription.regions[0].label == "bad":
            class Bad:
                model = []

                def model_dump(self, mode="json"):
                    return {"lines": "not a list"}
            return Bad()
        transcription.model.append(ModelInfo(step=self.step, name=self.name))
        return transcription


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buf, format="PNG")
    return buf.getvalue()


def page(page_id: str, label: str):
    doc = new_page_document(page_id, png())
    box = [0.0, 0.0, 10.0, 5.0]
    region = Region(id=f"{page_id}-r", label=label, polygon=[[0, 0], [10, 0], [10, 5], [0, 5]], bbox=box)
    p = page_of(doc)
    p.transcriptions["ocr"] = Transcription(regions=[region])
    set_page(doc, p)
    return doc


def serve_in_thread(port: int):
    from aiohttp import web

    from linecaster.serve.app import Hosted, build_app

    loop = asyncio.new_event_loop()
    app = build_app([Hosted("tables", f"{__name__}:FakeTables", {})])
    runner = web.AppRunner(app)

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    return loop, runner


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_served_step_sends_images_only_where_needed_and_fails_one_page():
    from saturate.engine import wait_for_health

    port = free_port()
    loop, runner = serve_in_thread(port)
    endpoint = f"http://127.0.0.1:{port}/v1"
    try:
        # as linecaster.serve.engine checks readiness
        wait_for_health(endpoint, 60, route="/linecaster/ready", payload={}, accept=lambda r: r.status_code == 404,
                        poll_interval=0.1)
        step = TablesStep(Served(endpoint, model="tables"))
        out = {d.id: d for d in step.run(iter([page("with", "table"), page("without", "text"), page("x", "bad")]))}
        assert SEEN == {"with-r": True, "without-r": False, "x-r": False}
        for pid in ("with", "without"):            # both pages carry the step's record, image or not
            t: Transcription = Page.model_validate(out[pid].metadata["page"]).transcriptions["ocr"]
            assert [m.name for m in t.model] == ["fake-tables"] and not out[pid].metadata.get("errors")
        assert out["x"].metadata["errors"][0]["step"] == "tables"     # the malformed answer: this page only
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def test_serve_blocks_keep_their_server_for_the_next_task(monkeypatch):
    """With keep_running a Job's later tasks reuse the server (started once, replaced if it died); without it
    each task starts and stops its own."""
    import linecaster.serve as serve_pkg
    from linecaster.blocks import serve
    from linecaster.blocks.serve import ServeModels

    events = []

    class FakeEngine:
        def __init__(self):
            self.proc = type("P", (), {"alive": True, "poll": lambda s: None if s.alive else 1})()

        def __enter__(self):
            events.append("up")
            return self

        def __exit__(self, *exc):
            events.append("down")

    monkeypatch.setattr(serve_pkg, "engine", lambda *a, **k: FakeEngine())
    monkeypatch.setattr(serve, "_SERVERS", {})
    kept = ServeModels([{"name": "x", "spec": "pkg:X"}], keep_running=True)
    for _ in range(3):
        assert list(kept.run(iter([1, 2]))) == [1, 2]
    assert events == ["up"]                                   # one server for three tasks
    next(iter(serve._SERVERS.values())).proc.alive = False    # it died between tasks: replaced
    list(kept.run(iter([])))
    assert events == ["up", "down", "up"]
    serve._stop_servers()
    assert events[-1] == "down" and serve._SERVERS == {}
    events.clear()
    for _ in range(2):
        list(ServeModels([{"name": "x", "spec": "pkg:X"}]).run(iter([1])))
    assert events == ["up", "down", "up", "down"]             # default: per task


def test_gpu_jobs_take_a_multiple_of_their_gpus():
    from linecaster.jobs import GPUJobsExecutor

    with pytest.raises(ValueError, match="multiple of gpus"):
        GPUJobsExecutor([], tasks=8, gpus=4, tasks_per_job=6, logging_dir="hf://buckets/x/y/logs")
