"""`linecaster serve` with served blocks, end to end in one process: a step that reads only some regions sends
no image for a page without them, a malformed answer is that page's error, and saturate's readiness check
passes once the models are loaded."""
import asyncio
import io
import socket
import threading

from PIL import Image

from linecaster.backends import Served
from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.recognition.recognizers import TableRecognizer
from linecaster.data import Region, Transcription
from linecaster.data.page import Page
from linecaster.testing import FakeTableEngine

SEEN: dict = {}


class FakeTables(FakeTableEngine):
    """The fake tables engine, noting whether it got an image; for a page whose region is labeled ``bad`` it
    answers something that is not a transcription."""

    def __call__(self, image, transcription, **params):
        SEEN[transcription.regions[0].id] = image is not None
        if transcription.regions[0].label == "bad":
            class Bad:
                steps = []

                def model_dump(self, mode="json"):
                    return {"lines": "not a list"}
            return Bad()
        return super().__call__(image, transcription, **params)


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buf, format="PNG")
    return buf.getvalue()


def page(page_id: str, label: str):
    doc = new_page_document(page_id, png())
    box = [0.0, 0.0, 10.0, 5.0]
    region = Region(id=f"{page_id}-r", label=label, polygon=[[0, 0], [10, 0], [10, 5], [0, 5]], bbox=box)
    p = page_of(doc)
    p.transcriptions["ocr_new"] = Transcription(regions=[region])
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
        step = TableRecognizer(Served(endpoint, model="tables"))
        out = {d.id: d for d in step.run(iter([page("with", "table"), page("without", "text"), page("x", "bad")]))}
        assert SEEN == {"with-r": True, "without-r": False, "x-r": False}
        for pid in ("with", "without"):            # both pages carry the step's record, image or not
            t: Transcription = Page.model_validate(out[pid].metadata["page"]).transcriptions["ocr_new"]
            assert [(m.name, m.engine) for m in t.steps] == [("fake-tables", "fake.tables.v1")] and not out[pid].metadata.get("errors")
        assert out["x"].metadata["errors"][0]["step"] == "tables"     # the malformed answer: this page only
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def test_a_served_block_passes_a_failed_page_on_at_once():
    """A page an earlier block failed on leaves a served block before the next page is read, not when the stream
    ends."""
    from saturate.engine import wait_for_health

    port = free_port()
    loop, runner = serve_in_thread(port)
    endpoint = f"http://127.0.0.1:{port}/v1"
    out_first = threading.Event()
    failed = page("failed", "table")
    failed.metadata["errors"] = [{"block": "X", "type": "RuntimeError", "error": "earlier"}]

    def pages():
        yield failed
        assert out_first.wait(10), "the failed page was held back"
        yield page("next", "table")

    try:
        wait_for_health(endpoint, 60, route="/linecaster/ready", payload={}, accept=lambda r: r.status_code == 404,
                        poll_interval=0.1)
        step = TableRecognizer(Served(endpoint, model="tables"))
        seen = []
        for d in step.run(pages()):
            seen.append(d.id)
            out_first.set()
        assert seen == ["failed", "next"] and step.stats["skipped_after_error"].total == 1
        assert not page_of(failed).transcriptions["ocr_new"].steps    # the step never read it
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
