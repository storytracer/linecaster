"""Model blocks: one block per step (layout, lines, recognition, ...), each with its backend.

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

from ..backends import InProcess, Served
from ..page import Page
from ..transcription.model import Transcription
from .base import PageStep, decode_rgb, image_bytes, page_of, set_page

_END = object()



class ModelStep(PageStep):
    """Run one model step on every page, adding its part to the page's ``transcription``."""

    step = "model"
    route: str | None = None       # the served route; None = linecaster serve's ``/linecaster/{step}``
    prepare_workers: int = 2       # threads building requests ahead of admission (image encoding)

    def __init__(self, backend: InProcess | Served, transcription: str = "ocr", params: dict | None = None,
                 primary: str | None = None, skip_on_error: bool = True, name: str | None = None):
        self.name = name or f"{self.step} ({backend.describe()})"   # before the base __init__, which names the stats
        super().__init__()
        self.backend, self.transcription, self.params = backend, transcription, params or {}
        self.primary, self.skip_on_error = primary or transcription, skip_on_error
        self._skipped: list = []

    # ------------------------------------------------------------- in-process
    def process_page(self, doc, page: Page) -> Page:
        t = page.transcription(self.transcription)
        start = time.perf_counter()
        out = self.backend.model()(decode_rgb(image_bytes(doc)), t, **self.params)
        if out.model:
            out.model[-1].measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
        page.transcriptions[self.transcription] = out
        return page

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.skip_on_error:
            data = self._passing_errors(data)
        if not self.backend.served:
            yield from super().run(data, rank, world_size)
        else:
            yield from self._run_served(data)
        yield from self._skipped

    def _passing_errors(self, data):
        """Pages a previous step failed on bypass this step (they are written with their errors)."""
        self._skipped = []
        for doc in data:
            if doc.metadata.get("errors"):
                self.stat_update("skipped_after_error")
                self._skipped.append(doc)
            else:
                yield doc

    # ----------------------------------------------------------------- served
    def _request(self, row: dict) -> dict:
        doc = row["doc"]
        page = page_of(doc)
        return {"model": self.backend.model, "page_id": doc.id,
                "image": base64.b64encode(image_bytes(doc)).decode("ascii"),
                "transcription": page.transcription(self.transcription).model_dump(mode="json"),
                "params": self.params}

    @staticmethod
    def _parse(body: dict) -> dict:
        return {"transcription": body["transcription"], "usage": body.get("usage") or {}}

    def _run_served(self, data):
        from saturate import AdaptiveClient, Auto, through

        b: Served = self.backend
        results: queue.Queue = queue.Queue(maxsize=4 * b.max_window)
        rows = ((doc.id, {"doc": doc}) for doc in data)

        async def pump():
            async with AdaptiveClient(b.endpoint, window=Auto(initial=b.initial_window, max_limit=b.max_window),
                                      read_timeout=b.read_timeout) as client:
                async with through(client, rows, self._request, self._parse,
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
            doc = item.row["doc"]
            self.stat_update("pages")
            if item.error is not None:
                self.stat_update("errors")
                doc.metadata.setdefault("errors", []).append({"step": self.step, "error": item.error})
                yield doc
                continue
            page = page_of(doc)
            out = Transcription.model_validate(item.out["transcription"])
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
            yield doc
        # wall time of the served run, first request to last result (downstream blocks included)
        self.stat_update("served_wall_seconds", value=round(time.perf_counter() - started, 2))


class LayoutStep(ModelStep):
    step = "layout"


class LinesStep(ModelStep):
    step = "lines"


class RecognitionStep(ModelStep):
    step = "recognition"


class TablesStep(ModelStep):
    step = "tables"


class FormulasStep(ModelStep):
    step = "formulas"
