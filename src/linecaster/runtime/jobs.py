"""Hugging Face Jobs helpers for linecaster pipelines (on datatrove's ``JobsPipelineExecutor``).

* ``dependencies(commit, script, engines=True)``: what a Job installs to run a pipeline script (linecaster's or a
  derivative's), as ``Dependencies``: its requirements with every source spelled out as a URL, the sources of the
  packages it installs taken from its lock (linecaster and the engine packages of the checkout from GitHub's source
  archive at ``commit``, git sources at their tag, branch or rev, the kraken fork, the OpenCV stub: PaddleX pins
  OpenCV's GUI build, which needs libGL; the Jobs image has none), every other package pinned at the lock's
  version, and the script's overrides.
* ``JobsExecutor``: datatrove's ``JobsPipelineExecutor`` with the tasks' logs as JSON lines (``runtime.logs``;
  the pipeline scripts set ``LINECASTER_LOG_JSON`` in their Jobs' environment), and with ``Dependencies`` each Job
  runs a uv script that carries them (``Dependencies.script``); ``GPUJobsExecutor`` builds on it.
* ``GPUJobsExecutor``: one Job per ``gpus`` datatrove tasks on a multi-GPU flavor (``l4x4``,
  ``l40sx8``): the Job runs its tasks side by side, one process each; task *i* of a Job gets GPU *i*
  (``CUDA_VISIBLE_DEVICES``) and its own loopback port for the servers its pipeline starts.

``uv run --with`` ignores ``[tool.uv.sources]``, so a pipeline script's sources are spelled out as URLs. It also
ignores constraints and overrides (``UV_CONSTRAINT``, ``UV_OVERRIDE``, a ``uv.toml``'s ``constraint-dependencies``),
which only a script's own ``[tool.uv]`` brings to ``uv run``: hence the launcher script.
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from datatrove.executor import JobsPipelineExecutor

from ..errors import PipelineConfigError

REPO = "https://github.com/storytracer/linecaster"
#: the checkout the launcher runs from (pipelines, engines, stubs)
ROOT = Path(__file__).resolve().parents[3]
#: a PEP 508 requirement: name, extras, the version or URL, the marker
_REQ = re.compile(r"\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[(?P<extras>[^\]]*)\])?(?P<rest>[^;]*)(?:;(?P<marker>.*))?$")
_SCRIPT = re.compile(r"(?m)^# /// script\s*$\n(?P<content>(^#(| .*)$\n)+)^# ///\s*$")


@dataclass(frozen=True)
class Dependencies:
    """What a Job installs (``dependencies``).

    Attributes:
        requirements: PEP 508 requirements, every source spelled out as a URL.
        constraints: ``name==version`` for every package the script's lock takes from an index and the requirements
            reach (a package the lock holds at several versions: each with its ``resolution-markers``), so a Job
            resolves the lock's versions; constraints only bound what the requirements bring.
        overrides: the script's ``[tool.uv] override-dependencies``, without which its lock would not resolve.
    """

    requirements: list[str]
    constraints: list[str] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)

    def script(self, body: str) -> str:
        """A uv script (PEP 723 inline metadata, then ``body``) whose environment is these dependencies: its
        ``dependencies`` the requirements, its ``[tool.uv]`` ``constraint-dependencies`` and
        ``override-dependencies`` the constraints and overrides."""
        def array(key: str, items: list[str]) -> list[str]:
            return [f"{key} = ["] + [f"    {json.dumps(i)}," for i in items] + ["]"]

        lines = array("dependencies", self.requirements)
        if self.constraints or self.overrides:
            lines += ["", "[tool.uv]"]
            lines += array("constraint-dependencies", self.constraints) if self.constraints else []
            lines += array("override-dependencies", self.overrides) if self.overrides else []
        header = ["# /// script"] + [f"# {line}".rstrip() for line in lines] + ["# ///"]
        return "\n".join(header) + "\n" + body

    def as_dict(self) -> dict[str, list[str]]:
        return {"requirements": list(self.requirements), "constraints": list(self.constraints),
                "overrides": list(self.overrides)}


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


def _checkout() -> Path | None:
    """The linecaster checkout this code runs from (a git work tree with linecaster's ``pyproject.toml``), or None
    when linecaster is installed from a wheel or an archive."""
    return ROOT if (ROOT / ".git").exists() and (ROOT / "pyproject.toml").is_file() else None


def _in_checkout(path: Path) -> str | None:
    """``path`` relative to the linecaster checkout (``.`` for its root), or None outside it."""
    root = _checkout()
    if root is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def _git(url: str, ref: str | None, subdirectory: str | None) -> str:
    return f"git+{url}" + (f"@{ref}" if ref else "") + (f"#subdirectory={subdirectory}" if subdirectory else "")


def _local(name: str, path: Path, commit: str | None, where: str) -> str:
    """A local folder as a URL a Job can install: GitHub's source archive of linecaster at ``commit`` when the folder
    is in the linecaster checkout; any other folder is a ``PipelineConfigError`` (a Job has no copy of it), and so is
    a folder in the checkout without a commit."""
    sub = _in_checkout(path)
    if sub is None:
        raise PipelineConfigError(f"{where}: {name} comes from the folder {path}, which a Job cannot install: give it "
                                  "a git or url source")
    if not commit:
        raise PipelineConfigError(f"{where}: {name} comes from the linecaster checkout, so the Jobs need the "
                                  "linecaster commit to install it (--commit, pushed)")
    return f"{REPO}/archive/{commit}.tar.gz" + (f"#subdirectory={sub}" if sub != "." else "")


def _source_url(name: str, src: dict, base: Path, commit: str | None, where: str) -> str:
    """The PEP 508 URL of a ``[tool.uv.sources]`` entry: ``url`` as it is, ``git`` with its ``tag``, ``branch`` or
    ``rev`` and its ``subdirectory`` (``git+URL@REF#subdirectory=DIR``), ``path`` (relative to ``base``) as
    ``_local``."""
    if "url" in src:
        return src["url"] + (f"#subdirectory={src['subdirectory']}" if src.get("subdirectory") else "")
    if "git" in src:
        ref = next((src[k] for k in ("tag", "branch", "rev") if k in src), None)
        return _git(src["git"], ref, src.get("subdirectory"))
    if "path" in src:
        return _local(name, base / src["path"], commit, where)
    raise PipelineConfigError(f"{where}: the source of {name} is none a Job can install (url, git or path): {src}")


def _locked_url(name: str, src: dict, base: Path, commit: str | None, where: str) -> str | None:
    """The PEP 508 URL of a package's ``source`` in a uv lock, None for an index's (``registry``) or a virtual one: a
    git source at the commit it was locked at."""
    if "url" in src:
        return src["url"] + (f"#subdirectory={src['subdirectory']}" if src.get("subdirectory") else "")
    if "git" in src:
        u = urlsplit(src["git"])
        query = dict(kv.split("=", 1) for kv in u.query.split("&") if "=" in kv)
        sub = query.get("subdirectory", "").replace("%2F", "/") or None
        return _git(urlunsplit(u._replace(query="", fragment="")), u.fragment or None, sub)
    for kind in ("editable", "directory", "path"):
        if kind in src:
            return _local(name, base / src[kind], commit, where)
    return None


def _reachable(lock: dict, roots: list[tuple[str, tuple[str, ...]]]) -> list[dict]:
    """The packages of ``lock`` reachable from ``roots`` (name, extras), extras followed only where asked for (every
    entry of a package the lock holds at several versions)."""
    packages: dict[str, list[dict]] = {}
    for p in lock.get("package", []):
        packages.setdefault(p["name"], []).append(p)
    found, seen, todo = {}, set(), [(n, tuple(e)) for n, e in roots]
    while todo:
        name, extras = todo.pop()
        if (name, extras) in seen or name not in packages:
            continue
        seen.add((name, extras))
        for p in packages[name]:
            found[(name, p.get("version"))] = p
            deps = list(p.get("dependencies", []))
            for e in extras:
                deps += p.get("optional-dependencies", {}).get(e, [])
            todo += [(d["name"], tuple(d.get("extra", ()))) for d in deps]
    return list(found.values())


def _locked_sources(reached: list[dict], base: Path, commit: str | None, where: str) -> dict[str, str]:
    """The ``reached`` packages that do not come from an index, with their URLs: the sources the installed packages
    declare themselves (pybookget's in linecaster, the kraken fork in linecaster-kraken, the OpenCV stub in
    linecaster-paddlex), which ``uv lock`` applied and ``uv run --with`` would not."""
    found = {}
    for p in reached:
        url = _locked_url(p["name"], p.get("source", {}), base, commit, where)
        if url:
            found[p["name"]] = url
    return found


def _locked_pins(reached: list[dict]) -> list[str]:
    """``name==version`` for the ``reached`` packages that come from an index (``registry``), sorted; a package held
    at several versions gets each version's ``resolution-markers`` as its marker."""
    by_name: dict[str, list[dict]] = {}
    for p in reached:
        if "registry" in p.get("source", {}) and p.get("version"):
            by_name.setdefault(p["name"], []).append(p)
    pins = []
    for name in sorted(by_name):
        entries = by_name[name]
        for p in entries:
            markers = p.get("resolution-markers") if len(entries) > 1 else None
            marker = " or ".join(f"({m})" for m in markers) if markers else ""
            pins.append(f"{name}=={p['version']}" + (f" ; {marker}" if marker else ""))
    return pins


def _lock_of(script: Path, commit: str | None) -> dict | None:
    import tomllib

    lock = script.with_name(script.name + ".lock")
    if _in_checkout(lock) is None and not lock.exists():
        return None
    try:
        return tomllib.loads(at_commit(lock, commit))
    except FileNotFoundError:
        return None


def needs_commit(script: str | Path | None) -> bool:
    """Whether the Jobs of ``script`` need ``--commit``: without a script (linecaster alone) and for a script in the
    linecaster checkout (linecaster's own, which installs linecaster at the commit). A derivative's script outside the
    checkout that takes linecaster from a git tag, branch or rev needs none (unless a source points into the
    checkout, which ``dependencies`` reports)."""
    return script is None or _in_checkout(Path(script)) is not None


def dependencies(commit: str | None, script: str | Path | None = None, engines: bool = True) -> Dependencies:
    """What a Job installs to run ``script`` (a pipeline script, linecaster's or a derivative's), as
    ``Dependencies``: requirements with every source spelled out as a URL, since ``uv run`` outside a project
    ignores ``[tool.uv.sources]``; the lock's versions as constraints; the script's overrides. ``commit`` is the
    linecaster commit the Jobs install (it must be pushed); a script in the linecaster checkout is read as it is at
    ``commit`` (``at_commit``), a derivative's as it is on disk. ``commit`` may be None for a derivative's script
    outside the checkout whose sources need none (``needs_commit``); otherwise its absence is a
    ``PipelineConfigError``.

    * Requirements, the script's own sources: ``url`` as it is, ``git`` with its ``tag``, ``branch`` or ``rev`` and
      its ``subdirectory`` (``name @ git+URL@REF#subdirectory=DIR``); a ``path`` in the linecaster checkout
      (linecaster, an engine package, the OpenCV stub) as GitHub's source archive of linecaster at ``commit``
      (``.../archive/<commit>.tar.gz#subdirectory=...``): some images (``vllm/vllm-openai``) have uv but no git
      executable. Any other path is a ``PipelineConfigError``: a Job has no copy of the folder.
    * Requirements, the sources of the packages it installs (pybookget's in linecaster, the kraken fork in
      linecaster-kraken, the OpenCV stub in linecaster-paddlex), from the script's lock (``<script>.lock``): every
      package reachable from the script's dependencies that does not come from an index, a git one at the commit it
      was locked at.
    * Constraints: every package reachable from the script's dependencies that the lock takes from an index, at the
      lock's version (``name==version``), so the Job resolves what the lock holds; none without a lock.
    * Overrides: the script's ``[tool.uv] override-dependencies`` (a lock that needs one to resolve: a package whose
      declared bound linecaster overrides).
    * linecaster without its ``ray`` extra: a Job does not use Ray.

    ``engines=False`` (a VLM pipeline whose image brings vLLM, or a CPU pipeline): linecaster with the script's
    extras and the sources it needs (pybookget), no engines, the constraints of what those reach; without a script,
    linecaster alone at ``commit``. The kraken fork needs git on the Job (its version comes from git history); the
    default Jobs image has it."""
    if needs_commit(script) and not commit:
        what = "linecaster alone" if script is None else f"{script}, in the linecaster checkout,"
        raise PipelineConfigError(f"{what} needs the linecaster commit the Jobs install (--commit, pushed)")
    repo = f"{REPO}/archive/{commit}.tar.gz"
    if script is None:
        if engines:
            raise PipelineConfigError("dependencies() without a script has no engine packages: give the pipeline's "
                                      "script, or engines=False for linecaster alone")
        return Dependencies([f"linecaster @ {repo}"])
    script = Path(script).resolve()
    where = str(script)
    meta = script_metadata(script, commit)
    uv = meta.get("tool", {}).get("uv", {})
    sources = {_name(k): v for k, v in uv.get("sources", {}).items()}
    direct, roots = {}, []
    for req in meta.get("dependencies", []):
        m = _REQ.match(req)
        if not m:
            raise PipelineConfigError(f"{where}: cannot read the requirement {req!r}")
        name = _name(m["name"])
        extras = tuple(e.strip() for e in (m["extras"] or "").split(",") if e.strip())
        if name == "linecaster":
            extras = tuple(e for e in extras if e != "ray")
        if not engines and name != "linecaster":
            continue
        roots.append((name, extras))
        spec = f"{name}[{','.join(extras)}]" if extras else name
        marker = f" ; {m['marker'].strip()}" if m["marker"] else ""
        src = sources.get(name)
        if src is None:
            direct[name] = f"{spec}{m['rest'].rstrip()}{marker}" if name == "linecaster" else req
        else:
            direct[name] = f"{spec} @ {_source_url(name, src, script.parent, commit, where)}{marker}"
    lock = _lock_of(script, commit)
    if lock is None:
        from loguru import logger

        logger.warning("{script} has no lock: its Jobs resolve their own versions", script=where)
    reached = _reachable(lock, roots) if lock else []
    found = _locked_sources(reached, script.parent, commit, where)
    requirements = list(direct.values()) + [f"{n} @ {u}" for n, u in found.items() if n not in direct]
    if not engines and not requirements:
        requirements = [f"linecaster @ {repo}"]
    return Dependencies(requirements, _locked_pins(reached), list(uv.get("override-dependencies", [])))


#: the body of the uv script a Job runs with ``Dependencies``: datatrove's ``launch_pickled_pipeline``
LAUNCHER = "from datatrove.tools.launch_pickled_pipeline import main\n\nif __name__ == \"__main__\":\n    main()\n"


class JobsExecutor(JobsPipelineExecutor):
    """datatrove's ``JobsPipelineExecutor``, its tasks logging JSON lines when ``LINECASTER_LOG_JSON`` is set in
    the Job (``linecaster.runtime.logs.add_task_logger`` in place of datatrove's).

    ``dependencies`` may be ``Dependencies`` (``dependencies()``): with constraints or overrides each Job runs a uv
    script that carries them (``Dependencies.script`` around datatrove's ``launch_pickled_pipeline``, uploaded as
    datatrove uploads its own) instead of ``uv run --with``, which would ignore them. A list is datatrove's
    ``uv run --with`` requirements, unpinned."""

    def __init__(self, *args, dependencies: Dependencies | list[str] | None = None, **kwargs):
        pinned = dependencies if isinstance(dependencies, Dependencies) else None
        super().__init__(*args, dependencies=pinned.requirements if pinned else dependencies, **kwargs)
        self.pinned = pinned if pinned and (pinned.constraints or pinned.overrides) else None

    def _submit_array_index(self, array_index: int, pik_path: str, token: str) -> str:
        if self.pinned is None:
            return super()._submit_array_index(array_index, pik_path, token)
        import tempfile

        import huggingface_hub

        original = huggingface_hub.run_uv_job
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / "launch_pickled_pipeline.py"
            launcher.write_text(self.pinned.script(LAUNCHER))

            def run_uv_job(script, *args, dependencies=None, **kwargs):     # the launcher, which has the dependencies
                return original(str(launcher), *args, dependencies=None, **kwargs)

            huggingface_hub.run_uv_job = run_uv_job
            try:
                return super()._submit_array_index(array_index, pik_path, token)
            finally:
                huggingface_hub.run_uv_job = original

    def _run_for_rank(self, rank: int, local_rank: int = 0, node_rank: int = -1):
        import datatrove.executor.jobs as datatrove_jobs

        from ..broker import set_worker_index
        from .logs import add_task_logger

        set_worker_index(local_rank, self.tasks_per_job)    # a multi-GPU Job's tasks run at once on one machine
        original = datatrove_jobs.add_task_logger
        datatrove_jobs.add_task_logger = add_task_logger
        try:
            return super()._run_for_rank(rank, local_rank, node_rank)
        finally:
            datatrove_jobs.add_task_logger = original


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
