"""Blocks that host models for a task's served blocks: ``ServeModels`` starts ``linecaster serve``,
``ServeChatModel`` starts vLLM or SGLang for a ``ChatPageStep`` (both through saturate's ``Engine``) when the
task starts, and stops it when all its pages are through. For a pipeline that brings
its own GPU, e.g. one HF Job per datatrove task.

Put it **last** in the pipeline (after the writer): datatrove chains generators, so the last block's
generator is the one that lives until every page has passed every block. Placed before the served
blocks, it would stop the server as soon as the reader ran dry, with requests still in flight."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep


class ServeModels(PipelineStep):
    type = "🔠 - LINECASTER"
    name = "🖥️ serve models"

    def __init__(self, models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
                 max_queue: int = 16):
        super().__init__()
        self.models, self.port, self.python, self.boot_timeout, self.max_queue = models, port, python, boot_timeout, max_queue

    def run(self, data, rank: int = 0, world_size: int = 1):
        from ..serve import engine

        with self.track_time("boot"):
            server = engine(self.models, self.port, self.python, self.boot_timeout, self.max_queue)
            server.__enter__()
        try:
            yield from data
        finally:
            server.__exit__(None, None, None)


class ServeChatModel(PipelineStep):
    """Start a chat VLM server for a task's ``ChatPageStep``, through saturate's ``Engine``. The spec's
    ``server`` picks it:

    * ``"vllm"``: ``vllm serve <spec.model> --host HOST --port PORT <spec.vllm_args(...)>``;
    * ``"sglang"``: ``PYTHON -m sglang.launch_server --model-path <spec.model> --host HOST --port PORT
      --enable-metrics <spec.sglang_args(...)>`` (metrics on: saturate reads SGLang's queue gauges).

    Like ``ServeModels``, put it **last** in the pipeline (after the writer).

    ``vllm`` is the vLLM command (default ``vllm`` on PATH, e.g. from the job image or a
    ``uv run --with vllm==...`` environment); ``python`` the Python that has SGLang (default ``python3``
    on PATH). ``gpu_memory_utilization`` (for SGLang: ``--mem-fraction-static``) and ``extra_args`` are the
    deployment's choices on top of the spec's flags. The server is ready when it answers a trial chat
    request (saturate's alive-only gate).

    Before the server starts: the spec's ``server_packages`` are installed into the server's Python
    (``uv pip install --python <that Python> ...``; e.g. a patched SGLang wheel), and for a spec with
    ``revision_flag = False`` (the server cannot be given ``--revision`` and loads the default branch) the
    block refuses to start unless the default branch's files equal the pinned revision's
    (``check_default_branch``). ``server_env`` goes into the server's environment.

    ``outside_venv``: start the server without this interpreter's virtual environment (``VIRTUAL_ENV``
    unset, its ``bin`` taken off ``PATH``), for a job image whose own Python has the server while the
    pipeline runs in a uv environment on top (HF Jobs); the server's helpers (``ninja``, ``python``) then
    come from the image, and ``python`` is looked up on that ``PATH``."""

    type = "🔠 - LINECASTER"
    name = "🖥️ serve chat model"

    def __init__(self, spec, port: int = 8000, host: str = "127.0.0.1", gpu_memory_utilization: float | None = None,
                 extra_args: list[str] | None = None, vllm: str = "vllm", boot_timeout: int = 1800,
                 outside_venv: bool = False, python: str = "python3"):
        super().__init__()
        self.spec, self.port, self.host = spec, port, host
        self.gpu_memory_utilization, self.extra_args = gpu_memory_utilization, list(extra_args or [])
        self.vllm, self.boot_timeout, self.outside_venv, self.python = vllm, boot_timeout, outside_venv, python

    @property
    def server(self) -> str:
        return getattr(self.spec, "server", "vllm")

    def command(self, python: str | None = None) -> list[str]:
        """The server command. For vLLM behind ``bash -c '<setup>; exec vllm serve ...'`` when the spec has a
        ``serve_setup`` script (run with ``VLLM`` set to the server command, ``set -euo pipefail``)."""
        if self.server == "vllm":
            cmd = [self.vllm, "serve", self.spec.model, "--host", self.host, "--port", str(self.port),
                   *self.spec.vllm_args(self.gpu_memory_utilization, self.extra_args)]
            setup = getattr(self.spec, "serve_setup", lambda: None)()
            if not setup:
                return cmd
            import shlex

            return ["bash", "-c", f"set -euo pipefail\nVLLM={shlex.quote(self.vllm)}\n{setup}\nexec {shlex.join(cmd)}"]
        if self.server == "sglang":
            return [python or self.python, "-m", "sglang.launch_server", "--model-path", self.spec.model,
                    "--host", self.host, "--port", str(self.port), "--enable-metrics",
                    *self.spec.sglang_args(self.gpu_memory_utilization, self.extra_args)]
        raise ValueError(f"unknown server {self.server!r} for {self.spec.model} (vllm or sglang)")

    def server_path(self) -> str:
        """``PATH`` for the server: this one, without this interpreter's ``bin`` with ``outside_venv``."""
        import os
        import sys

        path = os.environ.get("PATH", "")
        if not self.outside_venv:
            return path
        own = {os.path.realpath(os.path.join(sys.prefix, "bin"))}
        if os.environ.get("VIRTUAL_ENV"):
            own.add(os.path.realpath(os.path.join(os.environ["VIRTUAL_ENV"], "bin")))
        return os.pathsep.join(p for p in path.split(os.pathsep) if os.path.realpath(p) not in own)

    def launch_command(self, python: str | None = None) -> list[str]:
        """``command()``, behind ``env [-u VIRTUAL_ENV PATH=...] [spec.server_env...]`` when either applies."""
        cmd = self.command(python)
        env = [f"{k}={v}" for k, v in (getattr(self.spec, "server_env", None) or {}).items()]
        if self.outside_venv:
            env = ["-u", "VIRTUAL_ENV", f"PATH={self.server_path()}", *env]
        return ["env", *env, *cmd] if env else cmd

    def server_python(self) -> str:
        """The absolute path of ``python`` on the server's ``PATH``; it must import the server (SGLang)."""
        import shutil
        import subprocess

        py = shutil.which(self.python, path=self.server_path())
        if not py or subprocess.run([py, "-c", "import sglang"], capture_output=True, check=False).returncode != 0:
            raise RuntimeError(f"no {self.python} with sglang on the server's PATH (an SGLang image, outside_venv=True)")
        return py

    def install_commands(self, python: str, uv: str = "uv") -> list[list[str]]:
        """One ``uv pip install`` per entry of the spec's ``server_packages``, into ``python``."""
        return [[uv, "pip", "install", "-q", "--python", python, *args] for args in self.spec.server_packages()]

    def prepare(self) -> str | None:
        """Everything before the server starts: the pin check, the server's packages. Returns the server's
        Python for SGLang (``None`` for vLLM)."""
        import os
        import subprocess

        spec = self.spec
        if spec.revision and not getattr(spec, "revision_flag", True):
            check_default_branch(spec.model, spec.revision, getattr(spec, "pin_ignore", ()))
        python = self.server_python() if self.server == "sglang" else None
        installs = self.install_commands(python or self.python)
        if installs:
            env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
            for cmd in installs:
                subprocess.run(cmd, check=True, env=env)
        return python

    def run(self, data, rank: int = 0, world_size: int = 1):
        from saturate import Engine

        with self.track_time("boot"):
            python = self.prepare()
            server = Engine(self.spec.model, engine=self.server, port=self.port, boot_timeout=self.boot_timeout,
                            cmd=self.launch_command(python))
            server.__enter__()
        try:
            yield from data
        finally:
            server.__exit__(None, None, None)


def check_default_branch(model: str, revision: str, ignore=()) -> None:
    """Refuse (``RuntimeError``) unless every file on ``model``'s default branch, other than those matching
    an ``ignore`` glob, has the same git blob as at ``revision`` (and no file is missing on either side):
    for a server that loads the default branch, the weights, config and tokenizer are then the pinned ones."""
    from fnmatch import fnmatch

    from huggingface_hub import HfApi

    api = HfApi()

    def blobs(rev: str) -> dict[str, str]:
        info = api.model_info(model, revision=rev, files_metadata=True)
        return {f.rfilename: f.blob_id for f in info.siblings or []
                if not any(fnmatch(f.rfilename, g) for g in ignore)}

    pinned, head = blobs(revision), blobs("main")
    differ = sorted(k for k in set(pinned) | set(head) if pinned.get(k) != head.get(k))
    if differ:
        raise RuntimeError(f"{model}: the default branch differs from the pinned {revision} in {differ[:10]}; "
                           "the server loads the default branch, so re-pin deliberately")
