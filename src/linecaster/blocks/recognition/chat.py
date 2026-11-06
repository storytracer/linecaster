"""Page and region recognition by a VLM behind an OpenAI-compatible chat server (vLLM, SGLang, a hosted endpoint).

``PageRecognizer`` and ``RegionRecognizer`` are ``ModelBlock``s on the ``Chat`` backend: the served streaming of
``ModelBlock`` (saturate's ``AdaptiveClient`` + ``through()``: a window of requests in flight, adapted to the
server's queue gauges, 429s and delivered tokens; results passed on as they finish; a failed request the page's
error) on the route ``/chat/completions``. What is specific to chat is here: the backend's adapter
(``linecaster.adapters``) builds the request from the page image (or a region's crop) and parses the completion
into a text-only ``Transcription``.

    from linecaster.backends import Chat

    PageRecognizer(Chat("lightonocr-2-1b", "http://127.0.0.1:8000/v1", max_window=48, initial_window=8))
    PageRecognizer("lightonocr-2-1b")             # a preset by name: Chat on the task's ChatModelServer

Every result's ``StepInfo`` records the preset edition and its hash (``preset``, ``preset_sha256``) next to the
settings.

The completion is kept verbatim (``Transcription.extra["raw"]``, and ``text`` equals it); its
``finish_reason`` and token counts go to ``extra`` and ``StepInfo.measurements``. A completion cut
off at ``max_tokens`` (``finish_reason == "length"``, on page OCR nearly always a repetition loop) is
stored like any other and counted in the block's stats (``finish_length``); deciding what it means is
for whoever scores or post-processes the text. A request that fails is recorded on the page as an
error (``doc.metadata["errors"]``), as for every model block.

``saturate`` reads the response's ``usage`` itself, so the window controller sees delivered tokens.
"""
from __future__ import annotations

from ...adapters import ENGINE
from ...backends import Chat
from ...data.transcription import StepInfo
from ...errors import PipelineConfigError
from ..base.contract import Contract, parts
from ..base.model import ModelBlock, Passed, produces
from ..base.page import ErrorBudget, error_entry, image_bytes, page_of, record_error, set_page


def chat_backend(backend, block: str, prefer: str) -> Chat:
    """``backend`` as a ``Chat`` backend: a preset ref becomes one on the task's chat server."""
    if isinstance(backend, str):
        return Chat(backend, prefer=prefer)
    if not isinstance(backend, Chat):
        raise PipelineConfigError(f"{block} needs a Chat backend (a chat preset's VLM behind an OpenAI-compatible "
                                  f"server), not {type(backend).__name__}")
    return backend


class PageRecognizer(ModelBlock):
    """Recognizes every page with a chat VLM, whose completion becomes the page's transcription.

    A stream transform on the ``Chat`` backend (served only): one request per page, built by the preset's adapter
    from the page image, the completion parsed into a text-only transcription that replaces ``transcription``.
    Reads the page image; adds ``text`` and what the preset produces (``markdown``, ``html``, ...). The completion
    is kept verbatim (``extra["raw"]``); its ``finish_reason`` and token counts go to ``extra`` and the step's
    measurements, and a completion cut off at ``max_tokens`` is counted (stat ``finish_length``). The
    ``StepInfo`` records the preset edition and its hash. A failed request is the page's error.

    Args:
        backend: a ``Chat`` backend, or a chat preset's ref (its page preset) for one on the task's
            ``ChatModelServer``; any other backend is refused (``PipelineConfigError``).
        transcription: the transcription the completion becomes.
        primary: the transcription whose text becomes the datatrove document's ``text``; ``None``:
            ``transcription``.
        skip_on_error: pass pages that carry errors through unprocessed.
        prepare_workers: threads that build requests ahead of admission (decode, resize and PNG-encode the image;
            Pillow releases the GIL).
        name: the block's name in stats and logs; ``None``: ``"page (<model>, served <endpoint>)"``.

    Example:
        from linecaster.backends import Chat

        PageRecognizer("lightonocr-2-1b@1")
        PageRecognizer(Chat("lightonocr-2-1b@1", "http://127.0.0.1:8000/v1", max_window=48, initial_window=8))
    """

    step = "recognition"
    route = "/chat/completions"
    shape = "stream"
    #: what it reads besides the page image, what it adds besides the text and its preset's parts, and what of
    #: that it makes anew where the transcription has it already
    regions_read: tuple[str, ...] = ()
    lines_added: tuple[str, ...] = ()
    parts_made_anew: tuple[str, ...] = ()
    docs_args = {"backend": "lightonocr-2-1b@1"}

    def __init__(self, backend: Chat | str, transcription: str = "ocr_new", primary: str | None = None,
                 skip_on_error: bool = True, prepare_workers: int = 4, name: str | None = None):
        backend = chat_backend(backend, type(self).__name__, "page")
        super().__init__(backend, transcription, None, primary, skip_on_error,
                         name=name or f"page ({backend.adapter.model}, served {backend.endpoint})")
        self.prepare_workers = prepare_workers

    @property
    def adapter(self):
        """The chat preset's adapter (the backend's)."""
        return self.backend.adapter

    def contract(self) -> Contract:
        """The completion is the text; the preset's ``capabilities.produces`` say what else (``markdown``, ...)."""
        adds = {*self.lines_added, "text", *produces(self.backend, self.step)}
        return Contract(unit="page", role=self.role, reads=parts(("image", *self.regions_read), self.transcription),
                        adds=parts(adds, self.transcription), replaces=parts(self.parts_made_anew, self.transcription))

    def process_page(self, doc, page):  # pragma: no cover - the Chat backend is always served
        raise PipelineConfigError(f"{type(self).__name__} runs served only")

    def _request(self, row: dict) -> dict:       # ModelBlock notifies prepare and request around it
        return self.adapter.request(image_bytes(row["doc"]))

    def _parse(self, body: dict) -> dict:
        t = self.adapter.parse(body, backend=self.backend.describe())
        return {"transcription": t, "usage": body.get("usage") or {}}


#: Region labels a region-recognition step reads by default (pictures and formulas excluded: a picture has
#: no text and a formula step reads formulas as LaTeX).
#: pixels around a region's box when neither the block nor the adapter says (``region_pad``)
DEFAULT_PAD = 8
REGION_LABELS = frozenset({"text", "title", "section_header", "page_header", "page_footer", "caption", "footnote",
                           "list_item", "reference", "code", "table"})


class RegionRecognizer(PageRecognizer):
    """Recognizes each layout region of every page with a chat VLM, one request per region crop.

    The same saturate machinery as ``PageRecognizer``, results collected per page; any layout step can come
    before it. Reads the page image and ``regions``; adds ``lines``, ``text`` and what the preset produces, and
    replaces ``lines`` and ``text`` (the transcription's earlier lines, with their text, are replaced).
    Crops are cut at the scale the model expects for a whole page (the adapter's ``page_longest``: the page is
    scaled so its longest side has that length, and the region is cut from it, ``pad`` px around the region's box
    at that scale), so a small region is not blown up; the adapter decides which regions it reads. Every read
    region gets one line: the region's box and polygon, the completion as its text (verbatim; ``extra`` keeps
    ``raw`` and ``finish_reason``), in reading order; the transcription's earlier lines are replaced. The
    ``StepInfo`` records the preset edition, the settings with ``pad``, ``page_scale`` and ``labels``, and the
    token counts, ``regions`` and ``failed``. A page whose regions all failed is the page's error; a page without
    readable regions passes through unchanged (stat ``pages_without_regions``).

    Args:
        backend: a ``Chat`` backend, or a chat preset's ref (a model's Hugging Face id picks its region preset) for
            one on the task's ``ChatModelServer``; any other backend is refused (``PipelineConfigError``).
        transcription: the transcription it reads the regions of and adds the lines to.
        labels: the region labels it reads (default: text-like regions and tables, no pictures or formulas).
        pad: pixels around each region's box at the page scale; ``None``: the adapter's ``region_pad``, else 8.
        primary: the transcription whose text becomes the datatrove document's ``text``; ``None``:
            ``transcription``.
        skip_on_error: pass pages that carry errors through unprocessed.
        prepare_workers: threads that build the requests (crops, PNG encoding) ahead of admission.

    Example:
        RegionRecognizer("minicpm-ocr-1.0@1")
    """

    regions_read = ("regions",)
    lines_added = ("lines",)          # one line per region read
    parts_made_anew = ("lines", "text")   # the earlier lines (and their text) are replaced
    docs_args = {"backend": "minicpm-ocr-1.0@1"}

    results_windows = 8               # a page's regions finish one by one

    def __init__(self, backend: Chat | str, transcription: str = "ocr_new", labels=REGION_LABELS, pad: int | None = None,
                 primary: str | None = None, skip_on_error: bool = True, prepare_workers: int = 4):
        backend = chat_backend(backend, type(self).__name__, "region")
        super().__init__(backend, transcription, primary, skip_on_error, prepare_workers,
                         name=f"regions ({backend.adapter.model}, served {backend.endpoint})")
        self.labels = frozenset(labels)
        # an explicit pad wins; the adapter's region_pad is the default
        self.pad = pad if pad is not None else (self.adapter.region_pad if self.adapter.region_pad is not None
                                                else DEFAULT_PAD)

    def _unit(self, row: dict) -> dict:
        return {"region": row["region"].id}

    # requests are built in saturate's prepare threads from the page image decoded once per page; the trace context
    # cannot go along: saturate sends the same headers with every request, and a chat server reads it from the
    # headers only
    def _request(self, row: dict) -> dict:
        import io

        state, region = row["state"], row["region"]
        crop = self.adapter.crop_region(state["image"], region, state["scale"], self.pad)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return self.adapter.request_region(buf.getvalue(), region)

    def _parse(self, body: dict) -> dict:
        raw, finish = self.adapter.content(body)
        return {"raw": raw, "finish_reason": finish, "usage": body.get("usage") or {}}

    def _rows(self, data, results):
        import io

        from PIL import Image

        for doc in self._passing(data, results):
            page = page_of(doc)
            t = page.transcription(self.transcription)
            regions = sorted((r for r in t.regions if self.adapter.reads_region(r, self.labels)),
                             key=lambda r: (r.reading_order is None, r.reading_order or 0))
            if not regions:
                results.put(Passed(doc, "pages_without_regions"))
                continue
            with Image.open(io.BytesIO(image_bytes(doc))) as im:
                img = im.convert("RGB")
            longest = self.adapter.page_longest
            scale = longest / max(img.size) if longest else 1.0
            if scale != 1.0:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
            state = {"doc": doc, "page": page, "image": img, "remaining": len(regions), "out": {}, "scale": scale}
            for r in regions:
                yield f"{doc.id}|{r.id}", {"doc": doc, "state": state, "region": r}

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
        a = self.adapter
        t.steps.append(StepInfo(step=self.step, name=a.model, engine=ENGINE, revision=a.revision,
                                preset=a.preset, preset_sha256=a.preset_sha256,
                                backend=self.backend.describe(), settings={**a.settings(), "pad": self.pad,
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

    def _done(self, item, budget: ErrorBudget):
        """A region's result, kept with its page; the page leaves when its last region is back."""
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
