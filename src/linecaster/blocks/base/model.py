"""``ModelBlock``: the base of the model blocks, one block per step (layout, lines, recognition, ...), each with
its backend.

In-process, a block calls its model page by page. Served (``Served``, or ``Chat`` for a VLM), it streams its pages
through saturate: up to a window of requests in flight (adapted to the server's queue gauges and 429s), results
passed on as they finish, so CPU work upstream and downstream overlaps the server's GPU work. The streaming exists
once, here; a block says what its requests are (``_rows``: one per page by default, one per region for
``RegionRecognizer``), how each is built and parsed (``_request``, ``_parse``) and what a finished one completes
(``_done``). Either way a page's result depends only on the page (the server never mixes pages in a batch).
"""
from __future__ import annotations

import asyncio
import base64
import queue
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache

from ...backends import InProcess, Served
from ...data.page import Page
from ...data.transcription import Transcription
from ...errors import CatalogError, PipelineConfigError
from .contract import Contract, parts
from .page import (ErrorBudget, PageBlock, decode_rgb, error_entry, failed, image_bytes, page_of, record_error,
                   set_page, use_decoding)

_END = object()


class Passed:
    """A page a stream block passes through at once (an earlier block failed on it, or it has nothing to read),
    put on the results queue by the thread that reads the input; ``stat`` counts why."""

    __slots__ = ("doc", "stat")

    def __init__(self, doc, stat: str = "skipped_after_error"):
        self.doc, self.stat = doc, stat

#: what a step's block reads, besides the page image
STEP_READS = {"layout": (), "lines": (), "recognition": ("lines",), "tables": ("regions",), "formulas": ("regions",)}
#: what a step adds when neither its preset nor its engine says
STEP_PRODUCES = {"layout": ("regions", "reading_order"), "lines": ("lines",), "recognition": ("text",),
                 "tables": ("tables",), "formulas": ("formulas",)}


@lru_cache(maxsize=None)
def _preset_produces(ref: str) -> tuple[str, ...] | None:
    from ...catalog.registry import catalog, split_ref

    try:
        p = catalog().preset(split_ref(ref)[0])
    except (CatalogError, ValueError):     # unknown, or not an id@edition
        return None
    return tuple(p.capabilities.produces) or None


@lru_cache(maxsize=None)
def _engine_produces(spec: str) -> tuple[str, ...] | None:
    """The ``capabilities`` an engine class declares, read from its source where the repository has it (nothing
    imported), else from the class."""
    from ...catalog import code

    if code.REPO is not None and (code.REPO / "engines").is_dir():
        for e in code.engines().values():
            if e.target == spec:
                return tuple(e.capabilities.get("produces") or ()) or None
    try:
        from ...backends import resolve

        caps = getattr(resolve(spec), "capabilities", None) or {}
    except Exception:          # not installed here: the step's default
        return None
    return tuple(caps.get("produces") or ()) or None


def produces(backend, step: str, spec=None) -> tuple[str, ...]:
    """What a model block adds: its preset's ``capabilities.produces`` (the backend's or the chat ``spec``'s
    preset), else its engine's declared capabilities, else the step's default (``STEP_PRODUCES``)."""
    for ref in (getattr(spec, "preset", None), getattr(backend, "preset", None)):
        if ref and (found := _preset_produces(ref)):
            return found
    engine = getattr(backend, "spec", None) if not getattr(backend, "served", False) else getattr(backend, "engine", None)
    if isinstance(engine, str) and (found := _engine_produces(engine)):
        return found
    return STEP_PRODUCES.get(step, ())


def preset_backend(ref: str, step: str) -> InProcess:
    """The in-process backend of catalog preset ``ref`` (``id`` or ``id@edition``) for a block of ``step``."""
    from ...catalog.registry import catalog

    try:
        found = catalog().resolve(ref).content.get("step")
    except (CatalogError, ValueError) as e:
        raise PipelineConfigError(f"{step}: {e}") from None
    if found != step:
        raise PipelineConfigError(f"{step}: preset {ref!r} is a {found} preset")
    return InProcess.from_preset(ref)


def page_image(engine, data: bytes):
    """The page image as ``engine`` takes it: an RGB array, or the image file's bytes as the reader brought them for
    an engine whose ``image_input`` is ``"bytes"`` (a vendor's package that decodes the file itself)."""
    return data if getattr(engine, "image_input", "rgb") == "bytes" else decode_rgb(data)


class ModelBlock(PageBlock):
    """Runs one model step's engine on every page, through its backend, and adds its part to the transcription.

    In-process (``InProcess``) it is a per-unit transform: the engine loads in ``warm_up()``, before the first
    page, and is called with the page image (an RGB array, or the image file's bytes for an engine whose
    ``image_input`` is ``"bytes"``; none when the step reads only regions of a label the page lacks,
    ``region_label``) and the transcription so far. Served (``Served``, or ``Chat`` for a VLM) it is a
    stream transform: up to a window of requests in flight, passed on as they finish. Either way a page's result
    depends only on the page.

    Contract: reads the page image (recognition also ``lines``, tables and formulas ``regions``) and adds what its
    preset's ``capabilities.produces`` names, else its engine's declared capabilities, else the step's default
    (``STEP_PRODUCES``). The engine's ``Annotator`` gets the engine id, ``seconds``, ``datetime`` and, from a
    preset, the edition and its hash. A page an earlier block failed on passes through at once (stat
    ``skipped_after_error``); a failed request is the page's error (type ``ServerError``), counted against the
    error budget. Served stats: ``pages``, ``model_seconds``, token counts, ``finish_<reason>``,
    ``served_wall_seconds``.

    Args:
        backend: where the engine runs: ``InProcess``, ``Served``, or a catalog preset's ref (``id`` or
            ``id@edition``) for its engine in the pipeline's process; a preset of another step is refused
            (``PipelineConfigError``).
        transcription: the transcription the step reads and adds to.
        params: keyword arguments for every call of the engine (in-process) or sent with every request (served);
            ``None``: none.
        primary: the transcription whose text becomes the datatrove document's ``text``; ``None``:
            ``transcription``.
        skip_on_error: pass pages that carry errors through unprocessed.
        name: the block's name in stats and logs; ``None``: ``"<step> (<backend>)"``.

    Example:
        from linecaster.backends import InProcess, Served
        from linecaster.blocks.lines import LineDetector

        LineDetector("pp-ocrv6-medium-det@1")
        LineDetector(InProcess("linecaster_paddlex:PaddleLineEngine"))
        LineDetector(Served("http://127.0.0.1:8100/v1", model="lines"))
    """

    step = "model"
    role = "model"
    route: str | None = None       # the served route; None = linecaster serve's ``/linecaster/{step}``
    #: a step that reads only regions with this label gets no image for a page without one (``None``)
    region_label: str | None = None
    prepare_workers: int = 2       # threads building requests ahead of admission (image encoding)
    #: how page images are decoded (``auto``, ``gpu``, ``cpu``; ``linecaster.images.pixels``), here, in the server a
    #: served block reaches, or in a chat adapter: the builder sets it from ``--image-decode``. Operational: ``auto``
    #: depends on the machine anyway, and every step records its decoder (measurement ``decoder``)
    image_decode: str = "auto"
    results_windows: int = 4       # served: finished results held for the pipeline, in windows

    def __init__(self, backend: InProcess | Served | str, transcription: str = "ocr_new", params: dict | None = None,
                 primary: str | None = None, skip_on_error: bool = True, name: str | None = None):
        if isinstance(backend, str):         # a catalog preset: its engine in the pipeline's process
            backend = preset_backend(backend, self.step)
        self.name = name or f"{self.step} ({backend.describe()})"   # before the base __init__, which names the stats
        super().__init__()
        self.backend, self.transcription, self.params = backend, transcription, params or {}
        self.primary, self.skip_on_error = primary or transcription, skip_on_error

    def init_params(self) -> dict:
        """The parameters, ``backend`` as the backend it is (a preset given by name: the one it resolved to)."""
        out = super().init_params()
        out["backend"] = self.backend
        return out

    @property
    def shape(self) -> str:
        return "stream" if self.backend.served else "unit"

    def contract(self) -> Contract:
        reads = parts(("image", *STEP_READS.get(self.step, ())), self.transcription)
        return Contract(unit="page", role=self.role, reads=reads,
                        adds=parts(produces(self.backend, self.step), self.transcription))

    def warm_up(self) -> None:
        """The backend's: in-process the engine loads (not on the first page, so a page's measured ``seconds`` never
        include it); served the client's settings are resolved. The process's page decoding is set (``use_decoding``:
        ``image_decode``, the worker's GPU)."""
        use_decoding(self.image_decode)
        self.backend.warm_up()

    def _decoded(self, px, fresh: bool) -> None:
        """Counts a page image decoded here (``fresh``) or kept from a block before: ``image_decoded`` or
        ``image_shared``; for a fresh one also ``gpu_decoded`` or ``cpu_decoded``, and ``gpu_decode_refused`` /
        ``gpu_decode_errors`` where a GPU did not."""
        self.stat_update("image_decoded" if fresh else "image_shared")
        if fresh:
            self.stat_update("gpu_decoded" if px.gpu else "cpu_decoded")
            if px.fallback:
                self.stat_update("gpu_decode_refused" if px.fallback == "refused" else "gpu_decode_errors")

    def _placed(self, t: Transcription, doc) -> None:
        """A served result's transcription, finished for its page before it is stored (``PageRecognizer``: an
        adapter's boxes placed on the page image); default nothing."""

    @staticmethod
    def _record_request(t: Transcription, row: dict) -> None:
        """A served step's time from its request being built to its (last) answer (measurement ``request_seconds``)."""
        if t.annotators and "built" in row:
            t.annotators[-1].measurements["request_seconds"] = round(time.perf_counter() - row["built"], 4)

    @staticmethod
    def _record_decoder(t: Transcription, px) -> None:
        """The decoder of the pixels the step read, on its step record (measurement ``decoder``)."""
        if px is not None and t.annotators:
            t.annotators[-1].measurements.setdefault("decoder", px.decoder)

    def needs_image(self, t: Transcription) -> bool:
        return self.region_label is None or any(t.label(r.id) == self.region_label for r in t.regions)

    # ------------------------------------------------------------- in-process
    def process_page(self, doc, page: Page) -> Page:
        t = page.transcription(self.transcription)
        start, began = time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        engine = self.backend.model()
        image = px = None
        if self.needs_image(t):
            data = image_bytes(doc)
            if getattr(engine, "image_input", "rgb") == "bytes":
                image = data
            else:                                                       # decoded here, or a block before it did
                from ...images.pixels import decode_pixels, last_decode

                px = decode_pixels(data, self.image_decode)
                image = px.rgb
                self._decoded(*last_decode())
        out = engine(image, t, **self.params)
        self._record_decoder(out, px)
        if out.annotators:
            a = out.annotators[-1]
            a.engine = a.engine or getattr(engine, "engine_id", None)
            a.measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
            a.measurements.setdefault("datetime", began)     # ALTO processingDateTime, PAGE date
            if getattr(self.backend, "preset", None):        # built from a catalog preset
                a.preset, a.preset_sha256 = self.backend.preset, self.backend.preset_sha256
        page.transcriptions[self.transcription] = out
        return page

    def run(self, data, rank: int = 0, world_size: int = 1):
        """In-process ``PageBlock.run`` (pages one by one); served a stream. Either way a page an earlier block failed
        on passes through at once (``skip_on_error``)."""
        self.warm_up()
        if not self.backend.served:
            yield from super().run(data, rank, world_size)
        else:
            yield from self._run_served(data)

    def _passing(self, data, results: queue.Queue):
        """``data`` without the pages an earlier block failed on: those go straight onto ``results`` (``Passed``),
        in the thread that reads the input, so they leave the block at once."""
        for doc in data:
            if self.skip_on_error and failed(doc):
                results.put(Passed(doc))
            else:
                yield doc

    def _served_failure(self, doc, error, budget: ErrorBudget) -> None:
        """A page whose request failed (saturate's error for it): recorded, counted against the budget."""
        budget.failed(doc, record_error(doc, error_entry(self, error, "ServerError")))

    # ----------------------------------------------------------------- served
    def _rows(self, data, results: queue.Queue):
        """The requests, ``(key, row)`` with the page as ``row["doc"]``: one per page (a block reading parts of a
        page, e.g. its regions, yields one per part and gathers them in ``_done``)."""
        for doc in self._passing(data, results):
            yield doc.id, {"doc": doc}

    def _unit(self, row: dict) -> dict:
        """What names a request's part of its page for the observers (e.g. ``{"region": id}``); nothing for a page."""
        return {}

    def _request(self, row: dict) -> dict:
        doc = row["doc"]
        t = page_of(doc).transcription(self.transcription)
        image = self.needs_image(t)
        return {"model": self.backend.model, "page_id": doc.id,
                "image": base64.b64encode(image_bytes(doc)).decode("ascii") if image else None,
                **({"image_decode": self.image_decode} if image else {}),
                "transcription": t.model_dump(mode="json", by_alias=True, exclude_defaults=True), "params": self.params}

    @staticmethod
    def _parse(body: dict) -> dict:
        """Validated here, so a malformed response is that page's error (saturate), not the task's."""
        return {"transcription": Transcription.model_validate(body["transcription"]), "usage": body.get("usage") or {}}

    def _done(self, item, budget: ErrorBudget):
        """The pages one finished request completes (saturate's result for a row): here its page, with the
        transcription the server returned, or with the request's error recorded."""
        doc = item.row["doc"]
        self.stat_update("pages")
        budget.page()
        if item.error is not None:
            self.notify(doc, "done", error=item.error)
            self._served_failure(doc, item.error, budget)
            yield doc
            return
        page = page_of(doc)
        out = item.out["transcription"]
        self._record_decoder(out, item.row.get("decoded"))
        self._placed(out, doc)
        self._record_request(out, item.row)
        decoder = out.annotators[-1].measurements.get("decoder") if out.annotators and "decoded" not in item.row else None
        if decoder:                                # decoded by the server
            self.stat_update("gpu_decoded" if "(GPU" in decoder else "cpu_decoded")
        page.transcriptions[self.transcription] = out
        set_page(doc, page, self.primary)
        measured = out.annotators[-1].measurements if out.annotators else {}
        if "seconds" in measured:
            self.stat_update("model_seconds", value=measured["seconds"], unit="doc")
        for key in ("prompt_tokens", "completion_tokens"):
            if isinstance(measured.get(key), int):
                self.stat_update(key, value=measured[key], unit="doc")
        if measured.get("finish_reason") not in (None, "stop"):
            self.stat_update(f"finish_{measured['finish_reason']}")
        self.notify(doc, "done", **{k: measured[k] for k in ("prompt_tokens", "completion_tokens", "finish_reason")
                                    if measured.get(k) is not None})
        yield doc

    def _second_request(self, done) -> dict | None:
        """The body of a second request a finished one asks for (``PageRecognizer``'s repair pass), sent at once into
        the same window; ``None`` (the default): the result goes on as it is."""
        return None

    def _second_done(self, done, body: dict | None, error: str | None):
        """``done`` with the second request's response ``body`` (or its ``error``) added, for ``_done``."""
        return done

    def _next_request(self, done) -> dict | None:
        """The body of one more request after a second one came back (``_second_done``): a third, a fourth, ...
        (``PageRecognizer``'s repair passes), sent at once; ``None`` (the default): the result goes on."""
        return None

    def _run_served(self, data):
        """The requests (``_rows``) through saturate: built in its prepare threads (``_request``, with the observers'
        ``prepare`` and ``request`` events around it), up to the backend's window in flight, each result handed to
        ``_done`` as it finishes. A result that asks for a second request (``_second_request``) waits for it: the
        second request goes into the same window at once, and the result goes on with its response
        (``_second_done``) while the others stream on."""
        import anyio
        from saturate import AdaptiveClient, Auto, through

        b = self.backend
        results: queue.Queue = queue.Queue(maxsize=self.results_windows * b.max_window)
        rows = self._rows(data, results)
        budget = ErrorBudget(self, self.max_page_errors)
        headers = b.request_headers()            # secrets read here, in the task

        def request(row: dict) -> dict:       # in saturate's prepare threads
            from ...images.pixels import forget_last, last_decode

            doc, unit = row["doc"], self._unit(row)
            self.notify(doc, "prepare", **unit)
            forget_last()
            body = self._request(row)
            row["built"] = time.perf_counter()
            if (decoded := last_decode()) is not None:  # the request was built from the pixels (a chat adapter)
                row["decoded"] = decoded[0]
                self._decoded(*decoded)
            carrier: dict = {}
            self.notify(doc, "request", carrier=carrier, **unit)
            # saturate sends the same headers with every request: linecaster serve reads the trace context from the
            # body (an OpenAI-compatible server would not)
            if self.route is None and carrier.get("traceparent"):
                body["traceparent"] = carrier["traceparent"]
            return body

        route = self.route or f"/linecaster/{self.step}"

        async def pump():
            async with AdaptiveClient(b.endpoint, window=Auto(initial=b.initial_window, max_limit=b.max_window),
                                      read_timeout=b.read_timeout, headers=headers) as client:

                async def second(done, body):
                    while body is not None:          # the second request, and any it asks for after it
                        out, error = await client.post(body, route)
                        done = self._second_done(done, out, error)
                        body = self._next_request(done)
                    await asyncio.to_thread(results.put, done)

                async with anyio.create_task_group() as seconds:     # left only when every second request is back
                    async with through(client, rows, request, self._parse, route=route,
                                       prepare_workers=self.prepare_workers) as stream:
                        async for done in stream:
                            body = self._second_request(done)
                            if body is None:
                                await asyncio.to_thread(results.put, done)
                            else:
                                seconds.start_soon(second, done, body)

        def worker():
            try:
                asyncio.run(pump())
            except BaseException as e:  # surfaced in the pipeline's thread
                results.put(e)
            results.put(_END)

        started = time.perf_counter()
        threading.Thread(target=worker, name=f"linecaster-{self.step}", daemon=True).start()
        while (item := results.get()) is not _END:
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, Passed):
                self.stat_update(item.stat)
                yield item.doc
                continue
            yield from self._done(item, budget)
        # wall time of the served run, first request to last result (downstream blocks included)
        self.stat_update("served_wall_seconds", value=round(time.perf_counter() - started, 2))
