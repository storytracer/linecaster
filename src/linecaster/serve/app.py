"""``linecaster serve``: host engines over HTTP for blocks that reach them through saturate.

Stateless: every request carries the page image, the transcription so far and the parameters; the
server keeps nothing between requests. Routes:

* ``POST /v1/linecaster/{step}`` — ``{"model", "image" (base64; null for a page the step reads no region of),
  "transcription", "params", "page_id"}``
  -> ``{"transcription", "usage", "timing"}``; 429 when the model's queue is full, 404 for an unknown
  model, 422 for a request the model cannot use.
* ``GET /health`` — 200 once every model is loaded (saturate's ``Engine`` waits for it).
* ``GET /metrics`` — vLLM-shaped gauges per model (``vllm:num_requests_waiting``,
  ``vllm:num_requests_running``), which saturate's window controller reads.
* ``GET /v1/models`` — the hosted models.

Each model has one worker thread that runs its requests one at a time in arrival order: a page's
result depends only on the page, and different models (layout, lines, recognition) work on
different pages at the same time. Image decoding happens in a small thread pool before a request
joins its model's queue.

Tracing: a request that carries a W3C ``traceparent`` (in the body, as linecaster's served blocks send it, or in
the headers) continues that trace with ``linecaster.serve.decode`` (the image decoded, the transcription read),
``linecaster.serve.queue`` (waiting for the model's worker) and ``linecaster.serve.model`` (the model call); an
unsampled trace (flags 00) or a request without one records nothing. The spans go to the file the task names
(``LINECASTER_TRACES``, or ``--traces``) and, with the ``OTEL_*`` variables, to OTLP (``serve_provider``).
"""
from __future__ import annotations

import asyncio
import base64
import json
import queue
from datetime import datetime, timezone
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from aiohttp import web
from loguru import logger
from opentelemetry import context as otel_context
from opentelemetry import trace as trace_api
from opentelemetry.trace import StatusCode

from ..backends import resolve
from ..blocks.base.page import decode_rgb
from ..data.transcription import Transcription
from ..tracing import context_of



@dataclass
class Hosted:
    name: str
    spec: str
    kwargs: dict
    max_queue: int = 16
    preset: str | None = None          # id@edition when hosted from a catalog preset
    preset_sha256: str | None = None
    model: object = None
    jobs: queue.Queue = field(default_factory=queue.Queue)
    admitted: int = 0          # accepted and not yet answered (decoding, waiting or running)
    running: int = 0
    served: int = 0
    failed: int = 0
    busy_seconds: float = 0.0

    @property
    def step(self) -> str:
        return self.model.step

    def load(self) -> None:
        t = time.perf_counter()
        self.model = resolve(self.spec)(**self.kwargs)
        self.model.load()
        logger.info("loaded {model} ({engine}, step {step}) in {seconds}s", model=self.name, engine=self.spec,
                    step=self.step, seconds=round(time.perf_counter() - t, 1))

    def attributes(self) -> dict:
        """The identifying attributes of this model's spans."""
        attrs = {"linecaster.model": self.name, "linecaster.engine": self.spec}
        if self.model is not None and isinstance(getattr(self.model, "step", None), str):
            attrs["linecaster.step"] = self.model.step
        if self.preset:
            attrs["linecaster.preset"], _, edition = self.preset.partition("@")
            if edition:
                attrs["linecaster.edition"] = edition
        return attrs

    def work(self, loop: asyncio.AbstractEventLoop, tracer=None) -> None:
        tracer = tracer or trace_api.NoOpTracer()
        while True:
            image, t, params, fut, parent, waiting = self.jobs.get()
            waiting.end()
            span = tracer.start_span("linecaster.serve.model", context=parent, attributes=self.attributes())
            token = otel_context.attach(trace_api.set_span_in_context(span))      # this thread's logs
            self.running += 1
            start = time.perf_counter()
            try:
                began = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                out = self.model(image, t, **params)
                if out.steps:
                    out.steps[-1].engine = out.steps[-1].engine or getattr(self.model, "engine_id", None)
                    out.steps[-1].measurements.setdefault("datetime", began)
                if self.preset and out.steps:
                    out.steps[-1].preset, out.steps[-1].preset_sha256 = self.preset, self.preset_sha256
                if out.steps:
                    out.steps[-1].measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
                dumped = out.model_dump(mode="json")
                result = (200, {"transcription": dumped,
                                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                                "timing": {"model_seconds": round(time.perf_counter() - start, 4)}})
                if span.is_recording():
                    lines = dumped.get("lines") or []
                    span.set_attributes({"linecaster.lines": len(lines),
                                         "linecaster.regions": len(dumped.get("regions") or []),
                                         "linecaster.words": sum(len(x.get("words") or ()) for x in lines)})
                self.served += 1
            except Exception as e:  # a page the model cannot read: an error for this request only
                logger.opt(exception=True).warning("model {model} failed on a request: {error_type}: {error}",
                                                   model=self.name, error_type=type(e).__name__, error=str(e))
                result = (422, {"error": f"{type(e).__name__}: {e}"})
                span.set_status(StatusCode.ERROR)
                span.set_attribute("linecaster.error.type", type(e).__name__)
                self.failed += 1
            self.busy_seconds += time.perf_counter() - start
            self.running -= 1
            otel_context.detach(token)
            span.end()
            loop.call_soon_threadsafe(_resolve, fut, result)


def _resolve(fut: asyncio.Future, result) -> None:
    if not fut.done():
        fut.set_result(result)


def build_app(hosted: list[Hosted], decode_workers: int = 4, tracer=None, after_first_call=None) -> web.Application:
    """The server's application. ``tracer``: where the spans of traced requests go (``serve_provider``); none:
    no spans. ``after_first_call()`` runs in the event loop once each model has answered its first request."""
    tracer = tracer or trace_api.NoOpTracer()
    first_calls: set[str] = set()
    by_name = {h.name: h for h in hosted}
    pool = ThreadPoolExecutor(decode_workers, thread_name_prefix="decode")
    app = web.Application(client_max_size=256 * 2**20)
    ready = {"ok": False}

    async def start(app_):
        loop = asyncio.get_running_loop()
        for h in hosted:   # load one after another (the GPU is shared), then serve
            await loop.run_in_executor(None, h.load)
            threading.Thread(target=h.work, args=(loop, tracer), name=f"model-{h.name}", daemon=True).start()
        ready["ok"] = True

    async def health(request):
        return web.json_response({"status": "ok" if ready["ok"] else "loading"}, status=200 if ready["ok"] else 503)

    async def models(request):
        return web.json_response({"object": "list", "data": [
            {"id": h.name, "object": "model", "owned_by": "linecaster", "step": h.step if h.model else None,
             "spec": h.spec} for h in hosted]})

    async def metrics(request):
        lines = ["# TYPE vllm:num_requests_waiting gauge", "# TYPE vllm:num_requests_running gauge"]
        for h in hosted:
            lab = f'{{model_name="{h.name}"}}'
            lines.append(f"vllm:num_requests_waiting{lab} {max(h.admitted - h.running, 0)}")
            lines.append(f"vllm:num_requests_running{lab} {h.running}")
        for h in hosted:
            lab = f'{{model_name="{h.name}"}}'
            lines.append(f"linecaster_requests_served_total{lab} {h.served}")
            lines.append(f"linecaster_requests_failed_total{lab} {h.failed}")
            lines.append(f"linecaster_model_busy_seconds_total{lab} {h.busy_seconds:.3f}")
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")

    async def run_step(request):
        if not ready["ok"]:
            return web.json_response({"error": "loading"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "body is not JSON"}, status=400)
        step = request.match_info["step"]
        h = by_name.get(body.get("model")) or next((x for x in hosted if x.step == step and not body.get("model")), None)
        if h is None or h.step != step:
            return web.json_response({"error": f"no {step} model {body.get('model')!r} here"}, status=404)
        if h.admitted >= h.max_queue:
            return web.json_response({"error": "queue full"}, status=429, headers={"Retry-After": "1"})
        h.admitted += 1
        try:
            loop = asyncio.get_running_loop()
            parent = context_of(body.get("traceparent") or request.headers.get("traceparent"))
            attrs = h.attributes()
            if body.get("page_id"):
                attrs["linecaster.page.id"] = str(body["page_id"])
            decoding = tracer.start_span("linecaster.serve.decode", context=parent, attributes=attrs)
            try:
                data = body["image"]
                raw = None if data is None else base64.b64decode(data)
                image = (raw if raw is None or getattr(h.model, "image_input", "rgb") == "bytes"
                         else await loop.run_in_executor(pool, decode_rgb, raw))
                t = Transcription.model_validate(body.get("transcription") or {})
            except Exception as e:
                decoding.set_status(StatusCode.ERROR)
                decoding.set_attribute("linecaster.error.type", type(e).__name__)
                return web.json_response({"error": f"bad request: {type(e).__name__}: {e}"}, status=422)
            finally:
                decoding.end()
            fut = loop.create_future()
            waiting = tracer.start_span("linecaster.serve.queue", context=parent, attributes=attrs)
            h.jobs.put((image, t, body.get("params") or {}, fut, parent, waiting))
            status, payload = await fut
            if after_first_call is not None and h.name not in first_calls:
                first_calls.add(h.name)
                after_first_call()
            return web.json_response(payload, status=status)
        finally:
            h.admitted -= 1

    async def chat(request):
        return web.json_response({"error": "chat completions are not served here (yet): use /v1/linecaster/{step}"},
                                 status=400)

    app.on_startup.append(start)
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/linecaster/{step}", run_step)
    app.router.add_post("/v1/chat/completions", chat)
    return app


def serve_provider(traces: str | None = None):
    """The server's tracer provider: it continues the traces of requests that carry one (unsampled ones and requests
    without one record nothing), into the file ``traces`` (default ``LINECASTER_TRACES``, which a task sets for the
    server it starts) and, with the ``OTEL_*`` variables, to OTLP. None when there is neither."""
    import os

    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ParentBased

    from ..tracing import RUN_ENV, TASK_ENV, TRACES_ENV, otlp_configured, resource, task_provider

    traces = traces or os.environ.get(TRACES_ENV)
    if not traces and not otlp_configured():
        return None
    task = os.environ.get(TASK_ENV)
    res = resource("serve", os.environ.get(RUN_ENV), int(task) if task and task.isdigit() else None)
    provider, _ = task_provider(res, ParentBased(ALWAYS_OFF), traces)
    return provider


def serve(hosted: list[Hosted], host: str = "127.0.0.1", port: int = 8100, decode_workers: int = 4,
          traces: str | None = None) -> None:
    from ..runtime.logs import configure, install_trace_ids

    configure()
    provider = serve_provider(traces)
    app = build_app(hosted, decode_workers, provider.get_tracer("linecaster") if provider else None,
                    after_first_call=_graceful_signals if provider else None)
    if provider is not None:
        install_trace_ids()

        async def flush(app_):           # on SIGTERM (saturate's Engine stops the server so) and SIGINT
            await asyncio.get_running_loop().run_in_executor(None, provider.shutdown)

        async def signals(app_):
            _graceful_signals()

        app.on_startup.append(signals)
        app.on_shutdown.append(flush)
    web.run_app(app, host=host, port=port, access_log=None, print=None)


def _graceful_signals() -> None:
    """SIGTERM and SIGINT end the server gracefully, once (so its spans are flushed and its trace file closed), set
    again after the engines loaded and after each model's first call: an engine's library may put its own handler in
    place of aiohttp's (PaddlePaddle does, at its first operation, and ends the process at once)."""
    import signal

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _raise_graceful_exit)


_STOPPING = threading.Event()


def _raise_graceful_exit() -> None:
    """The first signal ends the server; a second one (saturate's Engine signals the process group, and ``uv run``
    passes the signal on to its child as well) must not cut the graceful end short."""
    if _STOPPING.is_set():
        return
    _STOPPING.set()
    raise web.GracefulExit()
