"""``ModelBlock``: the base of the model blocks, one block per step (layout, lines, recognition, ...), each with
its backend.

In-process, a block calls its model page by page. Served, it streams its pages through saturate:
up to a window of pages in flight (adapted to the server's queue gauges and 429s), results passed
on as they finish, so CPU work upstream and downstream overlaps the server's GPU work. Either
way a page's result depends only on the page (the server never mixes pages in a batch).
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
from ...errors import CatalogError
from .contract import Contract, parts
from .page import ErrorBudget, PageBlock, decode_rgb, error_entry, failed, image_bytes, page_of, record_error, set_page

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


class ModelBlock(PageBlock):
    """Run one model step on every page, adding its part to the page's ``transcription``. In-process it is a
    per-unit transform; served a stream transform (pages in flight in a window, passed on as they finish)."""

    step = "model"
    role = "model"
    route: str | None = None       # the served route; None = linecaster serve's ``/linecaster/{step}``
    #: a step that reads only regions with this label gets no image for a page without one (``None``)
    region_label: str | None = None
    prepare_workers: int = 2       # threads building requests ahead of admission (image encoding)

    def __init__(self, backend: InProcess | Served, transcription: str = "ocr_new", params: dict | None = None,
                 primary: str | None = None, skip_on_error: bool = True, name: str | None = None):
        self.name = name or f"{self.step} ({backend.describe()})"   # before the base __init__, which names the stats
        super().__init__()
        self.backend, self.transcription, self.params = backend, transcription, params or {}
        self.primary, self.skip_on_error = primary or transcription, skip_on_error

    @property
    def shape(self) -> str:
        return "stream" if self.backend.served else "unit"

    def contract(self) -> Contract:
        reads = parts(("image", *STEP_READS.get(self.step, ())), self.transcription)
        return Contract(unit="page", role=self.role, reads=reads,
                        adds=parts(produces(self.backend, self.step), self.transcription))

    def warm_up(self) -> None:
        """The backend's: in-process the engine loads (not on the first page, so a page's measured ``seconds`` never
        include it); served the client's settings are resolved."""
        self.backend.warm_up()

    def needs_image(self, t: Transcription) -> bool:
        return self.region_label is None or any(r.label == self.region_label for r in t.regions)

    # ------------------------------------------------------------- in-process
    def process_page(self, doc, page: Page) -> Page:
        t = page.transcription(self.transcription)
        start, began = time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        image = decode_rgb(image_bytes(doc)) if self.needs_image(t) else None
        out = self.backend.model()(image, t, **self.params)
        if out.model:
            out.model[-1].measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
            out.model[-1].measurements.setdefault("datetime", began)     # ALTO processingDateTime, PAGE date
            if getattr(self.backend, "preset", None):        # built from a catalog preset
                out.model[-1].preset, out.model[-1].preset_sha256 = self.backend.preset, self.backend.preset_sha256
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
    def _request(self, row: dict) -> dict:
        doc = row["doc"]
        t = page_of(doc).transcription(self.transcription)
        return {"model": self.backend.model, "page_id": doc.id,
                "image": base64.b64encode(image_bytes(doc)).decode("ascii") if self.needs_image(t) else None,
                "transcription": t.model_dump(mode="json"), "params": self.params}

    @staticmethod
    def _parse(body: dict) -> dict:
        """Validated here, so a malformed response is that page's error (saturate), not the task's."""
        return {"transcription": Transcription.model_validate(body["transcription"]), "usage": body.get("usage") or {}}

    def _run_served(self, data):
        from saturate import AdaptiveClient, Auto, through

        b: Served = self.backend
        results: queue.Queue = queue.Queue(maxsize=4 * b.max_window)
        rows = ((doc.id, {"doc": doc}) for doc in self._passing(data, results))
        budget = ErrorBudget(self, self.max_page_errors)
        headers = b.request_headers()            # secrets read here, in the task

        def request(row: dict) -> dict:       # in saturate's prepare threads
            doc = row["doc"]
            self.notify(doc, "prepare")
            body = self._request(row)
            carrier: dict = {}
            self.notify(doc, "request", carrier=carrier)
            # saturate sends the same headers with every request: linecaster serve reads the trace context from the
            # body (an OpenAI-compatible server would not)
            if self.route is None and carrier.get("traceparent"):
                body["traceparent"] = carrier["traceparent"]
            return body

        async def pump():
            async with AdaptiveClient(b.endpoint, window=Auto(initial=b.initial_window, max_limit=b.max_window),
                                      read_timeout=b.read_timeout, headers=headers) as client:
                async with through(client, rows, request, self._parse,
                                   route=self.route or f"/linecaster/{self.step}",
                                   prepare_workers=self.prepare_workers) as stream:
                    async for done in stream:
                        await asyncio.to_thread(results.put, done)

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
            doc = item.row["doc"]
            self.stat_update("pages")
            budget.page()
            if item.error is not None:
                self.notify(doc, "done", error=item.error)
                self._served_failure(doc, item.error, budget)
                yield doc
                continue
            page = page_of(doc)
            out = item.out["transcription"]
            page.transcriptions[self.transcription] = out
            set_page(doc, page, self.primary)
            measured = out.model[-1].measurements if out.model else {}
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
        # wall time of the served run, first request to last result (downstream blocks included)
        self.stat_update("served_wall_seconds", value=round(time.perf_counter() - started, 2))

