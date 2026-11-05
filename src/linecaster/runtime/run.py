"""One command line for a pipeline on every machine. A pipeline is a self-contained uv script (``pipelines/``)
that builds one pipeline shape with slots for presets; ``main`` gives it:

    uv run pipelines/transcribe_modular.py IMAGES OUT                              # this machine
    uv run pipelines/transcribe_modular.py IMAGES OUT --on ray --tasks 64           # a Ray cluster, one task per GPU
    uv run pipelines/transcribe_modular.py IMAGES OUT --on hf-jobs --commit <sha>   # Hugging Face Jobs
    uv run pipelines/transcribe_modular.py serve                                   # linecaster serve with its models
    uv run pipelines/transcribe_modular.py ray start --head                        # Ray's command line, same environment

Engines run inside the pipeline (``--backend in-process``, the default on this machine) or behind a
server that each task starts for itself (``--backend served``, the default on Ray and HF Jobs): the
pipeline's own ``serve`` command here and on Ray, ``linecaster serve`` in the Job's environment on HF Jobs.
``--endpoint`` points them at a server that is already running instead.

A pipeline passes ``main`` its ``__file__``, its docstring, a function that adds its options, a function
that returns its engines from the options (for ``serve``) and a function that builds the pipeline
(``reader``, ``engines`` and ``pages`` help with the usual parts). The builder may also return
``(pipeline, {"image": ..., "engines": False})``: the Jobs' container image, and whether a Job installs
the pipeline's engine packages or linecaster alone.

Before it launches, ``run`` writes the run record ``OUT/run.yaml`` (``linecaster.runtime.provenance.run_record``:
the pipeline script, the recipe, command line, options, executor, the pipeline's blocks with backends and presets, software); a
later launch into the same OUT (a resume) keeps it and writes ``OUT/run-<time>.yaml`` next to it.
Before that the builder (``linecaster.runtime.builder``) turns the blocks the script returns into a plan: it checks
their contracts (every problem listed, nothing launched), stamps the recipe before the first writer, applies
``--until``, ``--after`` and ``--tap-after``, and cuts the pipeline into stages where the stream changes from pages to
items with ``--tasks`` over 1 (each stage an executor that ``depends=`` on the one before). ``--page IMAGE`` runs one
image through the pipeline in this process (``linecaster page``).
``--dry-run`` writes nothing and prints the record with the plan and its Mermaid graph. A model dict may name a catalog
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

from ..errors import CatalogError, LinecasterError, PipelineConfigError, exit_code

ON = ("local", "ray", "hf-jobs")
RUN_RECORD = "run.yaml"
ENGINE_PORT = 8100
#: Ray's own `uv run` support does not handle scripts (workers come up without the script's packages)
RAY_UV = "RAY_ENABLE_UV_RUN_RUNTIME_ENV"


def parser(description: str | None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="?", help="folder of page images (any fsspec path: local, s3://, hf://), or "
                                              "--parquet, --manifests or --pages")
    ap.add_argument("out", help="output folder (any fsspec path): page records in OUT/pages, logs in OUT/logs")
    g = ap.add_argument_group("input (datatrove's reader options)")
    g.add_argument("--paths-file", help="IMAGES: a file with one image per line, relative to IMAGES, instead of "
                                        "finding the images (datatrove's paths_file); --manifests FOLDER: one "
                                        "manifest per line")
    g.add_argument("--glob-pattern", default=None, help="IMAGES: the image files to read (default every image "
                                                        "file); --parquet: the Parquet files (default **/*.parquet); "
                                                        "--manifests: the manifest files (default **/*.{json,xml}) or "
                                                        "item tables (default **/*.parquet)")
    g.add_argument("--item-from-parent", action="store_true",
                   help="IMAGES: the parent folder is the item (item id)")
    g.add_argument("--parquet", help="Parquet files with an image column instead of IMAGES, e.g. a Hub dataset: "
                                     "hf://datasets/<repo>@<revision>/data")
    g.add_argument("--id-key", default="id", help="--parquet: the page id column (without it: <item>_<0001> from "
                                                   "--item-key and --sequence-key)")
    g.add_argument("--image-key", default="image", help="--parquet: the image column (bytes, an HF image struct, "
                                                        "or a path)")
    g.add_argument("--item-key", default=None, help="--parquet, --manifests with --manifest-key: the item id column")
    g.add_argument("--sequence-key", default=None, help="--parquet: the page's position in its item")
    g.add_argument("--image-folder", default=None, help="--parquet: the folder relative image paths start from")
    g.add_argument("--manifests", help="items' manifests (IIIF or METS; linecaster[pybookget]) instead of IMAGES: a "
                                       "folder of manifest files, a .txt/.txt.gz list (one per line: a URL, or a "
                                       "path relative to the list's folder), or with --manifest-key item tables "
                                       "(a folder of Parquet files or one .parquet file)")
    g.add_argument("--manifest-key", default=None,
                   help="--manifests: the item tables' column with each item's manifest link (other columns go into "
                        "its pages' metadata)")
    g.add_argument("--manifest-format", choices=["iiif", "mets"], default=None,
                   help="--manifests: the manifests' format (default: told apart by content)")
    g.add_argument("--existing-ocr", action="store_true",
                   help="--manifests: also the library's own OCR the manifest links (ALTO, hOCR), as the "
                        "transcription ocr_original")
    g.add_argument("--item-id-pattern", default=None,
                   help="--manifests: a regular expression whose first group is the item id in each manifest "
                        "entry (default: its last path segment that is not 'manifest')")
    g.add_argument("--prefetch", type=int, default=8, help="--manifests: pages requested ahead")
    g.add_argument("--iiif-format", default="jpg", help="--manifests: the image format asked of IIIF image "
                                                        "services (jpg, png, tif, webp; what the server offers)")
    g.add_argument("--pages", help="page records of an earlier pipeline instead of IMAGES (e.g. "
                                   "pipelines/harvest.py's OUT/pages), images fetched from their URIs")
    g.add_argument("--page", metavar="IMAGE", help="one page image instead of IMAGES, run in this process without "
                                                   "an executor (`linecaster page`)")
    g.add_argument("--rate-limit", action="append", default=[], metavar="REQUESTS/SECONDS",
                   help="http(s) requests (manifests, images, OCR) per task, e.g. 5/1; repeatable, all windows apply")
    g.add_argument("--limit", type=int, default=-1, help="at most this many pages per task (datatrove's limit)")
    g.add_argument("--skip", type=int, default=0, help="skip this many pages at the start of each task")
    g = ap.add_argument_group("partial runs (blocks by class name, datatrove name or composite)")
    g.add_argument("--until", metavar="BLOCK", help="run the blocks up to BLOCK, then write the page records "
                                                    "(OUT/pages)")
    g.add_argument("--after", metavar="BLOCK", help="start from page records (--pages DIR) with the blocks after "
                                                    "BLOCK")
    g.add_argument("--tap-after", nargs=2, action="append", default=[], metavar=("BLOCK", "DIR"),
                   help="also write the page records as they leave BLOCK into DIR; repeatable")
    g = ap.add_argument_group("output")
    g.add_argument("--max-page-errors", type=float, default=0.01, metavar="SHARE",
                   help="the share of a task's pages a block may fail on (counting at least 100 pages) before the "
                        "task fails; failed pages go to OUT/rejects and keep their errors in the page records")
    g.add_argument("--new-pipeline", action="store_true",
                   help="run into an OUT that holds a run of another pipeline (another pipeline_sha256) knowingly; "
                        "without it such a run is refused")
    g.add_argument("--trace-sample", type=float, default=None, metavar="SHARE",
                   help="the share of pages traced, chosen by page id (default 0.01; 0: only failed pages and the "
                        "task spans, 1: every page); traces go to OUT/traces and, with the OTEL_* variables, to an "
                        "OTLP endpoint")
    g.add_argument("--item-shards", type=int, default=None, metavar="N",
                   help="write the page records into N item shards (OUT/pages/<shard>/<rank>.jsonl.gz), so a later "
                        "stage (pipelines/bind.py) reads whole items")
    g = ap.add_argument_group("where it runs")
    g.add_argument("--on", choices=ON, default="local")
    g.add_argument("--tasks", type=int, default=1, help="datatrove tasks (one GPU each on Ray and HF Jobs)")
    g.add_argument("--workers", type=int, default=None, help="tasks at once (default: all)")
    g.add_argument("--backend", choices=["in-process", "served"], default=None,
                   help="engines inside the pipeline or behind a server in each task "
                        "(default: in-process here, served on Ray and HF Jobs)")
    g.add_argument("--endpoint", default=None, help="a running server for the engines")
    g = ap.add_argument_group("Ray")
    g.add_argument("--address", default="auto", help="the Ray cluster")
    g.add_argument("--cpus-per-task", type=int, default=12)
    g.add_argument("--mem-per-cpu-gb", type=float, default=4)
    g = ap.add_argument_group("Hugging Face Jobs")
    g.add_argument("--commit", help="linecaster commit the Jobs install (must be pushed)")
    g.add_argument("--namespace", default="finebooks")
    g.add_argument("--flavor", default="l4x1")
    g.add_argument("--gpus", type=int, default=1, help="GPUs per Job (l4x4: 4), one task each")
    g.add_argument("--tasks-per-job", type=int, default=None,
                   help="tasks a single-GPU Job runs one after the other (datatrove's tasks_per_job; each task "
                        "starts its own servers)")
    g.add_argument("--image", default=None, help="the Jobs' container image")
    g.add_argument("--timeout", default="3h")
    g.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="for the Jobs; repeatable")
    g.add_argument("--dry-run", action="store_true", help="print the plan (stages, contracts, problems) and its "
                                                          "Mermaid graph, pickle the pipeline; launch nothing")
    return ap


def rate_limits(values: list[str]) -> list[tuple[int, float]] | None:
    """``["5/1", "200/60"]`` -> ``[(5, 1.0), (200, 60.0)]`` (pybookget's ``Config.rate_limits``)."""
    out = []
    for v in values:
        n, sep, secs = v.partition("/")
        try:
            out.append((int(n), float(secs)))
        except ValueError:
            raise PipelineConfigError(f"--rate-limit needs REQUESTS/SECONDS, got {v!r}") from None
        if not sep or out[-1][0] < 1 or out[-1][1] <= 0:
            raise PipelineConfigError(f"--rate-limit needs REQUESTS/SECONDS, got {v!r}")
    return out or None


def check(ap: argparse.ArgumentParser, a: argparse.Namespace) -> argparse.Namespace:
    inputs = [x for x in ("images", "parquet", "manifests", "pages", "page") if getattr(a, x, None)]
    if len(inputs) != 1:
        ap.error("give one of IMAGES, --parquet, --manifests, --pages and --page")
    if getattr(a, "after", None) and not a.pages:
        ap.error("--after starts from page records: give --pages DIR")
    if getattr(a, "page", None) and (a.on != "local" or a.tasks != 1):
        ap.error("--page runs one image in this process: no --on, no --tasks")
    if (a.parquet or a.pages) and (a.paths_file or a.item_from_parent):
        ap.error("--paths-file and --item-from-parent are for IMAGES and --manifests; --parquet names items "
                 "with --item-key")
    if a.manifests and a.item_from_parent:
        ap.error("--manifests: each manifest is an item (--item-id-pattern names it)")
    if not a.manifests and (a.manifest_key or a.manifest_format or a.existing_ocr):
        ap.error("--manifest-key, --manifest-format and --existing-ocr are for --manifests")
    if a.manifests and a.item_key and not a.manifest_key:
        ap.error("--manifests: --item-key names a column of item tables, so it needs --manifest-key")
    if a.pages and (a.limit != -1 or a.skip or a.glob_pattern):
        ap.error("--pages reads whole files of page records; --limit, --skip and --glob-pattern are for the other inputs")
    try:
        a.rate_limits = rate_limits(a.rate_limit)
    except PipelineConfigError as e:
        ap.error(e.problems[0])
    if a.tasks_per_job is not None and (a.tasks_per_job < 1 or a.gpus > 1):
        ap.error("--tasks-per-job is for single-GPU Jobs (a multi-GPU Job runs one task per GPU)")
    if a.on == "hf-jobs" and not a.commit:
        ap.error("--on hf-jobs needs --commit (pushed)")
    if a.backend is None:
        a.backend = "in-process" if a.on == "local" and not a.endpoint else "served"
    for kv in a.env:
        if "=" not in kv or kv.startswith("="):
            ap.error(f"--env needs KEY=VALUE, got {kv!r}")
    return a


def http(a: argparse.Namespace) -> dict:
    """pybookget ``Config`` fields from the options (``linecaster.net.http.HTTPFetcher``)."""
    out = {"iiif_format": getattr(a, "iiif_format", None) or "jpg"}
    if getattr(a, "rate_limits", None):
        out["rate_limits"] = a.rate_limits
    return out


def reader(a: argparse.Namespace, manifest_folder: str | None = None):
    """The reader for the input options. ``manifest_folder``: where ``ManifestReader`` saves the manifests it
    reads (``pipelines/harvest.py``)."""
    from ..blocks.readers.images import IMAGE_GLOB, ImageFolderReader, ImageParquetReader
    from ..blocks.readers.records import PageRecordReader

    if getattr(a, "manifests", None):
        from ..blocks.readers.manifests import ManifestReader

        src, folder, paths_file, glob = a.manifests, a.manifests, a.paths_file, a.glob_pattern
        parent, _, name = src.rpartition("/")
        if src.endswith((".txt", ".txt.gz")):
            folder, paths_file = parent or ".", src
        elif a.manifest_key and src.endswith(".parquet"):
            folder, glob = parent or ".", name
        return ManifestReader(folder, paths_file=paths_file, glob_pattern=glob, limit=a.limit, skip=a.skip,
                              manifest_key=a.manifest_key, item_key=a.item_key if a.manifest_key else None,
                              manifest_format=a.manifest_format, item_id_pattern=a.item_id_pattern,
                              existing_ocr=a.existing_ocr, manifest_folder=manifest_folder, prefetch=a.prefetch,
                              http=http(a))
    if getattr(a, "pages", None):
        return PageRecordReader(a.pages, http=http(a))
    if getattr(a, "page", None):
        folder, _, name = a.page.rstrip("/").rpartition("/")
        return ImageFolderReader(folder or ".", glob_pattern=name, recursive=False)
    if a.parquet:
        return ImageParquetReader(a.parquet, glob_pattern=a.glob_pattern or "**/*.parquet", limit=a.limit,
                                  skip=a.skip, id_key=a.id_key, image_key=a.image_key, item_key=a.item_key,
                                  sequence_key=a.sequence_key, image_folder=a.image_folder, http=http(a))
    return ImageFolderReader(a.images, paths_file=a.paths_file, glob_pattern=a.glob_pattern or IMAGE_GLOB,
                             item_from_parent=a.item_from_parent, limit=a.limit, skip=a.skip,
                             sequence=a.item_from_parent and not a.paths_file)


def engines(a: argparse.Namespace, models: list[dict], script: str, window: int = 32) -> tuple[dict, list]:
    """Backends for the engine ``models`` by name, and the server block that goes last (none in-process or
    with ``--endpoint``)."""
    from ..backends import InProcess, Served
    from ..blocks.servers.serve import ModelServer

    models = preset_models(models, installed=not getattr(a, "describe_only", False), served=a.backend != "in-process")
    if a.backend == "in-process":
        backends = {}
        for m in models:
            b = backends[m["name"]] = InProcess(m["spec"], **m.get("kwargs", {}))
            b.preset, b.preset_sha256 = m.get("preset"), m.get("preset_sha256")
            b.overrides = m.get("overrides")
        return backends, []
    endpoint = a.endpoint or f"http://127.0.0.1:{ENGINE_PORT}/v1"
    backends = {m["name"]: Served(endpoint, model=m["name"], max_window=window, preset=m.get("preset"),
                                  engine=m.get("spec")) for m in models}
    if a.endpoint:
        return backends, []
    # on HF Jobs the script is not there: the Job's environment has the engines (``dependencies``)
    return backends, [ModelServer(models, port=ENGINE_PORT, script=None if a.on == "hf-jobs" else script)]


def overrides(items: list[str], steps: list[str]) -> dict[str, dict]:
    """``--set STEP.OPTION=VALUE`` items as ``{step: {option: value}}``; values are read as YAML (``4`` is a
    number, ``true`` a boolean, anything else a string)."""
    from ..catalog import yamlio

    out: dict[str, dict] = {}
    for item in items:
        key, sep, value = item.partition("=")
        step, dot, option = key.partition(".")
        if not sep or not dot or not option:
            raise PipelineConfigError(f"--set needs STEP.OPTION=VALUE, got {item!r}")
        if step not in steps:
            raise PipelineConfigError(f"--set {item!r}: no step {step!r} in this pipeline ({', '.join(steps)})")
        out.setdefault(step, {})[option] = yamlio.load(value) if value else ""
    return out


def preset_models(models: list[dict], installed: bool = True, served: bool = False) -> list[dict]:
    """Model dicts with a catalog ``preset`` (``id`` or ``id@edition``) and no ``spec`` get the preset's
    engine and options, and its edition (``preset``) and hash (``preset_sha256``); the others stay as they
    are. ``installed=False``: the engines need not be installed here (``describe_script``). ``served``: for a server,
    which refuses the in-process-only engines."""
    out = []
    for m in models:
        if m.get("preset") and not m.get("spec"):
            from ..catalog.registry import engine_spec

            spec, kwargs, r = engine_spec(m["preset"], installed=installed, served=served)
            m = {**m, "spec": spec, "kwargs": {**kwargs, **m.get("overrides", {})}, "preset": r.ref,
                 "preset_sha256": r.sha256}
        out.append(m)
    return out


def pages(a: argparse.Namespace):
    from ..blocks.writers.records import PageJsonlWriter

    return PageJsonlWriter(f"{a.out.rstrip('/')}/pages", output_filename="${rank}.jsonl.gz",
                           item_shards=getattr(a, "item_shards", None))


from ..serve import model_args  # noqa: E402 - one place builds linecaster serve's model arguments


def serve(argv: list[str], options: Callable, models: Callable, pipeline_id: str | None = None,
          slots: dict[str, str] | None = None) -> None:
    """``linecaster serve`` in the pipeline's environment, with its models unless ``--model``/``--config``
    names others. The pipeline's slots (``--layout``, ``--recognition``, ...) pick them."""
    from ..cli import main as cli

    ap = argparse.ArgumentParser(add_help=False)
    if pipeline_id:
        ap.add_argument("--recipe")
    options(ap)
    a, rest = ap.parse_known_args(argv)
    if pipeline_id:
        apply_recipe(ap, a, pipeline_id, slots or {}, argv)
    if not any(x in rest for x in ("--model", "--config", "-h", "--help")):
        rest = model_args(models(a)) + rest
    cli(["serve", *rest])


def executor_name(a: argparse.Namespace) -> str:
    if getattr(a, "page", None):
        return "run_pages"
    return {"local": "LocalPipelineExecutor", "ray": "RayGPUExecutor"}.get(
        a.on, "GPUJobsExecutor" if a.gpus > 1 else "JobsExecutor")


def record(a: argparse.Namespace, p, script: str | None, argv: list[str] | None = None,
           deps: list | None = None, image: str | None = None) -> dict:
    """The run record of this launch (``linecaster.runtime.provenance.run_record``) for the builder's plan ``p``:
    its stages with their blocks, and ``pipeline_sha256``."""
    from .provenance import run_record

    extra = {"image": image, "dependencies": deps} if a.on == "hf-jobs" else {}
    opts = {k: v for k, v in vars(a).items() if k not in ("recipe_record", "describe_only")}
    return run_record(opts, p, script=script, argv=sys.argv[1:] if argv is None else argv,
                      executor=executor_name(a), extra=extra or None, recipe=getattr(a, "recipe_record", None))


def previous_record(out: str) -> dict | None:
    """The newest run record in ``out`` (``run.yaml`` or a later ``run-<time>.yaml``), or None."""
    from datatrove.io import get_datafolder

    from ..catalog import yamlio

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
    ``--tasks`` (each task would read other input; never overridden) or another pipeline (``pipeline_sha256``; unless
    ``new_pipeline``). Empty: a new folder, or a resume of the same pipeline."""
    previous = previous_record(out)
    if previous is None:
        return []
    problems = []
    if previous.get("tasks") != rec.get("tasks"):
        problems.append(f"{out} holds a run with --tasks {previous.get('tasks')}; a resume with --tasks "
                        f"{rec.get('tasks')} would give each task other input. Resume with --tasks "
                        f"{previous.get('tasks')}, or run into a new folder")
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

    from ..catalog import yamlio

    folder = get_datafolder(out)
    name = RUN_RECORD
    if folder.exists(name):
        name = f"run-{rec['created'].replace(':', '').replace('-', '')}.yaml"
    with folder.open(name, "w") as f:
        f.write(yamlio.dump(rec))
    return name


def plan(a: argparse.Namespace, pipeline: list, deps: list | None, image: str | None, stages: list | None = None) -> dict:
    """What ``--dry-run`` prints besides the builder's description: where it runs, the servers, the pickled size."""
    import dill

    from ..blocks.servers.serve import ChatModelServer, ModelServer
    from ..serve import serve_command

    servers = [serve_command(s.models, s.port, s.python, s.max_queue, s.script) if isinstance(s, ModelServer)
               else s.launch_command(s.python) for s in pipeline if isinstance(s, (ModelServer, ChatModelServer))]
    pickled = [s.pipeline for s in stages] if stages else pipeline
    return {"on": a.on, "tasks": a.tasks, "tasks_per_job": a.tasks_per_job, "backend": a.backend, "out": a.out,
            "image": image,
            "dependencies": deps, "pipeline": [type(s).__name__ for s in pipeline], "servers": servers,
            "pickled_bytes": len(dill.dumps(pickled))}


def build_plan(a: argparse.Namespace, pipeline: list):
    """The builder's plan for the pipeline a script built, with the command line's partial run, taps and recipe."""
    from . import builder

    recipe = getattr(a, "recipe_record", None)
    return builder.build(pipeline, tasks=1 if getattr(a, "page", None) else a.tasks,
                         until=getattr(a, "until", None), after=getattr(a, "after", None),
                         taps=dict(getattr(a, "tap_after", None) or []), run_folder=a.out.rstrip("/"),
                         recipe=(recipe["ref"], recipe["sha256"]) if recipe else None,
                         max_page_errors=getattr(a, "max_page_errors", None),
                         trace_sample=getattr(a, "trace_sample", None))


def _executors(a: argparse.Namespace, p, out: str, image: str | None, deps: list | None):
    """One executor per stage, each depending on the one before (datatrove's ``depends=``); the last one runs
    them all. One stage logs to ``OUT/logs``, several to ``OUT/logs/<stage>``."""
    previous = None
    many = len(p.stages) > 1
    for stage in p.stages:
        logs = f"{out}/logs/{stage.name}" if many else f"{out}/logs"
        servers = any(type(b).__name__ in ("ModelServer", "ChatModelServer") for b in stage.blocks)
        if a.on == "local":
            from datatrove.executor import LocalPipelineExecutor

            workers = a.workers or stage.tasks
            previous = LocalPipelineExecutor(stage.pipeline, tasks=stage.tasks, workers=min(workers, stage.tasks),
                                             logging_dir=logs, depends=previous)
        elif a.on == "ray":
            if servers or not many:
                from .ray import RayGPUExecutor as Ray
            else:                                    # an item stage without models needs no GPU
                from datatrove.executor.ray import RayPipelineExecutor as Ray

            previous = Ray(stage.pipeline, tasks=stage.tasks, cpus_per_task=a.cpus_per_task,
                           mem_per_cpu_gb=a.mem_per_cpu_gb, logging_dir=logs, depends=previous)
        else:
            from .jobs import GPUJobsExecutor, JobsExecutor
            from .logs import JSON_ENV

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


def run(a: argparse.Namespace, pipeline: list, script: str, image: str | None = None, engines: bool = True,
        argv: list[str] | None = None) -> None:
    """Build the plan of ``pipeline`` (``linecaster.runtime.builder``), check it, write the run record and run its
    stages one after another; with ``--dry-run`` print the plan and its graph instead; with ``--page`` run the one
    page in this process."""
    out = a.out.rstrip("/")
    p = build_plan(a, pipeline)
    blocks = p.blocks
    deps = None
    if a.on == "hf-jobs":
        from .jobs import dependencies

        deps = dependencies(a.commit, script, engines)
    if a.dry_run:
        rec = record(a, p, script, argv, deps, image or a.image)
        print(json.dumps({**plan(a, blocks, deps, image or a.image, p.stages), "plan": p.describe(), "record": rec},
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
    if getattr(a, "page", None):
        from .builder import run_plan

        docs = run_plan(p)
        print(json.dumps({"out": out, "pages": [d.id for d in docs]}))
        return
    _executors(a, p, out, image, deps).run()
    if a.on == "hf-jobs":
        print(json.dumps({"out": out, "commit": a.commit, "image": a.image or image}))


def _given(ap: argparse.ArgumentParser, argv: list[str], dest: str) -> bool:
    """Whether the command line gives option ``dest`` itself (a value equal to the default counts too)."""
    flags = [f for act in ap._actions if act.dest == dest for f in act.option_strings]
    return any(arg == f or arg.startswith(f + "=") for arg in argv for f in flags)


def apply_recipe(ap: argparse.ArgumentParser, a: argparse.Namespace, pipeline_id: str, slots: dict[str, str],
                 argv: list[str] | None = None, c=None) -> None:
    """Fill ``a`` from the recipe ``a.recipe`` (id[@edition] in the catalog ``c``): each slot's preset edition
    and each option, unless the command line gives its own; what it gives instead is recorded as an override
    (``a.recipe_record``: the recipe edition, its hash and the overrides, for the run record)."""
    if not getattr(a, "recipe", None):
        return
    from ..catalog.registry import catalog, split_ref

    argv = sys.argv[1:] if argv is None else argv
    c = catalog() if c is None else c
    ref = a.recipe
    rid, edition = split_ref(ref)
    d, doc = c.recipes[rid] if rid in c.recipes else (None, None)
    if doc is None:
        raise CatalogError(f"unknown recipe {a.recipe!r}; known: {sorted(c.recipes)}")
    pipeline = doc.pipeline if edition in (None, doc.edition) else d.lock.recipes[ref].resolved["pipeline"]
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
    a.recipe_record = {"ref": r.ref, "pipeline": pipeline_id, "sha256": r.sha256, "released": r.released,
                       **({"overrides": overrides} if overrides else {})}


def parse(argv: list[str], description: str | None, options: Callable, pipeline_id: str | None = None,
          slots: dict[str, str] | None = None, c=None) -> argparse.Namespace:
    """A pipeline's command line parsed: the shared options and the script's, the recipe applied (from catalog
    ``c``, default the installed one), checked."""
    ap = parser(description)
    g = ap.add_argument_group("pipeline")
    if pipeline_id:
        g.add_argument("--recipe", help="a catalog recipe (id[@edition]) filling the slots and options the "
                                        "command line leaves open")
    options(g)
    a = ap.parse_args(argv)
    if pipeline_id:
        apply_recipe(ap, a, pipeline_id, slots or {}, argv, c)
    return check(ap, a)


def load_script(script: str | Path):
    """A pipeline script as a module of this process (its ``__main__`` block does not run): its ``options``,
    ``models``, ``pipeline``, ``PIPELINE`` and ``SLOTS``. Its PEP 723 environment is not needed as long as nothing
    loads an engine: blocks and backends import no engine before ``warm_up``."""
    import importlib.util

    path = Path(script).resolve()
    spec = importlib.util.spec_from_file_location(f"linecaster_pipeline_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe_script(script: str | Path, argv: list[str], c=None):
    """The builder's plan of the pipeline script ``script`` with the command line ``argv``, built in this process
    without its engines (the describe mode: presets name their engines without importing them, nothing is
    loaded or launched)."""
    module = load_script(script)
    pipeline_id = getattr(module, "PIPELINE", None)
    a = parse(list(argv), module.__doc__, module.options, pipeline_id, getattr(module, "SLOTS", None), c)
    a.describe_only = True
    built = module.pipeline(a, str(Path(script).resolve()))
    pipeline = built[0] if isinstance(built, tuple) else built
    return build_plan(a, pipeline)


def describe_recipe(ref: str, c=None) -> dict:
    """A recipe edition's expanded pipeline: its pipeline script (by the recipe's pipeline id, in the checkout)
    described with ``--recipe REF`` on placeholder folders (``describe_script``), in-process, one task:
    ``{"pipeline": the functional blocks (provenance.functional_pipeline), "pipeline_sha256": ...}``. ``c``: the
    catalog the recipe is in (default the installed one)."""
    from ..blocks.base import model
    from ..catalog import code
    from ..catalog.registry import active, catalog
    from . import provenance

    c = c if c is not None else catalog()
    pipeline_id = c.resolve_recipe(ref).content["pipeline"]
    scripts = code.pipelines() if code.REPO is not None and (code.REPO / "pipelines").is_dir() else {}
    if pipeline_id not in scripts:
        raise CatalogError(f"recipe {ref}: no pipeline script for {pipeline_id} (it needs the repository checkout)")
    model._preset_produces.cache_clear()
    try:
        with active(c):
            p = describe_script(scripts[pipeline_id].source, ["IMAGES", "OUT", "--recipe", ref], c)
    finally:
        model._preset_produces.cache_clear()
    p.check()
    return {"pipeline": provenance.functional_pipeline(p), "pipeline_sha256": provenance.pipeline_sha256(p)}


def main(script: str, description: str | None, options: Callable, models: Callable, build: Callable,
         pipeline_id: str | None = None, slots: dict[str, str] | None = None) -> None:
    """The pipeline's command line: ``serve``, ``ray ...`` or a run (see the module docstring). ``pipeline_id``
    (e.g. ``transcribe_modular.v1``) and ``slots`` (slot -> option name) let a recipe fill the pipeline (``--recipe``)."""
    argv = sys.argv[1:]
    if argv[:1] == ["ray"]:
        os.environ.setdefault(RAY_UV, "0")
        from ray.scripts.scripts import main as ray_cli

        sys.argv = ["ray", *argv[1:]]
        sys.exit(ray_cli())
    try:
        if argv[:1] == ["serve"]:
            return serve(argv[1:], options, models, pipeline_id, slots)
        a = parse(argv, description, options, pipeline_id, slots)
        built = build(a, str(Path(script).resolve()))
        pipeline, extra = built if isinstance(built, tuple) else (built, {})
        run(a, pipeline, str(Path(script).resolve()), argv=argv, **extra)
    except LinecasterError as e:            # the command line's exit code (2: nothing launched); every problem listed
        print(e, file=sys.stderr)
        sys.exit(exit_code(e))
