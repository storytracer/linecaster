"""linecaster serve with several replicas of a model: requests spread over the copies, one at a time each."""
from __future__ import annotations

import asyncio
import base64
import io
import threading
import time

import numpy as np
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from linecaster.serve import Hosted, build_app, serve_command
from linecaster.transcription import ModelInfo, Transcription


class SlowModel:
    step = "recognition"
    name = "slow"
    active = 0
    peak = 0
    lock = threading.Lock()

    def load(self):
        pass

    def __call__(self, image, transcription, **params):
        with SlowModel.lock:
            SlowModel.active += 1
            SlowModel.peak = max(SlowModel.peak, SlowModel.active)
        time.sleep(0.2)
        with SlowModel.lock:
            SlowModel.active -= 1
        transcription.model.append(ModelInfo(step=self.step, name=f"{self.name}-{id(self)}"))
        return transcription


def _png() -> str:
    buf = io.BytesIO()
    Image.fromarray(np.zeros((4, 4, 3), np.uint8)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _run(replicas: int, pages: int):
    SlowModel.active = SlowModel.peak = 0
    hosted = [Hosted("recognition", f"{__name__}:SlowModel", {}, replicas=replicas)]

    async def go():
        async with TestClient(TestServer(build_app(hosted))) as client:
            while (await client.get("/health")).status != 200:
                await asyncio.sleep(0.01)
            body = {"model": "recognition", "image": _png(), "transcription": Transcription().model_dump(mode="json")}
            t = time.perf_counter()
            res = await asyncio.gather(*(client.post("/v1/linecaster/recognition", json=body) for _ in range(pages)))
            names = {(await r.json())["transcription"]["model"][-1]["name"] for r in res}
            info = (await (await client.get("/v1/models")).json())["data"][0]
            return time.perf_counter() - t, names, info

    return asyncio.run(go())


def test_one_replica_runs_one_request_at_a_time():
    wall, names, info = _run(1, 4)
    assert SlowModel.peak == 1 and len(names) == 1 and info["replicas"] == 1
    assert wall >= 0.8


def test_replicas_share_the_queue():
    wall, names, info = _run(2, 4)
    assert SlowModel.peak == 2 and len(names) == 2 and info["replicas"] == 2
    assert wall < 0.7


def test_serve_command_passes_replicas():
    cmd = serve_command([{"name": "recognition", "spec": "x:Y", "replicas": 2}, {"name": "layout", "spec": "x:Z"}])
    assert cmd[cmd.index("--replicas") + 1] == "recognition=2" and cmd.count("--replicas") == 1
