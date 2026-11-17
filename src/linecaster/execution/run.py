"""One command line for a pipeline on every machine. A pipeline is a self-contained uv script (``pipelines/``)
that runs one pipeline template with slots for presets (``linecaster.templates``); ``main`` gives it:

    uv run pipelines/transcribe_modular.py IMAGES OUT                              # this machine
    uv run pipelines/transcribe_modular.py IMAGES OUT --on ray --tasks 64           # a Ray cluster, one task per GPU
    uv run pipelines/transcribe_modular.py IMAGES OUT --on hf-jobs --namespace NS --commit <sha>   # Hugging Face Jobs
    uv run pipelines/transcribe_modular.py serve                                   # linecaster serve with its models
    uv run pipelines/transcribe_modular.py ray start --head                        # Ray's command line, same environment

Engines run inside the pipeline (``--backend in-process``, the default on this machine) or behind a
server that each task starts for itself (``--backend served``, the default on Ray and HF Jobs): the
pipeline's own ``serve`` command here and on Ray, ``linecaster serve`` in the Job's environment on HF Jobs.
``--endpoint`` points them at a server that is already running instead.

A pipeline script passes ``main`` its ``__file__`` and its template's docstring, the function that adds its options,
the function that returns its engines from the options (for ``serve``) and the function that builds the pipeline
(``reader``, ``engines`` and ``pages`` help with the usual parts), with its pipeline id and slots. ``describe``
builds a template in this process without its engines. The builder may also return
``(pipeline, {"image": ..., "engines": False})``: the Jobs' container image, and whether a Job installs
the pipeline's engine packages or linecaster alone.

Before it launches, ``run`` writes the run record ``OUT/run.yaml`` (``linecaster.execution.provenance.run_record``:
the run id, the pipeline script, the recipe, command line, options, executor, the pipeline's components with backends and
presets, software, hardware); a later launch into the same OUT (a resume) keeps it and writes ``OUT/run-<time>.yaml``
next to it, with its own run id. The page record writers name the launch's run id on every annotator it added
(``Annotator.run``).
Before that the builder (``linecaster.execution.builder``) turns the components the script returns into a plan: it checks
their contracts (every problem listed, nothing launched), stamps the recipe before the first writer, applies
``--until``, ``--after`` and ``--tap-after``, and cuts the pipeline into stages where the stream changes from pages to
items with ``--tasks`` over 1 (each stage an executor that ``depends=`` on the one before). ``--page IMAGE`` runs one
image through the pipeline in this process (``linecaster page``).
``--tasks`` and ``--workers`` are chosen when the command line leaves them open (``allocate``): a pipeline without
engines gets the task count its reader suggests (``auto_tasks``: tasks of about 1,000 pages, from the input); its
workers, with a proxy list, follow the available proxies (those not blocked and not held by another run's workers):
one per available proxy and at most one per CPU when the workers share them fairly (``proxies: {per_worker: share}``,
the default), one per available proxy divided by N with ``per_worker`` 1 or N, at most
``OBJECT_STORAGE_WORKERS`` with OUT on object storage; one when a host has rate limits without proxies (one task keeps
them busy), and one per CPU otherwise; a pipeline with engines one task, and as many workers as tasks. ``--rate-limit``
holds per worker: a server sees the workers running at once times it, which the run states before it starts
(``rate_note``, with why it has the workers it has, ``workers_note``); with ``--proxies`` it holds per proxy, each
proxy used by one worker at a time (the workers share them through ``--broker``, ``linecaster.net.broker``).
``--dry-run`` writes nothing and prints the record with the plan and its Mermaid graph. A model dict may name a catalog
``preset`` (``id``): ``preset_models`` fills in its engine and options, and the record and the
page files carry the preset and its hash.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from linecaster.errors import CatalogError, LinecasterError, PipelineConfigError, exit_code
from linecaster.execution.cpus import available_cpus
from linecaster.execution.allocation import (RAY_TASKS_PER_GPU, _plural, _policy_rate_limited, _proxy_plan, _proxy_workers, allocate, available_proxies, has_engines, on_object_storage, rate_note, ray_gpus, run_notes, starts_vlm_server, workers_note)  # noqa: F401
from linecaster.execution.options import (ENGINE_PORT, OBJECT_STORAGE_WORKERS, ON, check, input_options, parser, rate_limits, sample_problem, sample_rule, uri_map)  # noqa: F401
from linecaster.execution.wiring import (http, engines, overrides, pages, preset_models, reader)  # noqa: F401
from linecaster.serving import model_args  # one place builds the arguments of linecaster serve


RUN_RECORD = "run.yaml"
#: Ray's own `uv run` support does not handle scripts (workers come up without the script's packages)
RAY_UV = "RAY_ENABLE_UV_RUN_RUNTIME_ENV"


def serve(argv: list[str], options: Callable, models: Callable, pipeline_id: str | None = None,
          slots: dict[str, str] | None = None) -> None:
    """``linecaster serve`` in the pipeline's environment, with its models unless ``--model``/``--config``
    names others. The pipeline's slots (``--layout``, ``--recognition``, ...) pick them; presets of built-in engines
    (in the pipeline's process only) are left out."""
    from linecaster.cli import main as cli

    ap = argparse.ArgumentParser(add_help=False)
    if pipeline_id:
        ap.add_argument("--recipe")
    options(ap)
    a, rest = ap.parse_known_args(argv)
    if pipeline_id:
        apply_recipe(ap, a, pipeline_id, slots or {}, argv)
    if not any(x in rest for x in ("--model", "--config", "-h", "--help")):
        from linecaster.catalog.registry import in_process_only

        hosted = [m for m in models(a) if not (m.get("preset") and in_process_only(m["preset"]))]
        rest = model_args(hosted) + rest
    cli(["serve", *rest])


def executor_name(a: argparse.Namespace) -> str:
    if getattr(a, "page", None):
        return "run_pages"
    ray = "RayGPUExecutor" if has_engines(a) or getattr(a, "gpu_tasks", False) else "RayExecutor"
    return {"local": "LocalPipelineExecutor", "ray": ray}.get(a.on, "GPUJobsExecutor" if a.gpus > 1 else "JobsExecutor")


def record(a: argparse.Namespace, p, script: str | None, argv: list[str] | None = None,
           deps=None, image: str | None = None) -> dict:
    """The run record of this launch (``linecaster.execution.provenance.run_record``) for the builder's plan ``p``:
    its stages with their components, and ``pipeline_sha256``."""
    from linecaster.execution.provenance import run_record

    extra = {}
    if a.on == "hf-jobs":
        extra = {"image": image, "dependencies": deps.requirements if deps else None,
                 "constraints": (deps.constraints or None) if deps else None,
                 "overrides": (deps.overrides or None) if deps else None}
    internal = ("recipe_record", "describe_only", "has_engines", "proxy_count", "templates", "workers_note",
                "sample_record", "script_name", "gpu_tasks", "run_id")
    opts = {k: v for k, v in vars(a).items() if k not in internal}
    if getattr(a, "sample_record", None):
        extra["sample"] = a.sample_record
    return run_record(opts, p, script=script, argv=sys.argv[1:] if argv is None else argv,
                      executor=executor_name(a), extra=extra or None, recipe=getattr(a, "recipe_record", None),
                      script_name=getattr(a, "script_name", None), run_id=getattr(a, "run_id", None))


def previous_record(out: str) -> dict | None:
    """The newest run record in ``out`` (``run.yaml`` or a later ``run-<time>.yaml``), or None."""
    from datatrove.io import get_datafolder

    from linecaster.catalog import yamlio

    folder = get_datafolder(out)
    if not folder.exists(RUN_RECORD):
        return None
    records = []
    for name in [RUN_RECORD, *folder.glob("run-*.yaml")]:
        with folder.open(name, "r") as f:
            rec = yamlio.load(f.read()) or {}
        records.append((str(rec.get("created", "")), name != RUN_RECORD, rec))
    return max(records, key=lambda r: r[:2])[2]


def resume_problems(out: str, rec: dict, new_pipeline: bool = False) -> list[str]:
    """Why a run with the record ``rec`` cannot go into ``out``, where an earlier run left its record: another
    ``--tasks`` (each task would read other input; never overridden), another sample (its ``sample.selected.sha256``;
    never overridden) or another pipeline (``pipeline_sha256``; unless ``new_pipeline``). Empty: a new folder, or a
    resume of the same pipeline."""
    previous = previous_record(out)
    if previous is None:
        return []
    problems = []
    if previous.get("tasks") != rec.get("tasks"):
        problems.append(f"{out} holds a run with --tasks {previous.get('tasks')}; a resume with --tasks "
                        f"{rec.get('tasks')} would give each task other input. Resume with --tasks "
                        f"{previous.get('tasks')}, or run into a new folder")
    was, now = ((r.get("sample") or {}).get("selected", {}).get("sha256") for r in (previous, rec))
    if was != now:
        problems.append(f"{out} holds a run of another sample (sample.selected.sha256 {was or 'none: every page'}, "
                        f"this one {now or 'none: every page'}): its finished tasks would hold other pages. Run "
                        "into a new folder, or with the same sample options and input")
    if previous.get("pipeline_sha256") != rec["pipeline_sha256"] and not new_pipeline:
        was = previous.get("pipeline_sha256") or "none (a record from before pipelines were hashed)"
        problems.append(f"{out} holds a run of another pipeline (pipeline_sha256 {was}, this one "
                        f"{rec['pipeline_sha256']}): its finished tasks would be skipped and the folder would mix "
                        f"two pipelines' outputs. Run into a new folder, or give --new-pipeline to resume into this "
                        f"one knowingly (its record is kept next to the earlier one)")
    return problems


def write_record(out: str, rec: dict) -> str:
    """Write ``rec`` as ``OUT/run.yaml`` (any fsspec folder, through datatrove's ``DataFolder``); when one is
    there already (a resumed run), as ``OUT/run-<created>.yaml``. Returns the file name."""
    from datatrove.io import get_datafolder

    from linecaster.catalog import yamlio

    folder = get_datafolder(out)
    name = RUN_RECORD
    if folder.exists(name):
        name = f"run-{rec['created'].replace(':', '').replace('-', '')}.yaml"
    with folder.open(name, "w") as f:
        f.write(yamlio.dump(rec))
    return name


def plan(a: argparse.Namespace, pipeline: list, deps, image: str | None, stages: list | None = None) -> dict:
    """What ``--dry-run`` prints besides the builder's description: where it runs, the servers, the pickled size."""
    import dill

    from linecaster.components.servers.serve import VLMServer, EngineServer
    from linecaster.components.servers.service import VendorServer
    from linecaster.serving import serve_command

    servers = [serve_command(s.models, s.port, s.python, s.max_queue, s.script) if isinstance(s, EngineServer)
               else s.launch_command(getattr(s, "python", None)) for s in pipeline
               if isinstance(s, (EngineServer, VLMServer, VendorServer))]
    pickled = [s.pipeline for s in stages] if stages else pipeline
    return {"on": a.on, "tasks": a.tasks, "tasks_per_job": a.tasks_per_job, "backend": a.backend, "out": a.out,
            "image": image,
            "dependencies": deps.as_dict() if deps else None, "pipeline": [type(s).__name__ for s in pipeline],
            "servers": servers,
            "pickled_bytes": len(dill.dumps(pickled))}


def build_plan(a: argparse.Namespace, pipeline: list):
    """The builder's plan for the pipeline a script built, with the command line's partial run, taps and recipe."""
    from linecaster.execution import builder

    from linecaster.execution.console import Progress

    recipe = getattr(a, "recipe_record", None)
    return builder.build(pipeline, tasks=1 if getattr(a, "page", None) else (a.tasks or 1),
                         observers=None if getattr(a, "page", None) else [Progress()],
                         until=getattr(a, "until", None), after=getattr(a, "after", None),
                         taps=dict(getattr(a, "tap_after", None) or []), run_folder=a.out.rstrip("/"),
                         recipe=(recipe["ref"], recipe["sha256"]) if recipe else None,
                         max_page_errors=getattr(a, "max_page_errors", None),
                         image_decode=getattr(a, "image_decode", None),
                         trace_share=getattr(a, "trace_share", None), run_id=getattr(a, "run_id", None))


def _executors(a: argparse.Namespace, p, out: str, image: str | None, deps, script: str | None = None):
    """One executor per stage, each depending on the one before (datatrove's ``depends=``); the last one runs
    them all. One stage logs to ``OUT/logs``, several to ``OUT/logs/<stage>``."""
    previous = None
    many = len(p.stages) > 1
    for stage in p.stages:
        logs = f"{out}/logs/{stage.name}" if many else f"{out}/logs"
        servers = any(type(b).__name__ in ("EngineServer", "VLMServer", "VendorServer") for b in stage.components)
        if a.on == "local":
            from linecaster.execution.local import LocalExecutor

            workers = a.workers or stage.tasks
            title = Path(getattr(a, "script_name", None) or script).stem if script else "run"
            reader = next((b for b in stage.components if hasattr(b, "task_pages")), None)
            previous = LocalExecutor(stage.pipeline, tasks=stage.tasks, workers=min(workers, stage.tasks),
                                     logging_dir=logs, depends=previous, out=out, reader=reader,
                                     title=f"{title}/{stage.name}" if many else title, note=run_notes(a),
                                     retry_failed=getattr(a, "retry_failed", False))
        elif a.on == "ray":
            if servers or (not many and (has_engines(a) or getattr(a, "gpu_tasks", False))):
                from linecaster.execution.ray import RayGPUExecutor as Ray
            else:                                    # a stage without models (an item stage, a harvest) needs no GPU
                from linecaster.execution.ray import RayExecutor as Ray

            previous = Ray(stage.pipeline, tasks=stage.tasks, workers=min(a.workers or stage.tasks, stage.tasks),
                           cpus_per_task=a.cpus_per_task or 12, mem_per_cpu_gb=a.mem_per_cpu_gb,
                           mem_per_task_gb=getattr(a, "mem_per_task_gb", None),
                           check_fit=getattr(a, "fit_check", True), logging_dir=logs, depends=previous)
        else:
            from linecaster.execution.jobs import GPUJobsExecutor, JobsExecutor
            from linecaster.execution.logs import JSON_ENV

            run_id = out.rsplit("/", 1)[-1]
            env = {"LINECASTER_RUN": run_id, JSON_ENV: "1", **dict(kv.split("=", 1) for kv in a.env)}
            kw = dict(tasks=stage.tasks, workers=a.workers or -1, logging_dir=logs, flavor=a.flavor,
                      namespace=a.namespace, dependencies=deps, timeout=a.timeout, python="3.12",
                      job_name=f"linecaster-{run_id}" + (f"-{stage.name}" if many else ""),
                      labels={"project": "linecaster"}, env=env, depends=previous)
            if image or a.image:
                kw["image"] = a.image or image
            if a.gpus > 1 and servers:
                previous = GPUJobsExecutor(stage.pipeline, gpus=a.gpus, **kw)
            else:
                previous = JobsExecutor(stage.pipeline, tasks_per_job=a.tasks_per_job or 1, **kw)
    return previous


def check_commit(a: argparse.Namespace, script: str | None) -> None:
    """``--on hf-jobs`` needs ``--commit`` for linecaster's own scripts (``jobs.needs_commit``): their Jobs install
    linecaster at that commit. A downstream project's script outside the checkout that takes linecaster from a git tag,
    branch or rev runs without one."""
    if a.on != "hf-jobs":
        return
    if a.commit:
        from linecaster.execution.jobs import resolve_commit

        a.commit = resolve_commit(a.commit)
        return
    from linecaster.execution.jobs import needs_commit

    if needs_commit(script):
        raise PipelineConfigError(f"--on hf-jobs needs --commit (pushed): {script} is in the linecaster checkout, "
                                  "and its Jobs install linecaster at that commit")


def run(a: argparse.Namespace, pipeline: list, script: str, image: str | None = None, engines: bool = True,
        argv: list[str] | None = None, after: Callable[[], None] | None = None) -> None:
    """Build the plan of ``pipeline`` (``linecaster.execution.builder``), check it, write the run record and run its
    stages one after another; with ``--dry-run`` print the plan and its graph instead; with ``--page`` run the one
    page in this process. ``after`` runs here once every task is done (here or on Ray; not for HF Jobs, which this
    process does not wait for): a pipeline's step over all its tasks' output (``pipelines/score.py``)."""
    out = a.out.rstrip("/")
    if not getattr(a, "run_id", None):           # this launch's id: in its record and on every annotator it adds
        from linecaster.execution.provenance import new_run_id

        a.run_id = new_run_id()
    sample = sampled(a, pipeline)
    allocate(a, pipeline)
    p = build_plan(a, pipeline)
    components = p.components
    deps = None
    if a.on == "hf-jobs":
        from linecaster.execution.jobs import dependencies

        deps = dependencies(a.commit, script, engines)
    if a.dry_run:
        rec = record(a, p, script, argv, deps, image or a.image)
        print(json.dumps({**plan(a, components, deps, image or a.image, p.stages), "plan": p.describe(), "record": rec},
                         indent=1))
        print()
        print(p.mermaid())
        p.check()
        problems = resume_problems(out, rec, getattr(a, "new_pipeline", False))
        if problems:
            raise PipelineConfigError(problems)
        return
    p.check()
    rec = record(a, p, script, argv, deps, image or a.image)
    problems = resume_problems(out, rec, getattr(a, "new_pipeline", False))
    if problems:
        raise PipelineConfigError(problems)
    write_record(out, rec)
    if sample is not None:
        from linecaster.execution.sample import write_sample

        write_sample(out, sample)
    if getattr(a, "page", None):
        from linecaster.execution.builder import run_plan

        docs = run_plan(p)
        print(json.dumps({"out": out, "pages": [d.id for d in docs]}))
        return
    if a.on != "local":
        from loguru import logger

        for note in run_notes(a):
            logger.info(note)
    if a.on == "ray":
        connect_ray(a.address, script, getattr(a, "worker_env", "script"))
    _executors(a, p, out, image, deps, script).run()
    if a.on == "hf-jobs":
        print(json.dumps({"out": out, "commit": a.commit, "image": a.image or image}))
    elif after is not None:
        after()


def sampled(a: argparse.Namespace, pipeline: list):
    """The sample of the pipeline's reader (``linecaster.data.sample``), computed once here, before the tasks: kept
    on the reader, it travels with the pickled pipeline, so every task takes its share of the same sample; its
    record goes into the run record (``a.sample_record``). None without a sample. ``--dry-run`` saves nothing
    (no manifest copies)."""
    from linecaster.execution.sample import sample_reader

    reader = sample_reader(pipeline)
    if reader is None:
        return None
    sample = reader.sampled(save=not getattr(a, "dry_run", False))
    a.sample_record = sample.record()
    if len(sample.selected) < (reader.sample.pages or 0):
        from loguru import logger

        logger.warning("the sample holds {got} pages of the {asked} asked for: the input has no more within the rule",
                       got=len(sample.selected), asked=reader.sample.pages)
    return sample


def sample(argv: list[str]) -> None:
    """``linecaster sample [IMAGES] OUT ...``: the sample of an input without a run. Writes ``OUT/sample.parquet``
    (with ``--manifests`` also the manifests it read, ``OUT/manifests``), as a run with the same input and sample
    options would, and prints its record."""
    ap = argparse.ArgumentParser(prog="linecaster sample", description=sample.__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="?", help="folder of page images (any fsspec path), or --parquet, --manifests or "
                                              "--pages")
    ap.add_argument("out", help="output folder (any fsspec path): OUT/sample.parquet")
    input_options(ap)
    ap.set_defaults(on="local", tasks=None, workers=None, tasks_per_job=None, gpus=1, namespace=None, backend=None,
                    endpoint=None, env=[])
    a = check(ap, ap.parse_args(argv))
    if sample_rule(a) is None:
        ap.error("give --sample N, --sample-per-item K or --sample-items M")
    from linecaster.execution.sample import write_sample

    found = reader(a).sampled()
    path = write_sample(a.out.rstrip("/"), found)
    print(json.dumps({**found.record(), "path": path}, indent=1))


def server_env(a: argparse.Namespace) -> str:
    """``--server-env``: as given, ``auto`` by default (the server here when it is the preset's release, else
    uv's)."""
    return getattr(a, "server_env", None) or "auto"


def code_root(script: str) -> Path:
    """The folder a job uploads for its workers: the nearest folder above the script with a ``pyproject.toml`` (a
    linecaster checkout, for its own scripts, whose sources point into it), else the script's own folder."""
    path = Path(script).resolve()
    for d in path.parents:
        if (d / "pyproject.toml").exists():
            return d
    return path.parent


def worker_env(script: str | None, worker: str = "script") -> dict:
    """The runtime environment of a job's Ray workers. ``script``: the job's code (``code_root``) as Ray's
    ``working_dir``, and each worker started as ``uv run --locked <script> python ...`` there: the script's own
    locked environment, built on the node by uv the first time and reused (the script runs its ``python``
    pass-through, ``main``). ``node`` (or no script): nothing, the workers run the Python the node's Ray runs."""
    if worker != "script" or not script:
        return {}
    import shlex

    root = code_root(script)
    rel = Path(script).resolve().relative_to(root).as_posix()
    return {"working_dir": str(root), "py_executable": f"uv run --quiet --locked {shlex.quote(rel)} python",
            "excludes": [".venv/", ".git/", "**/__pycache__/"], "env_vars": {CODE_ROOT_ENV: str(root)}}


#: where a Ray job's code was on its driver: a worker finds the same files in Ray's working directory (``here``)
CODE_ROOT_ENV = "LINECASTER_CODE_ROOT"


def here(path: str | None) -> str | None:
    """``path`` on this machine: a path under the job's code on its driver (``CODE_ROOT_ENV``, set for a Ray job's
    workers by ``worker_env``) is the same file in the worker's working directory (Ray's copy of that code, the
    worker's current folder); any other path, or one that exists here, as it is."""
    root = os.environ.get(CODE_ROOT_ENV)
    if not path or not root or os.path.exists(path):
        return path
    try:
        rel = Path(path).relative_to(root)
    except ValueError:
        return path
    local = Path.cwd() / rel
    return str(local) if local.exists() else path


def connect_ray(address: str, script: str | None = None, worker: str = "script") -> None:
    """Joins the Ray cluster at ``address`` (``--address``: ``auto``, the cluster on this machine or ``RAY_ADDRESS``;
    ``host:6379``; ``ray://host:10001``), unless this process has joined one already, with the workers'
    environment (``worker_env``). Ray's own ``uv run`` support is off (``RAY_UV``): it would start the workers with
    ``uv run`` in the driver's folder, where a uv project replaces the script's environment."""
    os.environ.setdefault(RAY_UV, "0")
    import ray

    if not ray.is_initialized():
        ray.init(address=address, runtime_env=worker_env(script, worker) or None)


def _given(ap: argparse.ArgumentParser, argv: list[str], dest: str) -> bool:
    """Whether the command line gives option ``dest`` itself (a value equal to the default counts too)."""
    flags = [f for act in ap._actions if act.dest == dest for f in act.option_strings]
    return any(arg == f or arg.startswith(f + "=") for arg in argv for f in flags)


def apply_recipe(ap: argparse.ArgumentParser, a: argparse.Namespace, pipeline_id: str, slots: dict[str, str],
                 argv: list[str] | None = None, c=None) -> None:
    """Fill ``a`` from the recipe ``a.recipe`` (its id in the catalog ``c``): each slot's preset and each option,
    unless the command line gives its own; what it gives instead is recorded as an override (``a.recipe_record``:
    the recipe, its hash and the overrides, for the run record)."""
    if not getattr(a, "recipe", None):
        return
    from linecaster.catalog.registry import catalog, entry_id

    argv = sys.argv[1:] if argv is None else argv
    c = catalog() if c is None else c
    ref = entry_id(a.recipe)
    if ref not in c.recipes:
        raise CatalogError(f"unknown recipe {a.recipe!r}; known: {sorted(c.recipes)}")
    pipeline = c.recipes[ref][1].pipeline
    if pipeline != pipeline_id:                  # before resolving: its presets may need other engines
        raise PipelineConfigError(f"recipe {ref} is for the pipeline {pipeline}, not {pipeline_id}")
    r = c.resolve_recipe(ref)
    overrides = {}
    for slot, p in r.content["presets"].items():
        dest = slots[slot]
        given = getattr(a, dest)
        if given is None:
            setattr(a, dest, p["ref"])
        elif given != p["ref"]:
            overrides[slot] = given
    for name, value in r.content.get("options", {}).items():
        if not hasattr(a, name):
            raise PipelineConfigError(f"recipe {r.ref}: the pipeline {pipeline_id} has no option {name!r}")
        if not _given(ap, argv, name):
            setattr(a, name, value)
        elif getattr(a, name) != value:
            overrides[name] = getattr(a, name)
    a.recipe_record = {"ref": r.ref, "pipeline": pipeline_id, "sha256": r.sha256,
                       **({"overrides": overrides} if overrides else {})}


def parse(argv: list[str], description: str | None, options: Callable, pipeline_id: str | None = None,
          slots: dict[str, str] | None = None, c=None) -> argparse.Namespace:
    """A pipeline's command line parsed: the shared options and the script's, the recipe applied (from catalog
    ``c``, default the installed one), checked."""
    ap = parser(description)
    g = ap.add_argument_group("pipeline")
    if pipeline_id:
        g.add_argument("--recipe", help="a catalog recipe (id) filling the slots and options the "
                                        "command line leaves open")
    options(g)
    a = ap.parse_args(argv)
    if pipeline_id:
        apply_recipe(ap, a, pipeline_id, slots or {}, argv, c)
    return check(ap, a)


def describe(template, argv: list[str], c=None, script: str | None = None):
    """The builder's plan of the pipeline template ``template`` (a module of ``linecaster.templates``, or anything with its
    ``options``, ``models``, ``pipeline``, ``PIPELINE`` and ``SLOTS``) with the command line ``argv``, built in this
    process without its engines (the describe mode: presets name their engines without importing them, nothing is
    loaded or launched). ``c``: the catalog (default the installed one); ``script``: the pipeline script the components
    are told about (servers would start it; default the checkout's script of the same name, if there is one)."""
    pipeline_id = getattr(template, "PIPELINE", None)
    a = parse(list(argv), template.__doc__, template.options, pipeline_id, getattr(template, "SLOTS", None), c)
    a.describe_only = True
    a.has_engines = bool(template.models(a))
    if script is None:
        from linecaster.catalog import code

        found = code.script_of(template)
        script = str(found) if found is not None else None
    built = template.pipeline(a, script)
    pipeline = built[0] if isinstance(built, tuple) else built
    return build_plan(a, pipeline)


def describe_recipe(ref: str, c=None) -> dict:
    """A recipe's expanded pipeline: its pipeline template (by the recipe's pipeline id,
    ``linecaster.templates``) described with ``--recipe REF`` on placeholder folders (``describe``), in-process, one
    task: ``{"pipeline": the functional components (provenance.functional_pipeline), "pipeline_sha256": ...}``. ``c``: the
    catalog the recipe is in (default the installed one)."""
    from linecaster.core import model
    from linecaster.catalog.registry import active, catalog
    from linecaster.templates import template
    from linecaster.execution import provenance

    c = c if c is not None else catalog()
    pipeline_id = c.resolve_recipe(ref).content["pipeline"]
    try:
        found = template(pipeline_id)
    except PipelineConfigError as e:
        raise CatalogError(f"recipe {ref}: {e}") from e
    model._preset_produces.cache_clear()
    try:
        with active(c):
            p = describe(found, ["IMAGES", "OUT", "--recipe", ref], c)
    finally:
        model._preset_produces.cache_clear()
    p.check()
    return {"pipeline": provenance.functional_pipeline(p), "pipeline_sha256": provenance.pipeline_sha256(p)}


def recipe(script: str, recipe_id: str) -> None:
    """A recipe script's body (``recipes/<id>.py``): runs the catalog recipe ``recipe_id`` through its pipeline template
    (the recipe's ``pipeline:``, ``linecaster.templates``) with ``main``, ``--recipe`` set to it. The command line is
    the template's; slots on top (recorded as overrides) may be given, another recipe may not. The script itself holds only its environment (the engine packages its presets
    need) and this call.

    Example:
        from linecaster.execution import run

        if __name__ == "__main__":
            run.recipe(__file__, "squiddle")
    """
    from linecaster.catalog.registry import catalog, entry_id
    from linecaster.templates import template as pipeline_shape

    c = catalog()
    if recipe_id not in c.recipes:                # a command line's end, as main's: nothing launched
        print(CatalogError(f"{script}: no recipe {recipe_id!r} in the catalog (known: {', '.join(sorted(c.recipes))})"),
              file=sys.stderr)
        sys.exit(2)
    template = pipeline_shape(c.recipes[recipe_id][1].pipeline)

    def options(ap):
        template.options(ap)
        ap.set_defaults(recipe=recipe_id)        # run adds --recipe to the same parser before these options
        ap.set_defaults(script_name=f"recipes/{recipe_id}.py")   # the record's name for a copy run from the URL

    def build(a, path: str):
        if entry_id(a.recipe) != recipe_id:
            raise PipelineConfigError(f"{Path(script).name} runs the recipe {recipe_id}, not {a.recipe}")
        return template.pipeline(a, path)

    description = (f"The recipe {recipe_id} (the catalog's recipe, through the pipeline {template.PIPELINE}).\n\n"
                   + (template.__doc__ or ""))
    main(script, description, options, template.models, build, template.PIPELINE, template.SLOTS)


def main(script: str, description: str | None, options: Callable, models: Callable, build: Callable,
         pipeline_id: str | None = None, slots: dict[str, str] | None = None) -> None:
    """Gives a pipeline script its command line: a run on any executor, ``serve`` for its models, ``ray`` for Ray's.

    ``ray ...`` runs Ray's own command line in the script's environment; ``serve ...`` starts ``linecaster serve``
    with the script's models; anything else is a run: the options are parsed (a recipe given with ``--recipe``
    fills the slots), ``build`` makes the components, and the run is checked, recorded (``OUT/run.yaml``) and launched on
    ``--on local|ray|hf-jobs`` (see the module docstring). A ``LinecasterError`` ends the command with its exit
    code (2: nothing was launched), every problem listed.

    Args:
        script: the pipeline script's path (its ``__file__``): the run record names it, servers and Jobs run it.
        description: the command line's help text, usually the script's docstring.
        options: ``options(ap)`` adds the script's own options to the ``argparse`` parser.
        models: ``models(a)`` returns the engines the parsed options ask for, as dicts for ``linecaster serve``
            (``{"name", "preset"}`` or ``{"name", "spec", "kwargs"}``).
        build: ``build(a, script)`` returns the components, or ``(components, {"image": ..., "engines": False})`` (the
            Jobs' container image; whether a Job installs the script's engine packages or linecaster alone).
        pipeline_id: the script's pipeline id (``PIPELINE``, e.g. ``transcribe_modular.v1``), which recipes name.
        slots: slot -> option name (``SLOTS``): the options a recipe fills with its presets.

    Example:
        from linecaster.execution import run

        PIPELINE = "bind.v1"
        SLOTS = {"paragraphs": "paragraphs", "document": "document"}

        if __name__ == "__main__":
            run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
    """
    argv = sys.argv[1:]
    if argv[:1] == ["ray"]:
        os.environ.setdefault(RAY_UV, "0")
        from ray.scripts.scripts import main as ray_cli

        sys.argv = ["ray", *argv[1:]]
        sys.exit(ray_cli())
    if argv[:1] == ["python"]:              # a Ray worker in this script's environment (worker_env)
        os.execv(sys.executable, [sys.executable, *argv[1:]])
    try:
        if argv[:1] == ["serve"]:
            return serve(argv[1:], options, models, pipeline_id, slots)
        a = parse(argv, description, options, pipeline_id, slots)
        a.script_path = str(Path(script).resolve())
        check_commit(a, script)
        a.has_engines = bool(models(a))
        built = build(a, str(Path(script).resolve()))
        pipeline, extra = built if isinstance(built, tuple) else (built, {})
        run(a, pipeline, str(Path(script).resolve()), argv=argv, **extra)
    except LinecasterError as e:            # the command line's exit code (2: nothing launched); every problem listed
        print(e, file=sys.stderr)
        sys.exit(exit_code(e))
    except KeyboardInterrupt:               # Ctrl-C: the executor has said what stopped and what runs again
        interrupted()


def interrupted() -> None:
    """Ends this process by SIGINT, after a Ctrl-C the run's executor has handled (its summary, its unfinished tasks,
    its workers ended): no traceback, and the exit status a shell reads as killed by Ctrl-C (130, ``-2`` for a parent
    process), so a shell loop around the command stops. A second Ctrl-C from here on ends it at once. A run started by
    ``uv run`` still ends with exit code 130 and does not stop a shell loop: uv maps a child's signal to an exit code
    (astral-sh/uv#11886); ``trap 'exit 130' INT`` in the loop stops it."""
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 - a closed stream: nothing left to say
            pass
    if hasattr(signal, "SIGKILL"):          # POSIX: the signal itself
        os.kill(os.getpid(), signal.SIGINT)
    sys.exit(130)                           # elsewhere, or if the signal did not end it
