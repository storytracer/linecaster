"""Page recognition by a VLM behind an OpenAI-compatible chat server (vLLM, SGLang, a hosted endpoint).

``PageRecognizer`` is a served ``ModelBlock`` whose route is ``/chat/completions`` instead of
``linecaster serve``'s ``/linecaster/{step}``: the same saturate machinery (``AdaptiveClient`` +
``through()``: a window of pages in flight, adapted to the engine's queue gauges, 429s and delivered
tokens; results passed on as they finish), with an adapter (``linecaster.adapters``) building the
request from the page image and parsing the completion into a text-only ``Transcription``.

    from linecaster.adapters import chat_model
    from linecaster.backends import Served

    spec = chat_model("lightonocr-2-1b")          # a catalog preset (or its Hugging Face id)
    PageRecognizer(spec, Served("http://127.0.0.1:8000/v1", model=spec.served_name, max_window=48, initial_window=8))

``spec`` may also be the preset ref itself (``PageRecognizer("lightonocr-2-1b", ...)``). Every result's
``StepInfo`` records the preset edition and its hash (``preset``, ``preset_sha256``) next to the settings.

The completion is kept verbatim (``Transcription.extra["raw"]``, and ``text`` equals it); its
``finish_reason`` and token counts go to ``extra`` and ``StepInfo.measurements``. A completion cut
off at ``max_tokens`` (``finish_reason == "length"``, on page OCR nearly always a repetition loop) is
stored like any other and counted in the block's stats (``finish_length``); deciding what it means is
for whoever scores or post-processes the text. A request that fails is recorded on the page as an
error (``doc.metadata["errors"]``), as for every model block.

``saturate`` reads the response's ``usage`` itself, so the window controller sees delivered tokens.
"""
from __future__ import annotations

import asyncio
import queue
import threading

from ...adapters import ENGINE, ChatAdapter, chat_model
from ...backends import Served
from ...data.transcription import StepInfo
from ...errors import PipelineConfigError
from ..base.contract import Contract, parts
from ..base.model import _END, ModelBlock, Passed, produces
from ..base.page import ErrorBudget, error_entry, image_bytes, page_of, record_error, set_page


class PageRecognizer(ModelBlock):
    """Recognize every page with a chat VLM; the result is the page's ``transcription`` (default ``ocr_new``).

    ``backend.model`` is the name the server hosts the model under (for vLLM without
    ``--served-model-name``: the Hub id, ``spec.model``). ``prepare_workers`` threads build requests
    ahead of admission (decode, resize and PNG-encode the image; Pillow releases the GIL)."""

    step = "recognition"
    route = "/chat/completions"

    def __init__(self, spec: ChatAdapter | str, backend: Served, transcription: str = "ocr_new", primary: str | None = None,
                 skip_on_error: bool = True, prepare_workers: int = 4, name: str | None = None):
        if isinstance(spec, str):
            spec = chat_model(spec)
        if not getattr(backend, "served", False):
            raise PipelineConfigError("PageRecognizer needs a Served backend (an OpenAI-compatible chat endpoint)")
        super().__init__(backend, transcription, None, primary, skip_on_error,
                         name=name or f"page ({spec.model}, served {backend.endpoint})")
        spec.served_name = backend.model
        self.spec, self.prepare_workers = spec, prepare_workers

    shape = "stream"
    #: what it reads besides the page image, and what it adds besides the text and its preset's parts
    regions_read: tuple[str, ...] = ()
    lines_added: tuple[str, ...] = ()

    def contract(self) -> Contract:
        """The completion is the text; the preset's ``capabilities.produces`` say what else (``markdown``, ...)."""
        adds = {*self.lines_added, "text", *produces(self.backend, self.step, self.spec)}
        return Contract(unit="page", role=self.role, reads=parts(("image", *self.regions_read), self.transcription),
                        adds=parts(adds, self.transcription))

    def process_page(self, doc, page):  # pragma: no cover - only reached with an in-process backend
        raise PipelineConfigError("PageRecognizer runs served only")

    def _request(self, row: dict) -> dict:       # ModelBlock's request() notifies prepare and request around it
        return self.spec.request(image_bytes(row["doc"]))

    def _parse(self, body: dict) -> dict:
        t = self.spec.parse(body, backend=self.backend.describe())
        return {"transcription": t, "usage": body.get("usage") or {}}


#: Region labels a region-recognition step reads by default (pictures and formulas excluded: a picture has
#: no text and a formula step reads formulas as LaTeX).
REGION_LABELS = frozenset({"text", "title", "section_header", "page_header", "page_footer", "caption", "footnote",
                           "list_item", "reference", "code", "table"})


class RegionRecognizer(PageRecognizer):
    """Recognize each layout region with a chat VLM: one request per region crop, through the same saturate
    machinery as ``PageRecognizer``, results collected per page. Any layout step can come before it.

    Crops are cut at the scale the model expects for a whole page (``spec.page_longest``: the page is
    scaled so its longest side has that length, and the region is cut from it, ``pad`` px around the
    region's box at that scale), so a small region is not blown up. Every read region gets one line:
    the region's box and polygon, the completion as its text (verbatim; ``extra`` keeps ``raw`` and
    ``finish_reason``); the transcription's earlier lines are replaced. A page whose regions all
    failed is recorded as an error; a page without readable regions passes through unchanged."""

    regions_read = ("regions",)
    lines_added = ("lines",)          # one line per region read

    def __init__(self, spec: ChatAdapter | str, backend: Served, transcription: str = "ocr_new", labels=REGION_LABELS,
                 pad: int = 8, primary: str | None = None, skip_on_error: bool = True, prepare_workers: int = 4):
        if isinstance(spec, str):
            spec = chat_model(spec)
        super().__init__(spec, backend, transcription, primary, skip_on_error, prepare_workers,
                         name=f"regions ({spec.model}, served {backend.endpoint})")
        self.labels = frozenset(labels)
        self.pad = spec.region_pad if spec.region_pad is not None else pad

    def run(self, data, rank: int = 0, world_size: int = 1):
        self.warm_up()
        yield from self._run_regions(data)

    # requests are built in saturate's prepare threads from the page image decoded once per page
    def _request(self, row: dict) -> dict:
        import io

        state, region = row["state"], row["region"]
        self.notify(state["doc"], "prepare", region=region.id)
        crop = self.spec.crop_region(state["image"], region, state["scale"], self.pad)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        body = self.spec.request_region(buf.getvalue(), region)
        # the trace context cannot go along: saturate sends the same headers with every request, and a chat
        # server reads it from the headers only
        self.notify(state["doc"], "request", region=region.id, carrier={})
        return body

    def _parse(self, body: dict) -> dict:
        raw, finish = self.spec.content(body)
        return {"raw": raw, "finish_reason": finish, "usage": body.get("usage") or {}}

    def _rows(self, data, results):
        import io

        from PIL import Image

        for doc in self._passing(data, results):
            page = page_of(doc)
            t = page.transcription(self.transcription)
            regions = sorted((r for r in t.regions if self.spec.reads_region(r, self.labels)),
                             key=lambda r: (r.reading_order is None, r.reading_order or 0))
            if not regions:
                results.put(Passed(doc, "pages_without_regions"))
                continue
            with Image.open(io.BytesIO(image_bytes(doc))) as im:
                img = im.convert("RGB")
            scale = self.spec.page_longest / max(img.size) if self.spec.page_longest else 1.0
            if scale != 1.0:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
            state = {"doc": doc, "page": page, "image": img, "remaining": len(regions), "out": {}, "scale": scale}
            for r in regions:
                yield f"{doc.id}|{r.id}", {"state": state, "region": r}

    def _finish(self, state, budget: ErrorBudget) -> object:
        from ...data.transcription import Line

        doc, page = state["doc"], state["page"]
        t = page.transcription(self.transcription)
        lines, failed, tokens = [], [], {"prompt_tokens": 0, "completion_tokens": 0}
        regions = sorted((r for r in t.regions if r.id in state["out"]),
                         key=lambda r: (r.reading_order is None, r.reading_order or 0))
        for k, r in enumerate(regions):
            res = state["out"][r.id]
            if "error" in res:
                failed.append({"region": r.id, "error": res["error"]})
                continue
            for key in tokens:
                tokens[key] += int((res["usage"] or {}).get(key) or 0)
            lines.append(Line(id=f"{r.id}_l0", region_id=r.id, reading_order=k, bbox=r.bbox, polygon=r.polygon,
                              text=res["raw"], extra={"raw": res["raw"], "finish_reason": res["finish_reason"]}))
            if res["finish_reason"] not in (None, "stop"):
                self.stat_update(f"finish_{res['finish_reason']}")
        t.lines = lines
        t.steps.append(StepInfo(step=self.step, name=self.spec.model, engine=ENGINE, revision=self.spec.revision,
                                preset=getattr(self.spec, "preset", None),
                                preset_sha256=getattr(self.spec, "preset_sha256", None),
                                backend=self.backend.describe(), settings={**self.spec.settings(), "pad": self.pad,
                                                                           "page_scale": round(state["scale"], 6),
                                                                           "labels": sorted(self.labels)},
                                measurements={**tokens, "regions": len(regions), "failed": len(failed)}))
        set_page(doc, page, self.primary)
        self.stat_update("regions", value=len(regions))
        entry = None
        if failed:
            self.stat_update("region_errors", value=len(failed))
            if not lines:          # every region failed: the page did
                entry = record_error(doc, error_entry(self, failed, "ServerError"))
        self.notify(doc, "done", error=entry)
        if entry is not None:
            budget.failed(doc, entry)
        return doc

    def _run_regions(self, data):
        from saturate import AdaptiveClient, Auto, through

        b: Served = self.backend
        results: queue.Queue = queue.Queue(maxsize=8 * b.max_window)
        rows = self._rows(data, results)
        budget = ErrorBudget(self, self.max_page_errors)
        headers = b.request_headers()            # secrets read here, in the task

        async def pump():
            async with AdaptiveClient(b.endpoint, window=Auto(initial=b.initial_window, max_limit=b.max_window),
                                      read_timeout=b.read_timeout, headers=headers) as client:
                async with through(client, rows, self._request, self._parse, route=self.route,
                                   prepare_workers=self.prepare_workers) as stream:
                    async for done in stream:
                        await asyncio.to_thread(results.put, done)

        def worker():
            try:
                asyncio.run(pump())
            except BaseException as e:
                results.put(e)
            results.put(_END)

        threading.Thread(target=worker, name="linecaster-regions", daemon=True).start()
        while (item := results.get()) is not _END:
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, Passed):
                self.stat_update(item.stat)
                yield item.doc
                continue
            state, region = item.row["state"], item.row["region"]
            state["out"][region.id] = {"error": item.error} if item.error is not None else item.out
            usage = (item.out or {}).get("usage") or {}
            self.notify(state["doc"], "done", region=region.id, error=item.error,
                        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                        finish_reason=(item.out or {}).get("finish_reason"))
            state["remaining"] -= 1
            if state["remaining"] == 0:
                self.stat_update("pages")
                budget.page()
                yield self._finish(state, budget)
