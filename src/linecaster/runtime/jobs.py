"""Hugging Face Jobs helpers for linecaster pipelines (on datatrove's ``JobsPipelineExecutor``).

* ``dependencies(commit, script, engines=True)``: what a Job installs with ``uv run --with`` to run a pipeline,
  read from the pipeline script's inline metadata (``ENGINE_SCRIPT``, the modular pipeline script, for a derivative
  that needs the engine packages without a script of its own): its dependencies with the script's sources spelled out as URLs at
  ``commit`` (linecaster and the engine packages from GitHub's source archive, the kraken fork with
  git+, the OpenCV stub: PaddleX pins OpenCV's GUI build, which needs libGL; the Jobs image has none)
  and its version pins, for the packages its lock resolves.
* ``JobsExecutor``: datatrove's ``JobsPipelineExecutor`` with the tasks' logs as JSON lines (``runtime.logs``;
  the pipeline scripts set ``LINECASTER_LOG_JSON`` in their Jobs' environment); the other two build on it.
* ``WheelJobsExecutor``: ``JobsExecutor`` that also mounts volumes into every Job. A private
  derivative ships its code as a wheel: ``upload_wheel`` puts it in a bucket folder, the executor
  mounts that folder read-only (authorized by the Job's own HF token; no credential is persisted)
  and ``uv run --with <mount>/<wheel>`` installs it. ``wheel_volume`` builds the mount.
* ``GPUJobsExecutor``: one Job per ``gpus`` datatrove tasks on a multi-GPU flavor (``l4x4``,
  ``l40sx8``): the Job runs its tasks side by side, one process each; task *i* of a Job gets GPU *i*
  (``CUDA_VISIBLE_DEVICES``) and its own loopback port for the servers its pipeline starts.

``uv run --with`` ignores ``[tool.uv.sources]``, so a pipeline script's sources are spelled out as URLs.
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit

import subprocess
from pathlib import Path

from datatrove.executor import JobsPipelineExecutor

from ..errors import PipelineConfigError

REPO = "https://github.com/storytracer/linecaster"
#: the checkout the launcher runs from (pipelines, engines, stubs)
ROOT = Path(__file__).resolve().parents[3]
#: the modular pipeline script (in the checkout): its metadata lists every engine package with its sources and pins,
#: for ``dependencies(commit, ENGINE_SCRIPT)`` from a derivative's own pipeline
ENGINE_SCRIPT = ROOT / "pipelines" / "transcribe_modular.py"
WHEEL_MOUNT = "/wheels"
_SCRIPT = re.compile(r"(?m)^# /// script\s*$\n(?P<content>(^#(| .*)$\n)+)^# ///\s*$")


def at_commit(path: str | Path, commit: str | None) -> str:
    """The text of ``path`` as it is at linecaster ``commit``, so a Job's dependencies come from the commit it
    installs and not from whatever the checkout holds now. A file outside the checkout (a derivative's own), or a
    commit the checkout does not know (not fetched, or not a git checkout), is read as it is on disk, with a
    warning for the latter."""
    import subprocess

    path = Path(path).resolve()
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.read_text()
    if commit:
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        from loguru import logger

        logger.warning("linecaster commit {commit} is not in the checkout {root}: {rel} is read as it is on disk, "
                       "which may not match the commit the Jobs install", commit=commit, root=ROOT, rel=rel)
    return path.read_text()


def script_metadata(path: str | Path, commit: str | None = None) -> dict:
    """The inline metadata (PEP 723) of the script at ``path`` (at linecaster ``commit``: ``at_commit``)."""
    import tomllib

    m = _SCRIPT.search(at_commit(path, commit))
    if not m:
        raise PipelineConfigError(f"{path}: no '# /// script' block")
    return tomllib.loads("".join(line[2:] if line.startswith("# ") else line[1:]
                                 for line in m.group("content").splitlines(keepends=True)))


def _name(requirement: str) -> str:
    return re.split(r"[\s\[<>=!~;@]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def dependencies(commit: str, script: str | Path | None = None, engines: bool = True) -> list[str]:
    """``uv run --with`` requirements for a Job at linecaster ``commit`` (must be pushed) from the inline
    metadata of ``script`` (a pipeline): its dependencies with the script's sources spelled out as URLs at
    ``commit`` (``url`` sources as they are) and its version pins, for the packages its lock resolves, all read
    from the script and lock as they are at ``commit`` (``at_commit``).
    ``engines=False`` (a VLM pipeline whose image brings vLLM, or a CPU pipeline): linecaster with the script's
    extras and its ``url``-source dependencies (pybookget), no engines and no pins; without a script, linecaster
    alone. Engines without a script are a ``PipelineConfigError``: give ``ENGINE_SCRIPT`` (the modular pipeline's
    engines) or the pipeline's own script.

    linecaster is installed from GitHub's source archive (``.../archive/<rev>.tar.gz``), not with ``git+``:
    some images (``vllm/vllm-openai``) have uv but no git executable; pybookget the same way (a ``url``
    source). The kraken fork still needs git (its version comes from git history); the default Jobs image,
    which engine Jobs use, has it."""
    import tomllib

    repo = f"{REPO}/archive/{commit}.tar.gz"
    if script is None:
        if engines:
            raise PipelineConfigError("dependencies() without a script has no engine packages: give the pipeline's "
                                      "script, ENGINE_SCRIPT for the modular pipeline's engines, or engines=False "
                                      "for linecaster alone")
        return [f"linecaster @ {repo}"]
    script = Path(script).resolve()
    meta = script_metadata(script, commit)
    uv = meta.get("tool", {}).get("uv", {})
    sources = {_name(k): v for k, v in uv.get("sources", {}).items()}
    deps, light = [], []
    for req in meta.get("dependencies", []):
        src = sources.get(_name(req))
        if src and "url" in src:
            deps.append(f"{_name(req)} @ {src['url']}")
            light.append(deps[-1])
        elif src and "path" in src:
            sub = (script.parent / src["path"]).resolve().relative_to(ROOT).as_posix()
            extras = req[len(_name(req)):].split(";")[0].strip() if "[" in req else ""
            if _name(req) == "linecaster":   # a Job does not use Ray
                kept = [e for e in extras.strip("[]").split(",") if e.strip() and e.strip() != "ray"]
                extras = f"[{','.join(kept)}]" if kept else ""
            deps.append(f"{_name(req)}{extras} @ {repo}" + (f"#subdirectory={sub}" if sub != "." else ""))
            if _name(req) == "linecaster":
                light.append(deps[-1])
        elif src and "git" in src:
            deps.append(f"{_name(req)} @ git+{src['git']}@{src['rev']}")
        else:
            deps.append(req)
    if not engines:
        return light or [f"linecaster @ {repo}"]
    # --with installs what it is given: pin only what the script's environment really contains
    lock = script.with_name(script.name + ".lock")
    resolved = {p["name"] for p in tomllib.loads(at_commit(lock, commit))["package"]}
    deps += [c for c in uv.get("constraint-dependencies", []) if _name(c) in resolved]
    return deps


def bucket_parts(url: str) -> tuple[str, str]:
    """``hf://buckets/ns/name[/prefix]`` -> (``ns/name``, ``prefix``)."""
    parts = url.removeprefix("hf://buckets/").strip("/").split("/")
    return "/".join(parts[:2]), "/".join(parts[2:])


def wheel_volume(folder_url: str, mount_path: str = WHEEL_MOUNT) -> dict:
    """A read-only bucket volume for ``WheelJobsExecutor(volumes=[...])`` from ``hf://buckets/ns/name/path``."""
    bucket, path = bucket_parts(folder_url)
    vol = {"type": "bucket", "source": bucket, "mount_path": mount_path, "read_only": True}
    if path:
        vol["path"] = path
    return vol


def build_wheel(project: str | Path, out_dir: str | Path | None = None) -> Path:
    """``uv build --wheel`` for the project at ``project``; returns the newest wheel."""
    project = Path(project)
    out = Path(out_dir) if out_dir else project / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=project, check=True,
                   capture_output=True, text=True)
    return max(out.glob("*.whl"), key=lambda p: p.stat().st_mtime)


def upload_wheel(wheel: str | Path, folder_url: str) -> str:
    """Upload ``wheel`` to ``folder_url`` (``hf://buckets/...``); returns its URL."""
    from huggingface_hub import HfFileSystem

    wheel = Path(wheel)
    url = f"{folder_url.rstrip('/')}/{wheel.name}"
    HfFileSystem().put_file(str(wheel), url)
    return url


class JobsExecutor(JobsPipelineExecutor):
    """datatrove's ``JobsPipelineExecutor``, its tasks logging JSON lines when ``LINECASTER_LOG_JSON`` is set in
    the Job (``linecaster.runtime.logs.add_task_logger`` in place of datatrove's)."""

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        import datatrove.executor.jobs as datatrove_jobs

        from .logs import add_task_logger

        original = datatrove_jobs.add_task_logger
        datatrove_jobs.add_task_logger = add_task_logger
        try:
            return super()._run_for_rank(rank, local_rank, node_rank)
        finally:
            datatrove_jobs.add_task_logger = original


class WheelJobsExecutor(JobsExecutor):
    """``JobsExecutor`` that mounts ``volumes`` (dicts of ``huggingface_hub.Volume`` fields)
    into every Job it launches."""

    def __init__(self, *args, volumes: list[dict] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.volumes = list(volumes or [])

    def _submit_array_index(self, array_index: int, pik_path: str, token: str) -> str:
        import huggingface_hub
        from huggingface_hub import Volume

        original = huggingface_hub.run_uv_job
        volumes = [Volume(**v) for v in self.volumes]

        def run_uv_job(*args, **kwargs):
            kwargs["volumes"] = [*(kwargs.get("volumes") or []), *volumes]
            return original(*args, **kwargs)

        huggingface_hub.run_uv_job = run_uv_job     # the parent imports it at call time
        try:
            return super()._submit_array_index(array_index, pik_path, token)
        finally:
            huggingface_hub.run_uv_job = original


def point_to_gpu(pipeline: list, local: int) -> list:
    """The pipeline for task ``local`` of a multi-GPU machine: every block that starts a server
    (``ModelServer``, ``ChatModelServer``: attribute ``port``) and every served backend on loopback
    moves ``local`` ports up, so each GPU has its own servers and clients (a layout server on 8100 and
    vLLM on 8000 become 8103 and 8003 on GPU 3)."""
    from ..backends import Chat, Served
    from ..blocks.servers.serve import ChatModelServer, ModelServer

    pipeline = deepcopy(pipeline)
    for step in pipeline:
        if isinstance(step, (ModelServer, ChatModelServer)):
            step.port += local
        backend = getattr(step, "backend", None)
        if isinstance(backend, (Served, Chat)):
            u = urlsplit(backend.endpoint)
            if u.hostname in ("127.0.0.1", "localhost") and u.port:
                backend.endpoint = urlunsplit(u._replace(netloc=f"{u.hostname}:{u.port + local}"))
    return pipeline


class GPUJobsExecutor(JobsExecutor):
    """``JobsExecutor`` for multi-GPU flavors: each Job takes ``gpus`` datatrove tasks and runs
    them at the same time, one forked process per task, task *i* on GPU *i* with its servers *i* ports
    up (``point_to_gpu``). ``tasks`` should be a multiple of ``gpus``. The Job fails if
    any of its tasks fails; datatrove's completion markers make a rerun skip the finished ones."""

    def __init__(self, *args, gpus: int, **kwargs):
        super().__init__(*args, tasks_per_job=gpus, **kwargs)
        self.gpus = gpus

    def _run_array_index(self, array_index: int):
        import multiprocessing

        with self.logging_dir.open("ranks_to_run.json", "r") as f:
            all_ranks = json.load(f)
        start = array_index * self.tasks_per_job
        ranks = all_ranks[start:start + self.tasks_per_job]
        ctx = multiprocessing.get_context("fork")   # the Job's parent process never touches CUDA
        procs = [ctx.Process(target=self._run_on_gpu, args=(rank, local), name=f"gpu{local}")
                 for local, rank in enumerate(ranks)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        failed = [rank for p, rank in zip(procs, ranks) if p.exitcode != 0]
        if failed:
            raise RuntimeError(f"tasks {failed} failed in Job {array_index}")

    def _run_on_gpu(self, rank: int, local: int) -> None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(local)
        self.pipeline = point_to_gpu(self.pipeline, local)
        self._run_for_rank(rank, local_rank=local)
