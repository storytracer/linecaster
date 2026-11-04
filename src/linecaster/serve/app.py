"""``linecaster serve``: host engine models over HTTP for blocks that reach them through saturate.

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
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
from datetime import datetime, timezone
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
    preset: str | None = None          # id@edition when hosted from a catalogue preset
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
        log.info("loaded %s (%s, step %s) in %.1fs", self.name, self.spec, self.step, time.perf_counter() - t)

    def work(self, loop: asyncio.AbstractEventLoop) -> None:
        while True:
            image, t, params, fut = self.jobs.get()
            self.running += 1
            start = time.perf_counter()
            try:
                began = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                out = self.model(image, t, **params)
                if out.model:
                    out.model[-1].measurements.setdefault("datetime", began)
                if self.preset and out.model:
                    out.model[-1].preset, out.model[-1].preset_sha256 = self.preset, self.preset_sha256
                if out.model:
                    out.model[-1].measurements.setdefault("seconds", round(time.perf_counter() - start, 4))
                result = (200, {"transcription": out.model_dump(mode="json"),
                                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                                "timing": {"model_seconds": round(time.perf_counter() - start, 4)}})
                self.served += 1
            except Exception as e:  # a page the model cannot read: an error for this request only
                log.exception("model %s failed", self.name)
                result = (422, {"error": f"{type(e).__name__}: {e}"})
                self.failed += 1
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
            threading.Thread(target=h.work, args=(loop,), name=f"model-{h.name}", daemon=True).start()
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
            try:
                data = body["image"]
                image = None if data is None else await loop.run_in_executor(pool, decode_rgb, base64.b64decode(data))
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
