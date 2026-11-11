"""Blocks that host models for a task's served blocks: ``ModelServer`` starts ``linecaster serve``,
``ChatModelServer`` starts vLLM or SGLang for the ``Chat`` backend of a ``PageRecognizer`` or ``RegionRecognizer``
(both through saturate's ``Engine``) when the task starts, and stops it when all its pages are through. For a
pipeline that brings its own GPU, e.g. one HF Job per datatrove task.

Put it **last** in the pipeline (after the writer): datatrove chains generators, so the last block's
generator is the one that lives until every page has passed every block. Placed before the served
blocks, it would stop the server as soon as the reader ran dry, with requests still in flight."""
from __future__ import annotations

from datatrove.pipeline.base import PipelineStep
from loguru import logger

from ...errors import CatalogError, PipelineConfigError, ServerError
from ..base.contract import Contracted

#: vLLM's switch for its FlashInfer sampler, which compiles its kernels when it is first used (JIT) and so needs a
#: CUDA toolkit (``nvcc``); without one vLLM fails at its first request ("Could not find nvcc")
FLASHINFER_SAMPLER = "VLLM_USE_FLASHINFER_SAMPLER"
#: variables that name a CUDA toolkit
CUDA_TOOLKIT_VARS = ("CUDA_HOME", "CUDA_PATH")
_flashinfer_logged = False


class ModelServer(Contracted, PipelineStep):
    """Starts ``linecaster serve`` inside the task for its served model blocks, through saturate's ``Engine``.

    The server starts in ``warm_up()`` and is ready when every model is loaded; it stops when the task's pages are
    through. Its environment carries what the observers ask for (the task's trace file). A server that does not
    start fails the task (``ServerError``). Its role is ``server`` and its unit ``any``: it touches no part. It goes
    **last** in the pipeline (after the writer): datatrove chains generators, and only the last one lives until every
    page is written.

    Args:
        models: the models to host, one dict each: ``{"name", "preset"}`` (a catalog preset, optional
            ``"overrides"`` over its options) or ``{"name", "spec", "kwargs"}`` (an engine class ``module:Class``).
            A served model block asks for its model by ``name``.
        port: the port the server listens on (loopback).
        python: the Python that runs ``linecaster serve -m linecaster.cli``; default this interpreter. Ignored with
            ``script``.
        boot_timeout: seconds the server may take until every model is loaded.
        max_queue: requests a model accepts before answering 429.
        script: a pipeline script whose ``serve`` command starts the server in the script's own environment
            (``uv run --script <script> serve``); default: ``python``.
    """

    type = "🔠 - LINECASTER"
    name = "🖥️ model server"
    unit, role = "any", "server"
    docs_args = {"models": []}

    def __init__(self, models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
                 max_queue: int = 16, script: str | None = None):
        super().__init__()
        self.models, self.port, self.python, self.boot_timeout, self.max_queue = models, port, python, boot_timeout, max_queue
        self.script = script
        self._server = None

    def warm_up(self) -> None:
        """Start the server and wait until it answers (idempotent; stopped when the task's pages are through)."""
        if self._server is not None:
            return
        from ...serve import engine

        env = self._observers.environment() if self._observers is not None else {}
        server = engine(self.models, self.port, self.python, self.boot_timeout, self.max_queue, self.script, env)
        try:
            server.__enter__()
        except Exception as e:
            raise ServerError(f"linecaster serve on port {self.port} did not start: {type(e).__name__}: {e}") from e
        self._server = server

    def run(self, data, rank: int = 0, world_size: int = 1):
        self.warm_up()
        try:
            yield from data
        finally:
            _stop(self)

    def __getstate__(self):           # never pickle a running server
        return {**self.__dict__, "_server": None}


class ChatModelServer(Contracted, PipelineStep):
    """Starts a chat VLM server (vLLM or SGLang) inside the task for its ``Chat`` backends, through saturate's ``Engine``.

    The command comes from the chat preset's ``serve`` block (server, flags, environment, packages), whose ``server``
    picks it:

    * ``"vllm"``: ``vllm serve <spec.model> --host HOST --port PORT <spec.vllm_args(...)>`` (behind ``bash -c`` when
      the preset has a setup script);
    * ``"sglang"``: ``PYTHON -m sglang.launch_server --model-path <spec.model> --host HOST --port PORT
      --enable-metrics <spec.sglang_args(...)>`` (metrics on: saturate reads SGLang's queue gauges).

    The server starts in ``warm_up()`` and is ready when it answers a trial chat request (saturate's alive-only
    gate); it stops when the task's pages are through. Before it starts, the preset's ``server_packages`` are
    installed into the server's Python (``uv pip install --python <that Python> ...``), and for a preset with
    ``revision_flag: false`` (the server cannot be given ``--revision`` and loads the default branch) the block
    refuses to start unless the default branch's files equal the pinned revision's (``check_default_branch``); the
    preset's ``server_env`` goes into the server's environment. With OTLP configured, vLLM traces too
    (``tracing_args``). On a machine without a CUDA toolkit (no ``nvcc`` on the server's ``PATH``, neither
    ``CUDA_HOME`` nor ``CUDA_PATH`` set) vLLM starts with ``VLLM_USE_FLASHINFER_SAMPLER=0`` (``flashinfer_env``),
    unless that variable is set already: FlashInfer's sampler compiles its kernels at first use and fails without
    ``nvcc``. A server that does not start fails the task (``ServerError``).

    The server listens on ``port`` (8000 for ``Chat`` by default), so two runs on one machine collide unless each
    gets its own port and its own GPU (``CUDA_VISIBLE_DEVICES``): a second vLLM on a GPU that one already uses does
    not get its memory share, and a second server on the same port does not start.

    Its role is ``server`` and its unit ``any``: it touches no part. Like ``ModelServer``, it goes **last** in the
    pipeline (after the writer): datatrove chains generators, and only the last one lives until every page is
    written.

    Args:
        spec: the chat preset's adapter (``linecaster.adapters.chat_model``) or the preset's ref (``id@edition``).
        port: the port the server listens on; ``Chat`` without an endpoint asks on 8000.
        host: the address the server binds to; default loopback only.
        gpu_memory_utilization: the share of GPU memory the server may take (for SGLang ``--mem-fraction-static``);
            default the preset's flags alone. The deployment's choice.
        extra_args: more server flags, after the preset's.
        vllm: the vLLM command (default ``vllm`` on ``PATH``, e.g. from the job image or a ``uv run --with
            vllm==...`` environment).
        boot_timeout: seconds the server may take to answer.
        outside_venv: start the server without this interpreter's virtual environment (``VIRTUAL_ENV`` unset, its
            ``bin`` taken off ``PATH``), for a job image whose own Python has the server while the pipeline runs in a
            uv environment on top (HF Jobs); the server's helpers (``ninja``, ``python``) then come from the image.
        python: the Python that has SGLang (default ``python3``, looked up on the server's ``PATH``, then in the
            usual image locations).
    """

    type = "🔠 - LINECASTER"
    name = "🖥️ chat model server"
    unit, role = "any", "server"
    docs_args = {"spec": "lightonocr-2-1b@1"}

    def __init__(self, spec, port: int = 8000, host: str = "127.0.0.1", gpu_memory_utilization: float | None = None,
                 extra_args: list[str] | None = None, vllm: str = "vllm", boot_timeout: int = 1800,
                 outside_venv: bool = False, python: str = "python3"):
        super().__init__()
        if isinstance(spec, str):
            from ...adapters import chat_model

            spec = chat_model(spec)
        self.spec, self.port, self.host = spec, port, host
        self.gpu_memory_utilization, self.extra_args = gpu_memory_utilization, list(extra_args or [])
        self.vllm, self.boot_timeout, self.outside_venv, self.python = vllm, boot_timeout, outside_venv, python
        self._server = None

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
        raise PipelineConfigError(f"unknown server {self.server!r} for {self.spec.model} (vllm or sglang)")

    def server_path(self) -> str:
        """``PATH`` for the server: this one, without this interpreter's ``bin`` with ``outside_venv``."""
        import os
        import sys

        path = os.environ.get("PATH", "")
        if not self.outside_venv:
            return path
        # only this interpreter's own environment: an image may set VIRTUAL_ENV to the environment that has
        # the server (the SGLang image: /opt/sglang), which must stay on the PATH
        own = os.path.realpath(os.path.join(sys.prefix, "bin"))
        return os.pathsep.join(p for p in path.split(os.pathsep) if os.path.realpath(p) != own)

    def tracing_args(self) -> tuple[list[str], dict[str, str]]:
        """vLLM's own tracing when the ``OTEL_*`` variables ask for an OTLP export: ``--otlp-traces-endpoint`` (the
        traces URL) with the protocol linecaster uses (``OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf``, vLLM's
        default is gRPC). vLLM continues a ``traceparent`` it gets in a request's headers, which saturate cannot set
        per request: its spans are traces of their own. Nothing for SGLang, or without OTLP."""
        from ...tracing import otlp_traces_endpoint

        endpoint = otlp_traces_endpoint()
        if self.server != "vllm" or endpoint is None:
            return [], {}
        import os

        protocol = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or "http/protobuf"
        return ["--otlp-traces-endpoint", endpoint], {"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": protocol}

    def flashinfer_env(self) -> dict[str, str]:
        """``{"VLLM_USE_FLASHINFER_SAMPLER": "0"}`` for vLLM on a machine without a CUDA toolkit: no ``nvcc`` on the
        server's ``PATH`` and neither ``CUDA_HOME`` nor ``CUDA_PATH`` set, unless the variable is set already (in
        this environment or the preset's ``server_env``); else nothing."""
        import os
        import shutil

        if self.server != "vllm" or FLASHINFER_SAMPLER in os.environ:
            return {}
        if FLASHINFER_SAMPLER in (getattr(self.spec, "server_env", None) or {}):
            return {}
        if any(os.environ.get(v) for v in CUDA_TOOLKIT_VARS) or shutil.which("nvcc", path=self.server_path()):
            return {}
        return {FLASHINFER_SAMPLER: "0"}

    def launch_command(self, python: str | None = None) -> list[str]:
        """``command()``, behind ``env [-u VIRTUAL_ENV PATH=...] [spec.server_env...]`` when either applies; with
        vLLM's tracing arguments (``tracing_args``) when OTLP is configured, and ``flashinfer_env()``."""
        cmd = self.command(python)
        args, trace_env = self.tracing_args()
        if args:
            import shlex

            cmd = cmd + args if cmd[0] != "bash" else [*cmd[:-1], cmd[-1] + " " + shlex.join(args)]
        env = [f"{k}={v}" for k, v in {**(getattr(self.spec, "server_env", None) or {}), **trace_env,
                                       **self.flashinfer_env()}.items()]
        if self.outside_venv:
            env = ["-u", "VIRTUAL_ENV", f"PATH={self.server_path()}", *env]
        return ["env", *env, *cmd] if env else cmd

    #: where server images usually keep their Python, tried after every python on the server's PATH
    SERVER_PYTHONS = ("/opt/sglang/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3")

    def server_python(self) -> str:
        """The first Python that imports the server (SGLang): every ``python`` on the server's ``PATH`` in
        order, then ``SERVER_PYTHONS``. The import check runs without this interpreter's environment
        variables (``VIRTUAL_ENV``, ``PYTHONPATH``, ``PYTHONHOME``). The error lists every candidate."""
        import os
        import subprocess

        path = self.server_path()
        found = []
        for d in path.split(os.pathsep):
            c = os.path.join(d, self.python)
            if os.path.isfile(c) and os.access(c, os.X_OK) and c not in found:
                found.append(c)
        found += [c for c in self.SERVER_PYTHONS if os.path.isfile(c) and c not in found]
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
        env["PATH"] = path
        tried = []
        for py in found:
            r = subprocess.run([py, "-c", "import sglang"], capture_output=True, text=True, check=False, env=env)
            if r.returncode == 0:
                return py
            tried.append(f"{py}: {(r.stderr.strip().splitlines() or ['?'])[-1][:200]}")
        raise ServerError(f"no {self.python} with sglang (outside_venv={self.outside_venv}); PATH={path}; "
                           f"tried: {tried or 'none found'}")

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

    def warm_up(self) -> None:
        """Prepare and start the server, and wait until it answers (idempotent; stopped when the task's pages are
        through)."""
        if self._server is not None:
            return
        from saturate import Engine

        python = self.prepare()
        global _flashinfer_logged
        if self.flashinfer_env() and not _flashinfer_logged:
            logger.info("no CUDA toolkit here (no nvcc on PATH, no CUDA_HOME or CUDA_PATH): vLLM starts with "
                        "{var}=0, since FlashInfer's sampler would compile its kernels with nvcc", var=FLASHINFER_SAMPLER)
            _flashinfer_logged = True
        server = Engine(self.spec.model, engine=self.server, port=self.port, boot_timeout=self.boot_timeout,
                        cmd=self.launch_command(python))
        try:
            server.__enter__()
        except Exception as e:
            raise ServerError(f"{self.server} for {self.spec.model} on port {self.port} did not start: "
                              f"{type(e).__name__}: {e}") from e
        self._server = server

    def run(self, data, rank: int = 0, world_size: int = 1):
        self.warm_up()
        try:
            yield from data
        finally:
            _stop(self)

    def __getstate__(self):           # never pickle a running server
        return {**self.__dict__, "_server": None}


def _stop(block) -> None:
    """Stop a server block's server, if it runs."""
    server, block._server = block._server, None
    if server is not None:
        server.__exit__(None, None, None)


def check_default_branch(model: str, revision: str, ignore=()) -> None:
    """Refuse (``CatalogError``) unless every file on ``model``'s default branch, other than those matching
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
        raise CatalogError(f"{model}: the default branch differs from the pinned {revision} in {differ[:10]}; "
                           "the server loads the default branch, so re-pin deliberately")
