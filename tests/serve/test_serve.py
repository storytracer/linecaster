"""`linecaster serve` with served blocks, end to end in one process: a step that reads only some regions sends
no image for a page without them, a malformed answer is that page's error, and saturate's readiness check
passes once the models are loaded; a client refuses a server that speaks another transcription format."""
import asyncio
import io
import socket
import threading

from PIL import Image

from linecaster.backends import Served
from linecaster.blocks.base.page import new_page_document, page_of, set_page
from linecaster.blocks.recognition.recognizers import TableRecognizer
from linecaster.data import Annotator, Transcription
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
                annotators = []

                def model_dump(self, mode="json", **kwargs):
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
    t = Transcription()
    a = t.add_annotator(Annotator(step="layout", name="test"))
    t.add_region(a, f"{page_id}-r", box, [[0, 0], [10, 0], [10, 5], [0, 5]], label=label, role=label)
    p = page_of(doc)
    p.transcriptions["ocr_new"] = t
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
            assert [(m.name, m.engine) for m in t.annotators] == [("test", None), ("fake-tables", "fake.tables.v1")]
            assert not out[pid].metadata.get("errors")
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
        assert len(page_of(failed).transcriptions["ocr_new"].annotators) == 1    # the step never read it
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def test_the_server_decodes_as_the_block_asks_and_the_step_names_its_decoder(monkeypatch):
    """A served block sends its ``image_decode`` with the image; the server decodes the page that way and records the
    decoder on the step (measurement ``decoder``); a page sent without an image has none."""
    from saturate.engine import wait_for_health

    import linecaster.serve.app as app_module

    asked = []
    decode = app_module.decode_pixels

    def recording(raw, accel=None, device=None):
        asked.append(accel)
        return decode(raw, accel, device)

    monkeypatch.setattr(app_module, "decode_pixels", recording)
    port = free_port()
    loop, runner = serve_in_thread(port)
    endpoint = f"http://127.0.0.1:{port}/v1"
    try:
        wait_for_health(endpoint, 60, route="/linecaster/ready", payload={}, accept=lambda r: r.status_code == 404,
                        poll_interval=0.1)
        step = TableRecognizer(Served(endpoint, model="tables"))
        step.image_decode = "cpu"
        out = {d.id: d for d in step.run(iter([page("with", "table"), page("without", "text")]))}
        assert asked == ["cpu"]
        steps = {pid: Page.model_validate(out[pid].metadata["page"]).transcriptions["ocr_new"].annotators[-1]
                 for pid in out}
        assert steps["with"].measurements["decoder"].startswith("Pillow ")
        assert "decoder" not in steps["without"].measurements
        for pid, m in ((p, steps[p].measurements) for p in steps):    # the times of a served step
            assert m["request_seconds"] >= m["seconds"] >= 0 and m["queue_seconds"] >= 0, pid
        assert steps["with"].measurements["decode_seconds"] >= 0 and "decode_seconds" not in steps["without"].measurements
        assert step.stats["cpu_decoded"].total == 1            # counted from the server's record
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def test_the_server_decodes_a_page_once_for_all_its_steps():
    """Each served step sends the page's image with its request; the server keeps the decoded pages by their content,
    so two steps of one page decode it once (the second request is a copy of the bytes, not the same object)."""
    from saturate.engine import wait_for_health

    from linecaster.images import pixels

    pixels.clear()
    port = free_port()
    loop, runner = serve_in_thread(port)
    endpoint = f"http://127.0.0.1:{port}/v1"
    try:
        wait_for_health(endpoint, 60, route="/linecaster/ready", payload={}, accept=lambda r: r.status_code == 404,
                        poll_interval=0.1)
        first = TableRecognizer(Served(endpoint, model="tables"))
        second = TableRecognizer(Served(endpoint, model="tables"), transcription="ocr_new")
        docs = [page("p1", "table"), page("p2", "table")]
        for doc, w in zip(docs, (20, 30)):                                        # two images
            buf = io.BytesIO()
            Image.new("RGB", (w, 10), "white").save(buf, format="PNG")
            doc.media[0].media_bytes = buf.getvalue()
        before = pixels.decodes()
        out = list(second.run(first.run(iter(docs))))
        assert len(out) == 2 and pixels.decodes() - before == 2                   # two pages, four requests
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def test_a_client_checks_the_server_s_protocol():
    """``/health`` says the transcription format; ``Served.warm_up`` refuses a server that speaks another (or is too
    old to say), and passes one that does not answer yet or is no linecaster server."""
    import pytest
    from saturate.engine import wait_for_health

    from linecaster.backends.served import server_protocol
    from linecaster.errors import ServerError
    from linecaster.testing import fake_service

    port = free_port()
    loop, runner = serve_in_thread(port)
    endpoint = f"http://127.0.0.1:{port}/v1"
    try:
        wait_for_health(endpoint, 60, route="/linecaster/ready", payload={}, accept=lambda r: r.status_code == 404,
                        poll_interval=0.1)
        assert server_protocol(endpoint) == "linecaster.page/3"
        Served(endpoint, model="tables").warm_up()
    finally:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
    for health, refused in (({"status": "ok", "protocol": "linecaster.page/2"}, "speaks linecaster.page/2"),
                            ({"status": "ok"}, "speaks an older protocol")):
        with fake_service({"GET /health": lambda body, h=health: h}) as s:
            with pytest.raises(ServerError, match=refused):
                Served(f"{s.url}/v1", model="tables").warm_up()
    with fake_service({"GET /health": lambda body: {}}) as s:          # not linecaster serve: nothing to check
        Served(f"{s.url}/v1", model="tables").warm_up()
    Served(f"http://127.0.0.1:{free_port()}/v1", model="tables").warm_up()     # nothing there yet
