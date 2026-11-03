"""One command line for a recipe on every machine. A recipe is a self-contained uv script that builds one
pipeline; ``main`` gives it:

    uv run recipes/chain.py IMAGES OUT                              # this machine
    uv run recipes/chain.py IMAGES OUT --on ray --tasks 64           # a Ray cluster, one task per GPU
    uv run recipes/chain.py IMAGES OUT --on hf-jobs --commit <sha>   # Hugging Face Jobs
    uv run recipes/chain.py serve                                   # linecaster serve with its models
    uv run recipes/chain.py ray start --head                        # Ray's command line, same environment

Engine models run inside the pipeline (``--backend in-process``, the default on this machine) or behind a
server that each task starts for itself (``--backend served``, the default on Ray and HF Jobs): the
recipe's own ``serve`` command here and on Ray, ``linecaster serve`` in the Job's environment on HF Jobs.
``--endpoint`` points them at a server that is already running instead.

A recipe passes ``main`` its ``__file__``, its docstring, a function that adds its options, a function
that returns its engine models from the options (for ``serve``) and a function that builds the pipeline
(``reader``, ``engines`` and ``rows`` help with the usual parts). The builder may also return
``(pipeline, {"image": ..., "engines": False})``: the Jobs' container image, and whether a Job installs
the recipe's engine packages or linecaster alone.

Before it launches, ``run`` writes the run record ``OUT/run.yaml`` (``linecaster.provenance.run_record``:
recipe, command line, options, executor, the pipeline's blocks with backends and presets, software); a
later launch into the same OUT (a resume) keeps it and writes ``OUT/run-<time>.yaml`` next to it.
``--dry-run`` writes nothing and prints the record with the plan. A model dict may name a catalogue
``preset`` (``id@edition``): ``preset_models`` fills in its engine and options, and the record and the
page files carry the edition and its hash.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

ON = ("local", "ray", "hf-jobs")
RUN_RECORD = "run.yaml"
ENGINE_PORT = 8100
#: Ray's own `uv run` support does not handle scripts (workers come up without the script's packages)
RAY_UV = "RAY_ENABLE_UV_RUN_RUNTIME_ENV"


def parser(description: str | None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="?", help="folder of page images (any fsspec path), or --dataset")
    ap.add_argument("out", help="output folder (any fsspec path): page rows in OUT/rows, logs in OUT/logs")
    g = ap.add_argument_group("input")
    g.add_argument("--dataset", help="an image dataset on the Hugging Face Hub instead of IMAGES")
    g.add_argument("--revision", help="the dataset's pinned revision")
    g.add_argument("--id-column", default="PageID", help="the dataset's page id column")
    g.add_argument("--item-from-parent", action="store_true", help="item id = the image's parent folder")
    g.add_argument("--limit", type=int, default=-1, help="at most this many pages per task")
    g = ap.add_argument_group("where it runs")
    g.add_argument("--on", choices=ON, default="local")
    g.add_argument("--tasks", type=int, default=1, help="datatrove tasks (one GPU each on Ray and HF Jobs)")
    g.add_argument("--workers", type=int, default=None, help="tasks at once (default: all)")
    g.add_argument("--backend", choices=["in-process", "served"], default=None,
                   help="engine models inside the pipeline or behind a server in each task "
                        "(default: in-process here, served on Ray and HF Jobs)")
    g.add_argument("--endpoint", default=None, help="a running server for the engine models")
    g = ap.add_argument_group("Ray")
    g.add_argument("--address", default="auto", help="the Ray cluster")
    g.add_argument("--cpus-per-task", type=int, default=12)
    g.add_argument("--mem-per-cpu-gb", type=float, default=4)
    g = ap.add_argument_group("Hugging Face Jobs")
    g.add_argument("--commit", help="linecaster commit the Jobs install (must be pushed)")
    g.add_argument("--namespace", default="finebooks")
    g.add_argument("--flavor", default="l4x1")
    g.add_argument("--gpus", type=int, default=1, help="GPUs per Job (l4x4: 4), one task each")
    g.add_argument("--image", default=None, help="the Jobs' container image")
    g.add_argument("--timeout", default="3h")
    g.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="for the Jobs; repeatable")
    g.add_argument("--dry-run", action="store_true", help="print the plan and pickle the pipeline; launch nothing")
    return ap


def check(ap: argparse.ArgumentParser, a: argparse.Namespace) -> argparse.Namespace:
    if bool(a.images) == bool(a.dataset):
        ap.error("give IMAGES or --dataset")
    if a.dataset and not a.revision:
        ap.error("--dataset needs a pinned --revision")
    if a.on == "hf-jobs" and not a.commit:
        ap.error("--on hf-jobs needs --commit (pushed)")
    if a.backend is None:
        a.backend = "in-process" if a.on == "local" and not a.endpoint else "served"
    for kv in a.env:
        if "=" not in kv or kv.startswith("="):
            ap.error(f"--env needs KEY=VALUE, got {kv!r}")
    return a


def reader(a: argparse.Namespace):
    from .blocks.readers import HFImageDatasetReader, ImageFolderReader

    if a.dataset:
        return HFImageDatasetReader(a.dataset, a.revision, id_column=a.id_column, limit=a.limit)
    return ImageFolderReader(a.images, item_from_parent=a.item_from_parent, limit=a.limit)


def engines(a: argparse.Namespace, models: list[dict], script: str, window: int = 32) -> tuple[dict, list]:
    """Backends for the engine ``models`` by name, and the server block that goes last (none in-process or
    with ``--endpoint``)."""
    from .backends import InProcess, Served
    from .blocks.serve import ServeModels

    models = preset_models(models)
    if a.backend == "in-process":
        backends = {}
        for m in models:
            b = backends[m["name"]] = InProcess(m["spec"], **m.get("kwargs", {}))
            b.preset, b.preset_sha256 = m.get("preset"), m.get("preset_sha256")
            b.overrides = m.get("overrides")
        return backends, []
    endpoint = a.endpoint or f"http://127.0.0.1:{ENGINE_PORT}/v1"
    backends = {m["name"]: Served(endpoint, model=m["name"], max_window=window) for m in models}
    if a.endpoint:
        return backends, []
    # on HF Jobs the script is not there: the Job's environment has the engines (``dependencies``)
    return backends, [ServeModels(models, port=ENGINE_PORT, script=None if a.on == "hf-jobs" else script)]


def overrides(items: list[str], steps: list[str]) -> dict[str, dict]:
    """``--set STEP.OPTION=VALUE`` items as ``{step: {option: value}}``; values are read as YAML (``4`` is a
    number, ``true`` a boolean, anything else a string)."""
    from .catalog import yamlio

    out: dict[str, dict] = {}
    for item in items:
        key, sep, value = item.partition("=")
        step, dot, option = key.partition(".")
        if not sep or not dot or not option:
            raise SystemExit(f"--set needs STEP.OPTION=VALUE, got {item!r}")
        if step not in steps:
            raise SystemExit(f"--set {item!r}: no step {step!r} in this pipeline ({', '.join(steps)})")
        out.setdefault(step, {})[option] = yamlio.load(value) if value else ""
    return out


def preset_models(models: list[dict]) -> list[dict]:
    """Model dicts with a catalogue ``preset`` (``id`` or ``id@edition``) and no ``spec`` get the preset's
    engine and options, and its edition (``preset``) and hash (``preset_sha256``); the others stay as they
    are."""
    out = []
    for m in models:
        if m.get("preset") and not m.get("spec"):
            from .catalog.registry import engine_spec

            spec, kwargs, r = engine_spec(m["preset"])
            m = {**m, "spec": spec, "kwargs": {**kwargs, **m.get("overrides", {})}, "preset": r.ref,
                 "preset_sha256": r.sha256}
        out.append(m)
    return out


def rows(a: argparse.Namespace):
    from .blocks.writers import PageJsonlWriter

    return PageJsonlWriter(f"{a.out.rstrip('/')}/rows", output_filename="${rank}.jsonl.gz")


from .serve import model_args  # noqa: E402 - one place builds linecaster serve's model arguments


def serve(argv: list[str], options: Callable, models: Callable) -> None:
    """``linecaster serve`` in the recipe's environment, with its models unless ``--model``/``--config``
    names others. The recipe's model options (``--recognizer``, ``--layout-model``, ...) pick them."""
    from .cli import main as cli

    ap = argparse.ArgumentParser(add_help=False)
    options(ap)
    a, rest = ap.parse_known_args(argv)
    if not any(x in rest for x in ("--model", "--config", "-h", "--help")):
        rest = model_args(models(a)) + rest
    cli(["serve", *rest])


def executor_name(a: argparse.Namespace) -> str:
    return {"local": "LocalPipelineExecutor", "ray": "RayGPUExecutor"}.get(
        a.on, "GPUJobsExecutor" if a.gpus > 1 else "JobsPipelineExecutor")


def record(a: argparse.Namespace, pipeline: list, script: str | None, argv: list[str] | None = None,
           deps: list | None = None, image: str | None = None) -> dict:
    """The run record of this launch (``linecaster.provenance.run_record``)."""
    from .provenance import run_record

    extra = {"image": image, "dependencies": deps} if a.on == "hf-jobs" else None
    return run_record(vars(a), pipeline, script=script, argv=sys.argv[1:] if argv is None else argv,
                      executor=executor_name(a), extra=extra)


def write_record(out: str, rec: dict) -> str:
    """Write ``rec`` as ``OUT/run.yaml`` (any fsspec folder, through datatrove's ``DataFolder``); when one is
    there already (a resumed run), as ``OUT/run-<created>.yaml``. Returns the file name."""
    from datatrove.io import get_datafolder

    from .catalog import yamlio

    folder = get_datafolder(out)
    name = RUN_RECORD
    if folder.exists(name):
        name = f"run-{rec['created'].replace(':', '').replace('-', '')}.yaml"
    with folder.open(name, "w") as f:
        f.write(yamlio.dump(rec))
    return name


def plan(a: argparse.Namespace, pipeline: list, deps: list | None, image: str | None) -> dict:
    import dill

    from .blocks.serve import ServeChatModel, ServeModels
    from .serve import serve_command

    servers = [serve_command(s.models, s.port, s.python, s.max_queue, s.script) if isinstance(s, ServeModels)
               else s.launch_command(s.python) for s in pipeline if isinstance(s, (ServeModels, ServeChatModel))]
    return {"on": a.on, "tasks": a.tasks, "backend": a.backend, "out": a.out, "image": image,
            "dependencies": deps, "pipeline": [type(s).__name__ for s in pipeline], "servers": servers,
            "pickled_bytes": len(dill.dumps(pipeline))}


def run(a: argparse.Namespace, pipeline: list, script: str, image: str | None = None, engines: bool = True,
        argv: list[str] | None = None) -> None:
    out = a.out.rstrip("/")
    deps = None
    if a.on == "hf-jobs":
        from .jobs import dependencies

        deps = dependencies(a.commit, script, engines)
    rec = record(a, pipeline, script, argv, deps, image or a.image)
    if a.dry_run:
        print(json.dumps({**plan(a, pipeline, deps, image or a.image), "record": rec}, indent=1))
        return
    write_record(out, rec)
    if a.on == "local":
        from datatrove.executor import LocalPipelineExecutor

        LocalPipelineExecutor(pipeline, tasks=a.tasks, workers=a.workers or a.tasks, logging_dir=f"{out}/logs").run()
    elif a.on == "ray":
        os.environ.setdefault(RAY_UV, "0")
        import ray

        from .ray_executor import RayGPUExecutor

        ray.init(address=a.address)
        RayGPUExecutor(pipeline, tasks=a.tasks, cpus_per_task=a.cpus_per_task, mem_per_cpu_gb=a.mem_per_cpu_gb,
                       logging_dir=f"{out}/logs").run()
    else:
        from datatrove.executor import JobsPipelineExecutor

        from .jobs import GPUJobsExecutor

        run_id = out.rsplit("/", 1)[-1]
        env = {"LINECASTER_RUN": run_id, **dict(kv.split("=", 1) for kv in a.env)}
        kw = dict(tasks=a.tasks, workers=a.workers or -1, logging_dir=f"{out}/logs", flavor=a.flavor,
                  namespace=a.namespace, dependencies=deps, timeout=a.timeout, python="3.12",
                  job_name=f"linecaster-{run_id}", labels={"project": "linecaster"}, env=env)
        if image or a.image:
            kw["image"] = a.image or image
        (GPUJobsExecutor(pipeline, gpus=a.gpus, **kw) if a.gpus > 1 else JobsPipelineExecutor(pipeline, **kw)).run()
        print(json.dumps({"out": out, "commit": a.commit, "image": kw.get("image")}))


def main(script: str, description: str | None, options: Callable, models: Callable, build: Callable) -> None:
    """The recipe's command line: ``serve``, ``ray ...`` or a run (see the module docstring)."""
    argv = sys.argv[1:]
    if argv[:1] == ["ray"]:
        os.environ.setdefault(RAY_UV, "0")
        from ray.scripts.scripts import main as ray_cli

        sys.argv = ["ray", *argv[1:]]
        sys.exit(ray_cli())
    if argv[:1] == ["serve"]:
        return serve(argv[1:], options, models)
    ap = parser(description)
    options(ap.add_argument_group("pipeline"))
    a = check(ap, ap.parse_args(argv))
    built = build(a, str(Path(script).resolve()))
    pipeline, extra = built if isinstance(built, tuple) else (built, {})
    run(a, pipeline, str(Path(script).resolve()), argv=argv, **extra)
