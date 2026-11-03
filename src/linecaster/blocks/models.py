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

    def __init__(self, backend: InProcess | Served, transcription: str = "ocr", params: dict | None = None,
                 primary: str | None = None):
        super().__init__()
        self.backend, self.transcription, self.params = backend, transcription, params or {}
        self.primary = primary or transcription
        self.name = f"{self.step} ({backend.describe()})"

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
        if not self.backend.served:
            yield from super().run(data, rank, world_size)
            return
        yield from self._run_served(data)

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
                async with through(client, rows, self._request, self._parse, route=f"/linecaster/{self.step}",
                                   prepare_workers=2) as stream:
                    async for done in stream:
                        await asyncio.to_thread(results.put, done)

        def worker():
            try:
                asyncio.run(pump())
            except BaseException as e:  # surfaced in the pipeline's thread
                results.put(e)
            results.put(_END)

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
            page.transcriptions[self.transcription] = Transcription.model_validate(item.out["transcription"])
            set_page(doc, page, self.primary)
            yield doc


class LayoutStep(ModelStep):
    step = "layout"


class LinesStep(ModelStep):
    step = "lines"


class RecognitionStep(ModelStep):
    step = "recognition"
