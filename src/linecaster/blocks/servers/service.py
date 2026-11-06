"""``ServiceServer``: starts the service a page engine's preset names (its ``serve`` block) inside the task: vLLM for
an engine package that attaches to it (surya-ocr), or a vendor's own image entrypoint (Falcon-OCR's, OXR's). Like
the other server blocks it goes **last** in the pipeline, after the writer."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...errors import PipelineConfigError, ServerError
from ..base.contract import Contracted

#: variables of the pipeline's environment a service never inherits: it runs in its image's own environments
PIPELINE_ENV = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT")


class ServiceServer(Contracted, PipelineStep):
    """Starts the service a page engine's preset names inside the task, and stops it when the task's pages are through.

    The preset's ``serve`` block says what runs:

    * ``server: vllm`` (an engine package that attaches to vLLM, e.g. surya-ocr): the model pin is fetched (every
      pinned file checked) and served from that folder, ``vllm serve <folder> --host HOST --port PORT <flags>
      --served-model-name <the model's Hugging Face id>``, ready once ``/health`` and ``/v1/models`` answer 200;
    * ``server: vendor`` (a vendor's page pipeline in its own image, e.g. Falcon-OCR, OXR): with ``weights_dir`` the
      model pin is downloaded there first (every pinned file checked); then ``command``, the image's entrypoint,
      starts the service, ready once every ``health`` URL has answered 200, in order.

    The service runs in its own process group with the preset's ``env``, without the pipeline's environment
    (``PIPELINE_ENV``, and this interpreter's ``bin`` off ``PATH``), so the image's own Pythons and servers run as
    the image has them. A service that exits or is not ready within ``boot_timeout`` fails the task
    (``ServerError``). Its role is ``server`` and its unit ``any``: it touches no part. It goes **last** in the
    pipeline (after the writer): datatrove chains generators, and only the last one lives until every page is
    written. A vendor's entrypoint listens on the ports the image sets (one service per machine).

    Args:
        preset: the page preset whose ``serve`` block names the service (``id`` or ``id@edition``); a chat preset
            (``ChatModelServer`` starts its server), or a preset without such a block, is refused
            (``PipelineConfigError``).
        port: the port vLLM listens on (``server: vllm``); a vendor's entrypoint uses the image's own ports.
        host: the address vLLM binds to; default loopback only.
        vllm: the vLLM command (default ``vllm`` on the service's ``PATH``: the job image's).
        boot_timeout: seconds the service may take until it is ready.
    """

    type = "🔠 - LINECASTER"
    name = "🖥️ service server"
    unit, role = "any", "server"
    docs_args = {"preset": "falcon-ocr"}

    def __init__(self, preset: str, port: int = 8000, host: str = "127.0.0.1", vllm: str = "vllm",
                 boot_timeout: int = 1800):
        super().__init__()
        from ...catalog.registry import catalog

        r = catalog().resolve(preset)
        serve = dict(r.content.get("serve") or {})
        if r.engine == "chat.v1":
            raise PipelineConfigError(f"ServiceServer: {r.ref} is a chat preset; ChatModelServer starts its server")
        if serve.get("server") not in ("vllm", "vendor"):
            raise PipelineConfigError(f"ServiceServer: preset {r.ref} names no service (serve.server vllm or vendor)")
        if serve["server"] == "vendor" and not (serve.get("command") and serve.get("health")):
            raise PipelineConfigError(f"ServiceServer: preset {r.ref} names no command or health URLs")
        self.preset, self.ref = preset, r.ref
        self.serve = serve
        pin = r.content.get("model")
        model = catalog().model(pin["id"]) if pin else None
        self.weights = ({"model": model.id, "source": model.source.model_dump(), "revision": pin["revision"],
                         "files": pin["files"]} if pin else None)
        self.port, self.host, self.vllm, self.boot_timeout = port, host, vllm, boot_timeout
        self._proc = None

    @property
    def server(self) -> str:
        """``vllm`` or ``vendor``."""
        return self.serve["server"]

    def command(self, model_dir: str | None = None) -> list[str]:
        """The command that starts the service; for vLLM ``model_dir`` is the fetched pin (a placeholder without)."""
        if self.server == "vendor":
            return list(self.serve["command"])
        if self.weights is None:
            raise PipelineConfigError(f"ServiceServer: preset {self.ref} serves vLLM but pins no model")
        repo = self.weights["source"]["ref"]
        folder = model_dir or f"<{repo}@{self.weights['revision']}>"
        return [self.vllm, "serve", folder, "--host", self.host, "--port", str(self.port),
                *self.serve.get("flags", []), "--served-model-name", repo]

    def health(self) -> list[str]:
        """The URLs that must each answer 200, in order, before the service is ready."""
        if self.server == "vendor":
            return list(self.serve["health"])
        base = f"http://{'127.0.0.1' if self.host in ('0.0.0.0', '::') else self.host}:{self.port}"
        return [f"{base}/health", f"{base}/v1/models"]

    def environment(self) -> dict[str, str]:
        """The service's environment: this one without the pipeline's (``PIPELINE_ENV``, this interpreter's ``bin`` on
        ``PATH``), with the preset's ``env``."""
        env = {k: v for k, v in os.environ.items() if k not in PIPELINE_ENV}
        own = os.path.realpath(os.path.join(sys.prefix, "bin"))
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if p and os.path.realpath(p) != own)
        env.update(self.serve.get("env") or {})
        return env

    def launch_command(self, python: str | None = None) -> list[str]:
        """``command()`` as ``--dry-run`` shows it (vLLM's model folder as a placeholder)."""
        return self.command()

    def prepare(self) -> str | None:
        """Fetch the weights the service reads: vLLM's model folder (returned), or a vendor's ``weights_dir``."""
        from ...catalog.fetch import check, hf_snapshot

        if self.server == "vllm":
            return str(hf_snapshot(self.weights))
        folder = self.serve.get("weights_dir")
        if folder and self.weights is not None:
            from huggingface_hub import snapshot_download

            repo, revision = self.weights["source"]["ref"], self.weights["revision"]
            logger.info("{repo}@{revision} -> {folder}", repo=repo, revision=revision[:12], folder=folder)
            snapshot_download(repo, revision=revision, local_dir=folder)
            for name, sha in self.weights["files"].items():
                check(os.path.join(folder, name), sha, f"{self.weights['model']}@{revision[:12]}")
        return None

    def warm_up(self) -> None:
        """Fetch the weights, start the service and wait until it is ready (idempotent; stopped when the task's pages
        are through)."""
        if self._proc is not None:
            return
        try:
            model_dir = self.prepare()
        except Exception as e:
            raise ServerError(f"service of {self.ref}: its weights could not be fetched: {type(e).__name__}: {e}") from e
        cmd = self.command(model_dir)
        logger.info("service of {preset}: {command}", preset=self.ref, command=" ".join(cmd))
        # its own process group (stopped as a whole); its output on stderr, like saturate's servers
        proc = subprocess.Popen(cmd, env=self.environment(), start_new_session=True, stdout=2)
        self._proc = proc
        try:
            self.wait_ready(proc)
        except BaseException:
            _stop(self)
            raise

    def wait_ready(self, proc) -> None:
        """Wait until every health URL has answered 200, in order; ``ServerError`` when the service exits first or
        ``boot_timeout`` passes."""
        deadline = time.monotonic() + self.boot_timeout
        for url in self.health():
            last = None
            while True:
                if proc.poll() is not None:
                    raise ServerError(f"service of {self.ref} exited with code {proc.returncode} before {url} was up")
                try:
                    with urllib.request.urlopen(url, timeout=5) as r:
                        if r.status == 200:
                            break
                except (OSError, urllib.error.HTTPError) as e:
                    last = e
                if time.monotonic() > deadline:
                    raise ServerError(f"service of {self.ref}: {url} not ready after {self.boot_timeout} s: {last}")
                time.sleep(2)
        logger.info("service of {preset} ready", preset=self.ref)

    def run(self, data, rank: int = 0, world_size: int = 1):
        self.warm_up()
        try:
            yield from data
        finally:
            _stop(self)

    def __getstate__(self):           # never pickle a running service
        return {**self.__dict__, "_proc": None}


def _stop(block, grace: float = 30.0) -> None:
    """Stop the service's process group: SIGTERM, then SIGKILL after ``grace`` seconds; the leader is reaped."""
    proc, block._proc = block._proc, None
    if proc is None:
        return
    pgid = proc.pid                   # start_new_session: the service leads its own group
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 10.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
        try:                          # the leader is gone; its children may not be
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
