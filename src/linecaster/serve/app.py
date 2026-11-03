"""``linecaster serve``: host engine models over HTTP for blocks that reach them through saturate.

Stateless: every request carries the page image, the transcription so far and the parameters; the
server keeps nothing between requests. Routes:

* ``POST /v1/linecaster/{step}`` — ``{"model", "image" (base64), "transcription", "params", "page_id"}``
  -> ``{"transcription", "usage", "timing"}``; 429 when the model's queue is full, 404 for an unknown
  model, 422 for a request the model cannot use.
* ``GET /health`` — 200 once every model is loaded (saturate's ``Engine`` waits for it).
* ``GET /metrics`` — vLLM-shaped gauges per model (``vllm:num_requests_waiting``,
  ``vllm:num_requests_running``), which saturate's window controller reads.
* ``GET /v1/models`` — the hosted models.

Each model has one worker thread per replica (default one), all taking requests from the model's
queue in arrival order; a replica is its own copy of the model and runs one request at a time. A
page goes to exactly one replica, so its result depends only on the page, however many replicas
there are; different models (layout, lines, recognition) work on different pages at the same time. Image decoding happens in a small thread pool before a request
joins its model's queue.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from aiohttp import web

from ..backends import resolve
from ..blocks.base import decode_rgb
from ..transcription.model import Transcription

log = logging.getLogger("linecaster.serve")


@dataclass
class Hosted:
    name: str
    spec: str
    kwargs: dict
    max_queue: int = 16
    replicas: int = 1          # copies of the model on the device, each with its own worker thread
    model: object = None       # the first copy (its step, name)
    copies: list = field(default_factory=list)
    jobs: queue.Queue = field(default_factory=queue.Queue)
    admitted: int = 0          # accepted and not yet answered (decoding, waiting or running)
    running: int = 0
    served: int = 0
    failed: int = 0
    busy_seconds: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)   # the counters, updated by every replica

    @property
    def step(self) -> str:
        return self.model.step

    def load(self) -> None:
        t = time.perf_counter()
        for _ in range(max(int(self.replicas), 1)):
            model = resolve(self.spec)(**self.kwargs)
            model.load()
            self.copies.append(model)
        self.model = self.copies[0]
        log.info("loaded %s (%s, step %s, %d replica(s)) in %.1fs", self.name, self.spec, self.step,
                 len(self.copies), time.perf_counter() - t)

    def work(self, loop: asyncio.AbstractEventLoop, model) -> None:
        while True:
            image, t, params, fut = self.jobs.get()
            with self.lock:
                self.running += 1
            start = time.perf_counter()
            try:
                out = model(image, t, **params)
                if out.model:
                    out.model[-1].measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
                result = (200, {"transcription": out.model_dump(mode="json"),
                                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                                "timing": {"model_seconds": round(time.perf_counter() - start, 4)}})
                ok = True
            except Exception as e:  # a page the model cannot read: an error for this request only
                log.exception("model %s failed", self.name)
                result = (422, {"error": f"{type(e).__name__}: {e}"})
                ok = False
            with self.lock:
                self.served += ok
                self.failed += not ok
                self.busy_seconds += time.perf_counter() - start
                self.running -= 1
            loop.call_soon_threadsafe(_resolve, fut, result)


def _resolve(fut: asyncio.Future, result) -> None:
    if not fut.done():
        fut.set_result(result)


def build_app(hosted: list[Hosted], decode_workers: int = 4) -> web.Application:
    by_name = {h.name: h for h in hosted}
    pool = ThreadPoolExecutor(decode_workers, thread_name_prefix="decode")
    app = web.Application(client_max_size=256 * 2**20)
    ready = {"ok": False}

    async def start(app_):
        loop = asyncio.get_running_loop()
        for h in hosted:   # load one after another (the GPU is shared), then serve
            await loop.run_in_executor(None, h.load)
            for i, model in enumerate(h.copies):
                threading.Thread(target=h.work, args=(loop, model), name=f"model-{h.name}-{i}", daemon=True).start()
        ready["ok"] = True

    async def health(request):
        return web.json_response({"status": "ok" if ready["ok"] else "loading"}, status=200 if ready["ok"] else 503)

    async def models(request):
        return web.json_response({"object": "list", "data": [
            {"id": h.name, "object": "model", "owned_by": "linecaster", "step": h.step if h.model else None,
             "spec": h.spec, "replicas": h.replicas} for h in hosted]})

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
            try:
                data = base64.b64decode(body["image"])
                image = await loop.run_in_executor(pool, decode_rgb, data)
                t = Transcription.model_validate(body.get("transcription") or {})
            except Exception as e:
                return web.json_response({"error": f"bad request: {type(e).__name__}: {e}"}, status=422)
            fut = loop.create_future()
            h.jobs.put((image, t, body.get("params") or {}, fut))
            status, payload = await fut
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


def serve(hosted: list[Hosted], host: str = "127.0.0.1", port: int = 8100, decode_workers: int = 4) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    web.run_app(build_app(hosted, decode_workers), host=host, port=port, access_log=None, print=None)
