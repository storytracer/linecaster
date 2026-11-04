"""Page recognition by a VLM behind an OpenAI-compatible chat server (vLLM, SGLang, a hosted endpoint).

``ChatPageStep`` is a served ``ModelStep`` whose route is ``/chat/completions`` instead of
``linecaster serve``'s ``/linecaster/{step}``: the same saturate machinery (``AdaptiveClient`` +
``through()``: a window of pages in flight, adapted to the engine's queue gauges, 429s and delivered
tokens; results passed on as they finish), with a model spec (``linecaster.models``) building the
request from the page image and parsing the completion into a text-only ``Transcription``.

    from linecaster.backends import Served
    from linecaster.models import chat_model

    spec = chat_model("lightonocr-2-1b")          # a catalogue preset (or its Hugging Face id)
    ChatPageStep(spec, Served("http://127.0.0.1:8000/v1", model=spec.served_name, max_window=48, initial_window=8))

``spec`` may also be the preset ref itself (``ChatPageStep("lightonocr-2-1b", ...)``). Every result's
``ModelInfo`` records the preset edition and its hash (``preset``, ``preset_sha256``) next to the settings.

The completion is kept verbatim (``Transcription.extra["raw"]``, and ``text`` equals it); its
``finish_reason`` and token counts go to ``extra`` and ``ModelInfo.measurements``. A completion cut
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

from ..backends import Served
from ..models import ChatModel, chat_model
from ..transcription.model import ModelInfo
from .base import image_bytes, page_of, set_page
from .models import _END, ModelStep


class ChatPageStep(ModelStep):
    """Recognise every page with a chat VLM; the result is the page's ``transcription`` (default ``ocr``).

    ``backend.model`` is the name the server hosts the model under (for vLLM without
    ``--served-model-name``: the Hub id, ``spec.model``). ``prepare_workers`` threads build requests
    ahead of admission (decode, resize and PNG-encode the image; Pillow releases the GIL)."""

    step = "page"
    route = "/chat/completions"

    def __init__(self, spec: ChatModel | str, backend: Served, transcription: str = "ocr", primary: str | None = None,
                 skip_on_error: bool = True, prepare_workers: int = 4, name: str | None = None):
        if isinstance(spec, str):
            spec = chat_model(spec)
        if not getattr(backend, "served", False):
            raise TypeError("ChatPageStep needs a Served backend (an OpenAI-compatible chat endpoint)")
        super().__init__(backend, transcription, None, primary, skip_on_error,
                         name=name or f"page ({spec.model}, served {backend.endpoint})")
        spec.served_name = backend.model
        self.spec, self.prepare_workers = spec, prepare_workers

    def process_page(self, doc, page):  # pragma: no cover - only reached with an in-process backend
        raise TypeError("ChatPageStep runs served only")

    def _request(self, row: dict) -> dict:
        return self.spec.request(image_bytes(row["doc"]))

    def _parse(self, body: dict) -> dict:
        t = self.spec.parse(body, backend=self.backend.describe())
        return {"transcription": t, "usage": body.get("usage") or {}}


#: Region labels a region-recognition step reads by default (pictures and formulas excluded: a picture has
#: no text and a formula step reads formulas as LaTeX).
REGION_LABELS = frozenset({"text", "title", "section_header", "page_header", "page_footer", "caption", "footnote",
                           "list_item", "reference", "code", "table"})


class ChatRegionStep(ChatPageStep):
    """Recognise each layout region with a chat VLM: one request per region crop, through the same saturate
    machinery as ``ChatPageStep``, results collected per page. Any layout step can come before it.

    Crops are cut at the scale the model expects for a whole page (``spec.page_longest``: the page is
    scaled so its longest side has that length, and the region is cut from it, ``pad`` px around the
    region's box at that scale), so a small region is not blown up. Every read region gets one line:
    the region's box and polygon, the completion as its text (verbatim; ``extra`` keeps ``raw`` and
    ``finish_reason``); the transcription's earlier lines are replaced. A page whose regions all
    failed is recorded as an error; a page without readable regions passes through unchanged."""

    step = "regions"

    def __init__(self, spec: ChatModel | str, backend: Served, transcription: str = "ocr", labels=REGION_LABELS,
                 pad: int = 8, primary: str | None = None, skip_on_error: bool = True, prepare_workers: int = 4):
        if isinstance(spec, str):
            spec = chat_model(spec)
        super().__init__(spec, backend, transcription, primary, skip_on_error, prepare_workers,
                         name=f"regions ({spec.model}, served {backend.endpoint})")
        self.labels = frozenset(labels)
        self.pad = spec.region_pad if spec.region_pad is not None else pad

    def run(self, data, rank: int = 0, world_size: int = 1):
        if self.skip_on_error:
            data = self._passing_errors(data)
        yield from self._run_regions(data)
        yield from self._skipped

    # requests are built in saturate's prepare threads from the page image decoded once per page
    def _request(self, row: dict) -> dict:
        import io

        state, region = row["state"], row["region"]
        crop = self.spec.crop_region(state["image"], region, state["scale"], self.pad)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return self.spec.request_region(buf.getvalue(), region)

    def _parse(self, body: dict) -> dict:
        raw, finish = self.spec.content(body)
        return {"raw": raw, "finish_reason": finish, "usage": body.get("usage") or {}}

    def _rows(self, data, results):
        import io

        from PIL import Image

        for doc in data:
            page = page_of(doc)
            t = page.transcription(self.transcription)
            regions = sorted((r for r in t.regions if self.spec.reads_region(r, self.labels)),
                             key=lambda r: (r.reading_order is None, r.reading_order or 0))
            if not regions:
                results.put(("pass", doc))
                continue
            with Image.open(io.BytesIO(image_bytes(doc))) as im:
                img = im.convert("RGB")
            scale = self.spec.page_longest / max(img.size) if self.spec.page_longest else 1.0
            if scale != 1.0:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
            state = {"doc": doc, "page": page, "image": img, "remaining": len(regions), "out": {}, "scale": scale}
            for r in regions:
                yield f"{doc.id}|{r.id}", {"state": state, "region": r}

    def _finish(self, state) -> object:
        from ..transcription.model import Line

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
        t.model.append(ModelInfo(step=self.step, name=self.spec.model, revision=self.spec.revision,
                                 preset=getattr(self.spec, "preset", None),
                                 preset_sha256=getattr(self.spec, "preset_sha256", None),
                                 backend=self.backend.describe(), settings={**self.spec.settings(), "pad": self.pad,
                                                                            "page_scale": round(state["scale"], 6),
                                                                            "labels": sorted(self.labels)},
                                 measurements={**tokens, "regions": len(regions), "failed": len(failed)}))
        if failed:
            self.stat_update("region_errors", value=len(failed))
            if not lines:
                doc.metadata.setdefault("errors", []).append({"step": self.step, "error": failed})
        set_page(doc, page, self.primary)
        self.stat_update("regions", value=len(regions))
        return doc

    def _run_regions(self, data):
        from saturate import AdaptiveClient, Auto, through

        b: Served = self.backend
        results: queue.Queue = queue.Queue(maxsize=8 * b.max_window)
        rows = self._rows(data, results)

        async def pump():
            async with AdaptiveClient(b.endpoint, window=Auto(initial=b.initial_window, max_limit=b.max_window),
                                      read_timeout=b.read_timeout) as client:
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
            if isinstance(item, tuple) and item[0] == "pass":
                self.stat_update("pages_without_regions")
                yield item[1]
                continue
            state, region = item.row["state"], item.row["region"]
            state["out"][region.id] = {"error": item.error} if item.error is not None else item.out
            state["remaining"] -= 1
            if state["remaining"] == 0:
                self.stat_update("pages")
                yield self._finish(state)
