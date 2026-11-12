"""Page and region recognition: by a VLM behind an OpenAI-compatible chat server (vLLM, SGLang, a hosted endpoint),
or, for ``PageRecognizer``, by a page engine (an engine whose unit is the page) on the ``InProcess`` or ``Served``
backend.

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
off at ``max_tokens`` (``finish_reason == "length"``) is stored like any other and counted in the block's stats
(``finish_length``). It may be a repetition loop, or a page that needs more tokens than ``max_tokens`` (a dense
table) and finishes with more room; deciding what it means is for whoever scores or post-processes the text. With the
repair pass on (the chat option ``repair_max_tokens``, ``linecaster.adapters.ChatAdapter``), ``PageRecognizer`` sends
such a page again with a larger cap, and again with the next while it stops at its cap, and keeps the first
completion that finished. A request that fails is
recorded on the page as an error (``doc.metadata["errors"]``), as for every model block.

``saturate`` reads the response's ``usage`` itself, so the window controller sees delivered tokens.
"""
from __future__ import annotations

from loguru import logger

from ...adapters import ENGINE
from ...backends import Chat, InProcess, Served
from ...data.transcription import StepInfo, Transcription
from ...errors import CatalogError, PageError, PipelineConfigError, ServerError
from ..base.contract import Contract, parts
from ..base.model import ModelBlock, Passed, preset_backend, produces
from ..base.page import ErrorBudget, error_entry, image_bytes, page_of, record_error, set_page


def chat_backend(backend, block: str, prefer: str) -> Chat:
    """``backend`` as a ``Chat`` backend: a preset ref becomes one on the task's chat server."""
    if isinstance(backend, str):
        return Chat(backend, prefer=prefer)
    if not isinstance(backend, Chat):
        raise PipelineConfigError(f"{block} needs a Chat backend (a chat preset's VLM behind an OpenAI-compatible "
                                  f"server), not {type(backend).__name__}")
    return backend


def page_backend(backend, block: str) -> Chat | InProcess | Served:
    """``backend`` as a page recognizer's backend: a chat preset's ref (or a model's Hugging Face id) becomes a
    ``Chat`` backend on the task's chat server, a page engine's preset its ``InProcess`` backend; a preset of
    another unit is refused (``PipelineConfigError``)."""
    if isinstance(backend, str):
        from ...catalog.registry import catalog

        try:
            r = catalog().resolve(backend)
        except (CatalogError, ValueError):         # a Hugging Face id: its chat preset (chat_model decides)
            return Chat(backend, prefer="page")
        if r.engine == Chat.engine:
            return Chat(backend, prefer="page")
        unit = (catalog().preset(r.id).capabilities.unit or "")
        if unit != "page":
            raise PipelineConfigError(f"{block}: preset {r.ref} reads {unit or 'no'} units, not whole pages")
        return preset_backend(backend, "recognition")
    if not isinstance(backend, (Chat, InProcess, Served)):
        raise PipelineConfigError(f"{block} needs a Chat, InProcess or Served backend, not {type(backend).__name__}")
    return backend


def chat_step(t: Transcription | None) -> StepInfo | None:
    """The last step of ``t`` a chat VLM recognized it in (engine ``chat.v1``), or ``None``."""
    for step in reversed(t.steps if t is not None else []):
        if step.step == "recognition" and step.engine == ENGINE:
            return step
    return None


def pass_entry(t: Transcription, request: dict | None = None) -> dict:
    """One request of a page as ``extra["passes"]`` records it: the completion verbatim (``raw``), ``finish_reason``,
    ``prompt_tokens``, ``completion_tokens``, the ``max_tokens``, ``temperature`` and ``top_p`` it was sent with, and
    the preset edition. ``t`` is the completion parsed; ``request`` the body sent (``None``: the sampling ``t``'s step
    records, for a page record written earlier)."""
    step = chat_step(t)
    m = step.measurements if step is not None else {}
    sent = request if request is not None else ((step.settings.get("sampling") if step is not None else None) or {})
    return {"raw": t.extra.get("raw"), "finish_reason": t.extra.get("finish_reason"),
            "prompt_tokens": m.get("prompt_tokens"), "completion_tokens": m.get("completion_tokens"),
            "max_tokens": sent.get("max_tokens"), "temperature": sent.get("temperature"), "top_p": sent.get("top_p"),
            "preset": step.preset if step is not None else None}


def _total(values) -> int | None:
    known = [v for v in values if isinstance(v, int)]
    return sum(known) if known else None


class PageRecognizer(ModelBlock):
    """Recognizes every page with a chat VLM or a page engine, whose output becomes the page's transcription.

    On the ``Chat`` backend (served only) a stream transform: one request per page, built by the preset's adapter
    from the page image, the completion parsed into a text-only transcription that replaces ``transcription``. The
    completion is kept verbatim (``extra["raw"]``); its ``finish_reason`` and token counts go to ``extra`` and the
    step's measurements, and a completion cut off at ``max_tokens`` is counted (stat ``finish_length``).

    **The repair passes** (the chat option ``repair_max_tokens``: a cap, or a list of rising caps, one per pass;
    ``linecaster.adapters.ChatAdapter``): a page whose completion stopped at ``max_tokens`` waits in the block while its
    repair request goes into the same window at once (the same request body, so the same image and prompt and
    ``top_p``, with ``max_tokens`` raised and the repair temperature); the other pages stream on. A repair that stops
    at its cap too is sent again with the next cap, until one finishes or the caps run out. Each repair's
    ``max_tokens`` is its cap, at most the served context minus the page's prompt tokens (the context from the
    server's ``/models`` ``max_model_len``, else the preset's ``--max-model-len``); where that is not above the cap
    before it, no more repairs are sent (none at all: stat ``repair_skipped``). The page keeps the first completion
    that finished (``"stop"``), its first one otherwise; ``extra["passes"]`` records every request (``pass_entry``:
    the completion verbatim, finish reason, tokens, ``max_tokens`` as sent, temperature, ``top_p``, preset),
    ``extra["kept"]`` which one the transcription holds (from 1), and ``extra["raw"]`` and ``extra["finish_reason"]``
    stay the kept one's. The step's measurements sum the tokens of every request and list them per request
    (``pass_prompt_tokens``, ``pass_completion_tokens``); its settings add ``repair``. Pages that stopped otherwise are
    recorded as without repairs. A repair request that fails ends the repairs, and the page keeps what the passes
    before it give (stat ``repair_errors``), not an error of the page. A page record is written only after its
    repairs, so an interrupted task sends every request again. Stats:
    ``finish_length`` (first requests), ``repair_sent`` (repair requests), ``repair_stop``, ``repair_length`` (their
    finish reasons), ``repair_kept`` (pages that keep a repair), ``repair_skipped``, ``repair_errors``.

    With ``repair_only`` it reads page records written earlier (``PageRecordReader``) and sends only the repair
    requests, by the same rules and recorded the same way: for the pages whose transcription's first completion
    stopped at ``max_tokens`` and has no repair yet (``extra["passes"]`` with one entry, or a record without
    ``passes``, as linecaster wrote before the repair pass). Every other page passes through unchanged, without a
    request (stat ``repair_not_needed``). The first request's prompt tokens and sampling come from the record.

    On the ``InProcess`` or ``Served`` backend it runs a page engine (an engine of the recognition step whose unit is the
    page: a vendor package, or a client of a vendor's service) as every model block runs its engine: the engine
    gets the page image and returns the page's transcription. Either way it reads the page image and adds
    ``text`` and what the preset produces (``lines``, ``markdown``, ``html``, ...); the ``StepInfo`` records the
    preset edition and its hash. A failed request or call is the page's error.

    Args:
        backend: a ``Chat`` backend, an ``InProcess`` or ``Served`` backend of a page engine, or a preset's ref:
            a chat preset's (or a model's Hugging Face id: its page preset) for ``Chat`` on the task's
            ``ChatModelServer``, a page engine's for its engine in the pipeline's process; a preset of another
            unit or any other backend is refused (``PipelineConfigError``).
        transcription: the transcription the completion becomes.
        primary: the transcription whose text becomes the datatrove document's ``text``; ``None``:
            ``transcription``.
        skip_on_error: pass pages that carry errors through unprocessed.
        prepare_workers: threads that build requests ahead of admission (decode, resize and PNG-encode the image;
            Pillow releases the GIL).
        name: the block's name in stats and logs; ``None``: ``"page (<model>, served <endpoint>)"``.
        repair_only: send only the repair pass, for the pages of earlier page records that need it (a ``Chat``
            backend with ``repair_max_tokens`` set; ``PipelineConfigError`` otherwise).

    Example:
        from linecaster.backends import Chat

        PageRecognizer("lightonocr-2-1b@1")
        PageRecognizer(Chat("lightonocr-2-1b@1", "http://127.0.0.1:8000/v1", max_window=48, initial_window=8))
        PageRecognizer(Chat("lightonocr-3-0.8b@2", overrides={"repair_max_tokens": [8192, 12288]}))   # repair passes
        PageRecognizer("indra-ocr@1")             # a page engine, in the pipeline's process
    """

    step = "recognition"
    #: what it reads besides the page image, what it adds besides the text and its preset's parts, and what of
    #: that it makes anew where the transcription has it already
    regions_read: tuple[str, ...] = ()
    lines_added: tuple[str, ...] = ()
    parts_made_anew: tuple[str, ...] = ()
    docs_args = {"backend": "lightonocr-2-1b@1"}
    #: added later; a pipeline that leaves it at this default keeps its ``pipeline_sha256``
    unhashed_defaults = {"repair_only": False}

    def __init__(self, backend: Chat | InProcess | Served | str, transcription: str = "ocr_new",
                 primary: str | None = None, skip_on_error: bool = True, prepare_workers: int = 4,
                 name: str | None = None, repair_only: bool = False):
        backend = page_backend(backend, type(self).__name__)
        default = (f"page ({backend.adapter.model}, served {backend.endpoint})" if isinstance(backend, Chat)
                   else f"page ({backend.describe()})")
        super().__init__(backend, transcription, None, primary, skip_on_error, name=name or default)
        self.prepare_workers = prepare_workers
        self.repair_only = repair_only
        if repair_only and not (self.chat and self.adapter.repair_caps):
            raise PipelineConfigError(f"{type(self).__name__}: repair_only needs a Chat backend with the repair pass "
                                      "on (the option repair_max_tokens)")
        #: the served context the repair pass is checked against (``warm_up``: the server's, else the preset's)
        self._context = self.adapter.served_context() if self.repairs else None
        if self.repairs:
            self._check_context(self._context, "the preset's server flags")

    @property
    def repairs(self) -> bool:
        """Whether the block runs the repair pass (a ``Chat`` backend whose adapter has ``repair_max_tokens``)."""
        return self.chat and bool(self.adapter.repair_caps)

    def _check_context(self, context: int | None, source: str) -> None:
        """A warning when ``repair_max_tokens`` and a page's largest prompt do not fit the served ``context``."""
        a = self.adapter
        largest = a.max_prompt_tokens()
        if context and largest and a.repair_max_tokens + largest > context:
            logger.warning("repair pass: repair_max_tokens {cap} plus a page's largest prompt ({largest} tokens) is "
                           "more than the served context, {context} tokens ({source}); a repair gets at most the "
                           "context minus its prompt, and none where that is not above max_tokens (repair_skipped)",
                           cap=a.repair_max_tokens, largest=largest, context=context, source=source)

    def _served_context(self) -> tuple[int | None, str]:
        """The context the server gives the model: its ``/models`` ``max_model_len``, else the preset's flags."""
        import json
        import urllib.request

        b = self.backend
        try:
            req = urllib.request.Request(f"{b.endpoint.rstrip('/')}/models", headers=b.request_headers())
            with urllib.request.urlopen(req, timeout=30) as r:
                listed = json.load(r).get("data") or []
            for m in listed:
                if m.get("id") == b.model and m.get("max_model_len"):
                    return int(m["max_model_len"]), "the server's max_model_len"
        except (OSError, ValueError, AttributeError):    # no such route, not JSON: the preset's flags
            pass
        return self.adapter.served_context(), "the preset's server flags"

    def warm_up(self) -> None:
        """The backend's; with the repair pass, the served context it is checked against."""
        super().warm_up()
        if self.repairs and not getattr(self, "_context_read", False):
            context, source = self._served_context()
            if context != self._context:
                self._check_context(context, source)
            self._context, self._context_read = context, True
            logger.info("repair passes: max_tokens {cap}, temperature {t}, served context {context} ({source})",
                        cap=", ".join(map(str, self.adapter.repair_caps)), t=self.adapter.repair_temperature, context=context,
                        source=source)

    @property
    def chat(self) -> bool:
        """Whether the backend is a chat VLM's (``Chat``), not a page engine's."""
        return isinstance(self.backend, Chat)

    @property
    def route(self) -> str | None:
        """``/chat/completions`` for a chat VLM; a served page engine's is ``linecaster serve``'s."""
        return "/chat/completions" if self.chat else None

    @property
    def adapter(self):
        """The chat preset's adapter (the backend's); ``None`` for a page engine."""
        return getattr(self.backend, "adapter", None)

    def contract(self) -> Contract:
        """The completion is the text; the preset's ``capabilities.produces`` say what else (``markdown``, ...)."""
        adds = {*self.lines_added, "text", *produces(self.backend, self.step)}
        return Contract(unit="page", role=self.role, reads=parts(("image", *self.regions_read), self.transcription),
                        adds=parts(adds, self.transcription), replaces=parts(self.parts_made_anew, self.transcription))

    def process_page(self, doc, page):
        if self.chat:  # pragma: no cover - the Chat backend is always served
            raise PipelineConfigError(f"{type(self).__name__} on a Chat backend runs served only")
        return super().process_page(doc, page)

    def _request(self, row: dict) -> dict:       # ModelBlock notifies prepare and request around it
        if not self.chat:
            return super()._request(row)
        body = self.adapter.request(image_bytes(row["doc"]))
        if self.repair_only:                       # the repair request alone
            body = row["request"] = self.adapter.repair_request(body, row["cap"])
        elif self.repairs:                         # kept until the result is back: a repair resends it
            row["request"] = body
        return body

    def _parse(self, body: dict) -> dict:
        if not self.chat:
            return ModelBlock._parse(body)
        t = self.adapter.parse(body, backend=self.backend.describe())
        return {"transcription": t, "usage": body.get("usage") or {}}

    # ----------------------------------------------------------------- the repair pass
    def _first_pass(self, t: Transcription | None) -> dict | None:
        """The first request of a stored transcription that needs a repair (``pass_entry``), else ``None``."""
        if t is None:
            return None
        passes = t.extra.get("passes")
        if passes:
            return dict(passes[0]) if len(passes) == 1 and passes[0].get("finish_reason") == "length" else None
        step = chat_step(t)
        if t.extra.get("finish_reason") != "length" or step is None:
            return None
        if step.name != self.adapter.model:
            raise PipelineConfigError(f"{type(self).__name__}: the page records were transcribed by {step.name}, the "
                                      f"repair pass would ask {self.adapter.model}")
        return pass_entry(t)

    def _cap(self, first: dict, index: int = 0, previous: int | None = None) -> tuple[int, bool]:
        """The ``index``-th repair request's ``max_tokens`` after the context check, and whether it is above the cap
        of the request before it (``previous``; the first request's ``max_tokens`` for the first repair)."""
        cap = self.adapter.repair_cap(first.get("prompt_tokens"), self._context, index)
        before = previous if previous is not None else int(first.get("max_tokens")
                                                           or self.adapter.sampling.get("max_tokens") or 0)
        return cap, cap > before

    def _rows(self, data, results):
        if not self.repair_only:
            yield from super()._rows(data, results)
            return
        for doc in self._passing(data, results):
            page = page_of(doc)
            first = self._first_pass(page.transcriptions.get(self.transcription))
            if first is None:
                results.put(Passed(doc, "repair_not_needed"))
                continue
            cap, room = self._cap(first)
            if not room:                       # the context leaves no more room than the first request had
                page.transcriptions[self.transcription] = self._record(page.transcriptions[self.transcription],
                                                                       first, [])
                set_page(doc, page, self.primary)
                results.put(Passed(doc, "repair_skipped"))
                continue
            yield doc.id, {"doc": doc, "first": first, "cap": cap}

    def _second_request(self, done) -> dict | None:
        """The first repair request of a page whose first completion stopped at ``max_tokens`` (in saturate's
        loop); with ``repair_only`` the request that came back was that repair, and this asks for the next one."""
        if not self.repairs or done.error is not None:
            done.row.pop("request", None)
            return None
        if self.repair_only:                       # the stored first pass, then the repair just answered
            done.out["first"] = done.row["first"]
            done.out["repairs"] = [{"request": done.row.pop("request", None), "cap": done.row["cap"],
                                    "transcription": done.out["transcription"]}]
            return self._next_request(done)
        body = done.row.pop("request", None)
        t = done.out["transcription"]
        if t.extra.get("finish_reason") != "length":
            return None
        first = done.out["first"] = pass_entry(t, body)
        done.out["first_request"], done.out["repairs"] = body, []
        cap, room = self._cap(first)
        if not room:
            return None
        return self._send_repair(done, self.adapter.repair_request(body, cap), cap,
                                 notify_first=True)

    def _send_repair(self, done, request: dict, cap: int, notify_first: bool = False) -> dict:
        done.out["repairs"].append({"request": request, "cap": cap})
        doc = done.row["doc"]
        if notify_first:
            first = done.out["first"]
            self.notify(doc, "done", **{k: first[k] for k in ("prompt_tokens", "completion_tokens", "finish_reason")
                                        if first[k] is not None})
        self.notify(doc, "request", carrier={})
        return request

    def _second_done(self, done, body: dict | None, error: str | None):
        done.out["repairs"][-1].update(body=body, error=error)
        return done

    def _next_request(self, done) -> dict | None:
        """The next repair request while the last one stopped at its cap and the preset has a further cap whose
        request the context leaves room for; ``None`` otherwise."""
        repairs = done.out.get("repairs") or []
        if not repairs:
            return None
        last = repairs[-1]
        if last.get("error") is not None:
            return None
        if "transcription" in last:
            finish = last["transcription"].extra.get("finish_reason")
        elif last.get("body") is not None:
            try:
                finish = self.adapter.content(last["body"])[1]
            except ServerError:                    # not a completion: _done records the error
                return None
        else:
            return None
        index = len(repairs)
        if finish != "length" or index >= len(self.adapter.repair_caps):
            return None
        cap, room = self._cap(done.out["first"], index, last["cap"])
        if not room:
            return None
        base = done.out.get("first_request") or last["request"]
        return self._send_repair(done, self.adapter.repair_request(base, cap), cap)

    def _record(self, first: Transcription, p1: dict, repairs: list[dict]) -> Transcription:
        """The page's transcription after the repair passes: the first repair's that finished (``"stop"``), else
        ``first``; with ``extra["passes"]`` (the first request and each repair) and ``extra["kept"]`` (the kept
        pass, from 1), the tokens of every request in the step's measurements and the repair settings in its
        settings."""
        a = self.adapter
        passes, t, kept = [p1], first, 1
        for r in repairs:
            second = r.get("transcription")
            if second is None:
                break
            passes.append(pass_entry(second, r.get("request")))
            if kept == 1 and passes[-1]["finish_reason"] == "stop":
                old, new = chat_step(first), chat_step(second)
                second.steps = ([new if s is old else s for s in first.steps] if old is not None
                                else [*first.steps, new])
                t, kept = second, len(passes)
        step = chat_step(t)
        if step is not None:
            step.settings = {**step.settings, "repair": {"max_tokens": list(a.repair_caps),
                                                         "temperature": a.repair_temperature}}
            step.measurements.update({
                "prompt_tokens": _total(p["prompt_tokens"] for p in passes),
                "completion_tokens": _total(p["completion_tokens"] for p in passes),
                "pass_prompt_tokens": [p["prompt_tokens"] for p in passes],
                "pass_completion_tokens": [p["completion_tokens"] for p in passes]})
        t.extra["passes"], t.extra["kept"] = passes, kept
        return t

    def _done(self, item, budget: ErrorBudget):
        """A page's result; with the repair passes, a page that needed them completes with them here."""
        out = item.out or {}
        if not self.chat or not (self.repair_only or "repairs" in out):
            yield from super()._done(item, budget)
            return
        doc = item.row["doc"]
        page = page_of(doc)
        self.stat_update("pages")
        budget.page()
        if "repairs" in out:
            first_t = out["transcription"] if not self.repair_only else page.transcriptions[self.transcription]
            p1, repairs = out["first"], [dict(r) for r in out["repairs"]]
        else:                                      # repair_only, its first repair failed
            first_t, p1 = page.transcriptions[self.transcription], item.row["first"]
            repairs = [{"request": item.row.get("request"), "cap": item.row.get("cap"), "error": item.error}]
        for r in repairs:                          # the responses parsed
            if "transcription" not in r and r.get("body") is not None and r.get("error") is None:
                try:
                    r["transcription"] = self.adapter.parse(r["body"], backend=self.backend.describe())
                except ServerError as e:
                    r["error"] = str(e)
        self.stat_update(f"finish_{p1['finish_reason']}")
        if not repairs:
            self.stat_update("repair_skipped")
        error = None
        for r in repairs:
            self.stat_update("repair_sent")
            if r.get("error") is not None:
                error = r["error"]
                self.stat_update("repair_errors")
                logger.warning("page {page_id}: a repair request failed, the passes before it stay: {error}",
                               page_id=doc.id, error=error)
                r.pop("transcription", None)
                break
        t = self._record(first_t, p1, repairs)
        sent = [p1, *t.extra["passes"][1:]] if not self.repair_only else t.extra["passes"][1:]
        for key in ("prompt_tokens", "completion_tokens"):
            value = _total(p[key] for p in sent)
            if value is not None:
                self.stat_update(key, value=value, unit="doc")
        for p in t.extra["passes"][1:]:
            self.stat_update(f"repair_{p['finish_reason']}")
        if t.extra["kept"] > 1:
            self.stat_update("repair_kept")
        page.transcriptions[self.transcription] = t
        set_page(doc, page, self.primary)
        last = t.extra["passes"][-1]
        self.notify(doc, "done", error=error, **{k: last[k] for k in ("prompt_tokens", "completion_tokens",
                                                                       "finish_reason") if last[k] is not None})
        yield doc


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
    token counts, ``regions`` and ``failed``. A page whose regions all failed is the page's error, and so is a page
    without image bytes (stat ``errors``); a page without readable regions passes through unchanged (stat
    ``pages_without_regions``).

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

    route = "/chat/completions"
    regions_read = ("regions",)
    lines_added = ("lines",)          # one line per region read
    parts_made_anew = ("lines", "text")   # the earlier lines (and their text) are replaced
    docs_args = {"backend": "minicpm-ocr-1.0@1"}

    results_windows = 8               # a page's regions finish one by one

    def __init__(self, backend: Chat | str, transcription: str = "ocr_new", labels=REGION_LABELS, pad: int | None = None,
                 primary: str | None = None, skip_on_error: bool = True, prepare_workers: int = 4):
        backend = chat_backend(backend, type(self).__name__, "region")
        if backend.adapter.repair_max_tokens:
            raise PipelineConfigError(f"{type(self).__name__}: the repair pass is for whole pages (PageRecognizer); "
                                      "set repair_max_tokens to 0")
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
            try:
                data = image_bytes(doc)
            except PageError as e:     # the page's error (as in-process), not the task's
                entry = record_error(doc, error_entry(self, e))
                logger.warning("page {page_id} failed in {block}: {error_type}: {error}", page_id=doc.id,
                               block=entry["block"], error_type=entry["type"], error=entry["error"])
                results.put(Passed(doc, "errors"))
                continue
            with Image.open(io.BytesIO(data)) as im:
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
