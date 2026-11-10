"""One command line for a pipeline on every machine. A pipeline is a self-contained uv script (``pipelines/``)
that runs one pipeline shape with slots for presets (``linecaster.pipelines``); ``main`` gives it:

    uv run pipelines/transcribe_modular.py IMAGES OUT                              # this machine
    uv run pipelines/transcribe_modular.py IMAGES OUT --on ray --tasks 64           # a Ray cluster, one task per GPU
    uv run pipelines/transcribe_modular.py IMAGES OUT --on hf-jobs --namespace NS --commit <sha>   # Hugging Face Jobs
    uv run pipelines/transcribe_modular.py serve                                   # linecaster serve with its models
    uv run pipelines/transcribe_modular.py ray start --head                        # Ray's command line, same environment

Engines run inside the pipeline (``--backend in-process``, the default on this machine) or behind a
server that each task starts for itself (``--backend served``, the default on Ray and HF Jobs): the
pipeline's own ``serve`` command here and on Ray, ``linecaster serve`` in the Job's environment on HF Jobs.
``--endpoint`` points them at a server that is already running instead.

A pipeline script passes ``main`` its ``__file__`` and its shape's docstring, the function that adds its options,
the function that returns its engines from the options (for ``serve``) and the function that builds the pipeline
(``reader``, ``engines`` and ``pages`` help with the usual parts), with its pipeline id and slots. ``describe``
builds a shape in this process without its engines. The builder may also return
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
``--tasks`` and ``--workers`` are chosen when the command line leaves them open (``allocate``): a pipeline without
engines gets the task count its reader suggests (``auto_tasks``: tasks of about 1,000 pages, from the input); its
workers, with a proxy list, follow the available proxies (those not blocked and not held by another run's workers):
one per available proxy and at most one per CPU when the workers share them fairly (``proxies_per_worker: share``,
the default), one per available proxy divided by N with ``proxies_per_worker`` 1 or N, at most
``OBJECT_STORAGE_WORKERS`` with OUT on object storage; one when a host has rate limits without proxies (one task keeps
them busy), and one per CPU otherwise; a pipeline with engines one task, and as many workers as tasks. ``--rate-limit``
holds per worker: a server sees the workers running at once times it, which the run states before it starts
(``rate_note``, with why it has the workers it has, ``workers_note``); with ``--proxies`` it holds per proxy, each
proxy used by one worker at a time (the workers share them through ``--broker``, ``linecaster.broker``).
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
from .cpus import available_cpus

ON = ("local", "ray", "hf-jobs")
RUN_RECORD = "run.yaml"
ENGINE_PORT = 8100
#: the most workers a run through proxies gets by default with OUT on object storage (``allocate``): 250 workers
#: writing to S3-compatible object storage hung in their listings of OUT/images where 64 ran cleanly, an observation
#: from one setup, not a guarantee; ``--workers`` overrides
OBJECT_STORAGE_WORKERS = 64
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
    g.add_argument("--parquet", help="Parquet files with an image column instead of IMAGES (a folder or one .parquet "
                                     "file), e.g. a Hub dataset: hf://datasets/<repo>@<revision>/data")
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
    g.add_argument("--iiif-format", default="jpg", help="--manifests: the image format asked of IIIF image "
                                                        "services (jpg, png, tif, webp; what the server offers)")
    g.add_argument("--pages", help="page records of an earlier pipeline instead of IMAGES (e.g. "
                                   "pipelines/harvest.py's OUT/pages), images fetched from their URIs")
    g.add_argument("--page", metavar="IMAGE", help="one page image instead of IMAGES, run in this process without "
                                                   "an executor (`linecaster page`)")
    g.add_argument("--rate-limit", action="append", default=[], metavar="REQUESTS/SECONDS",
                   help="http(s) requests (manifests, images, OCR) each worker may send, e.g. 5/1; repeatable, all "
                        "windows apply; a server sees the workers running at once times this")
    g.add_argument("--proxies", default=None, metavar="FILE",
                   help="http(s) requests through these proxies: one per line, a URL or host:port[:user:pass] as "
                        "Webshare lists them; each proxy has one worker at a time (--broker), the rate limits hold "
                        "per proxy, a proxy that is blocked (429, a block page) is left out for that host until the "
                        "block ends, a broken one for an hour; the environment's HTTPS_PROXY then does not apply")
    g.add_argument("--broker", default=None, metavar="PATH",
                   help="the folder (any fsspec path) through which the workers share the proxies and their blocks "
                        "(linecaster.broker; default OUT/logs/broker); runs pointed at one path share them too")
    ua = g.add_mutually_exclusive_group()
    ua.add_argument("--user-agent", default=None, metavar="TEXT",
                    help="the User-Agent of every http(s) request (default: datatrove's, HF-Research/1.0)")
    ua.add_argument("--random-user-agent", action="store_true",
                    help="a random browser User-Agent (pybookget's fake-useragent), a new one for each task")
    g.add_argument("--limit", type=int, default=-1, help="at most this many pages per task (datatrove's limit)")
    g.add_argument("--items", metavar="TABLE",
                   help="items' remote files (resources) instead of IMAGES: Parquet (a folder or one .parquet file) "
                        "with --item-key and either --resource templates or one row per resource (--url-key, "
                        "--kind-key, --name-key); pipelines/harvest.py fetches them as served")
    g.add_argument("--resource", action="append", default=[], metavar="KIND=URL",
                   help="--items: a resource of every item, its URL with {item} for the item id, e.g. "
                        "marcxml=https://catalog.example.org/{item}/marcxml; repeatable")
    g.add_argument("--url-key", default="url", help="--items without --resource: the resource URL column")
    g.add_argument("--kind-key", default="kind", help="--items without --resource: the resource kind column")
    g.add_argument("--name-key", default=None, help="--items without --resource: the copy's name column (default "
                                                    "the URL's last segment)")
    g.add_argument("--max-items", type=int, default=None, metavar="N",
                   help="--items: only the first N items of the input for the whole run (a smoke test)")
    g.add_argument("--http-policy", default=None, metavar="FILE",
                   help="--items, --parquet: an HTTP policy file (YAML: rate_limits, proxies, max_retries, pause_on, "
                        "stop_on, ... for every host at the root, overrides per host under hosts:; "
                        "linecaster.net.policy); the run's own options go over its root, a host's entry over both")
    g.add_argument("--max-pages", type=int, default=None, metavar="N",
                   help="--parquet, IMAGES: only the first N pages of the input for the whole run, divided into tasks "
                        "as the whole input would be (a smoke test of the real setup)")
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
    g.add_argument("--retry-failed", action="store_true",
                   help="local: finished tasks that left rejects (OUT/rejects) run again; with harvest.py their "
                        "images that are there are read back and only the failed pages fetched")
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
    g.add_argument("--tasks", type=int, default=None,
                   help="datatrove tasks (one GPU each on Ray and HF Jobs); default: a pipeline without engines "
                        "tasks of about 1,000 pages (or 5 items) from its input (harvest.py: one item each), one "
                        "otherwise")
    g.add_argument("--workers", type=int, default=None,
                   help="tasks at once; default: a pipeline without engines with --proxies one per available "
                        "proxy, at most one per CPU (proxies_per_worker: share, the default) or divided by "
                        f"proxies_per_worker (1 or N), at most {OBJECT_STORAGE_WORKERS} with OUT on object storage; "
                        "one with --rate-limit without proxies, one per CPU otherwise; all tasks with engines")
    g.add_argument("--backend", choices=["in-process", "served"], default=None,
                   help="engines inside the pipeline or behind a server in each task "
                        "(default: in-process here, served on Ray and HF Jobs)")
    g.add_argument("--endpoint", default=None, help="a running server for the engines")
    g = ap.add_argument_group("Ray")
    g.add_argument("--address", default="auto",
                   help="the Ray cluster: auto (the one on this machine, or RAY_ADDRESS), HOST:6379 or ray://HOST:10001")
    g.add_argument("--cpus-per-task", type=int, default=12,
                   help="CPUs a task reserves on its Ray node (start the workers with ray start --num-cpus at least this)")
    g.add_argument("--mem-per-cpu-gb", type=float, default=4,
                   help="memory a task reserves per CPU, in GiB (ignored with --mem-per-task-gb)")
    g.add_argument("--mem-per-task-gb", type=float, default=None,
                   help="memory a task reserves, in GiB, whatever its CPUs (default: --mem-per-cpu-gb per CPU; "
                        "start the workers with ray start --memory at least this)")
    g.add_argument("--no-fit-check", dest="fit_check", action="store_false",
                   help="launch without checking that a live Ray node can run a task (a cluster that adds nodes on "
                        "demand)")
    g = ap.add_argument_group("Hugging Face Jobs")
    g.add_argument("--commit", help="linecaster commit the Jobs install (must be pushed)")
    g.add_argument("--namespace", default=None,
                   help="the Hugging Face user or organization the Jobs run under and are billed to (required "
                        "with --on hf-jobs; there is no default)")
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
    inputs = [x for x in ("images", "parquet", "manifests", "pages", "page", "items") if getattr(a, x, None)]
    if len(inputs) != 1:
        ap.error("give one of IMAGES, --parquet, --manifests, --pages, --page and --items")
    if a.items and not a.item_key:
        ap.error("--items needs --item-key: the column with each row's item id")
    a.templates = {}
    for spec in a.resource:
        kind, sep, url = spec.partition("=")
        if not sep or not kind or "{item}" not in url:
            ap.error(f"--resource needs KIND=URL with {{item}} in the URL, got {spec!r}")
        a.templates[kind] = url
    if (a.resource or a.max_items is not None) and not a.items:
        ap.error("--resource and --max-items are for --items")
    if a.max_items is not None and a.max_items < 1:
        ap.error("--max-items needs at least 1")
    if a.http_policy and (a.manifests or a.pages):
        ap.error("--http-policy is for --items and --parquet so far")
    if a.http_policy:
        from ..net.policy import HTTPPolicy

        try:
            HTTPPolicy(a.http_policy)
        except PipelineConfigError as e:
            ap.error(e.problems[0])
    if getattr(a, "after", None) and not a.pages:
        ap.error("--after starts from page records: give --pages DIR")
    if getattr(a, "page", None) and (a.on != "local" or a.tasks not in (None, 1)):
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
    if a.max_pages is not None and (a.max_pages < 1 or a.manifests or a.pages or getattr(a, "page", None)):
        ap.error("--max-pages N (at least 1) is for --parquet and IMAGES, whose pages are known before they are read; "
                 "--manifests: --tasks 1 with --limit")
    if a.pages and (a.limit != -1 or a.skip or a.glob_pattern):
        ap.error("--pages reads whole files of page records; --limit, --skip and --glob-pattern are for the other inputs")
    try:
        a.rate_limits = rate_limits(a.rate_limit)
    except PipelineConfigError as e:
        ap.error(e.problems[0])
    if (a.tasks is not None and a.tasks < 1) or (a.workers is not None and a.workers < 1):
        ap.error("--tasks and --workers need at least 1")
    if a.tasks_per_job is not None and (a.tasks_per_job < 1 or a.gpus > 1):
        ap.error("--tasks-per-job is for single-GPU Jobs (a multi-GPU Job runs one task per GPU)")
    if a.on == "hf-jobs" and not a.commit:
        ap.error("--on hf-jobs needs --commit (pushed)")
    if a.on == "hf-jobs" and not a.namespace:
        ap.error("--on hf-jobs needs --namespace: the Hugging Face user or organization the Jobs run under")
    if a.backend is None:
        a.backend = "in-process" if a.on == "local" and not a.endpoint else "served"
    if getattr(a, "proxies", None):
        from ..net.http import read_proxies

        try:
            a.proxy_count = len(read_proxies(a.proxies))
        except (OSError, ValueError) as e:
            ap.error(f"--proxies: {e}")
    for kv in a.env:
        if "=" not in kv or kv.startswith("="):
            ap.error(f"--env needs KEY=VALUE, got {kv!r}")
    return a


def has_engines(a: argparse.Namespace) -> bool:
    """Whether the pipeline runs engines (``main`` sets ``a.has_engines`` from the script's ``models``; unknown counts
    as yes, which keeps one task and every task at once)."""
    return getattr(a, "has_engines", True)


def rate_note(a: argparse.Namespace) -> str | None:
    """What a server sees from ``--rate-limit`` (per worker) and the workers running at once: ``rate limits per
    worker: 150/60, 3/1 · 2 workers → up to 300/min at a server``; with ``--proxies`` per proxy and the proxies in use
    (``rate limits per proxy: 150/60 · 100 proxies → up to 15,000/min at a server``; with fewer workers than proxies
    times their count per worker, ``· 2 of 100 proxies in use (1 proxy per worker)``); and the HTTP policy
    (``--http-policy``); None without either."""
    hosts = None
    if getattr(a, "http_policy", None):
        from ..net.policy import HTTPPolicy

        options = {"rate_limits": [f"{n}/{s:g}" for n, s in a.rate_limits]} if getattr(a, "rate_limits", None) else {}
        if getattr(a, "proxies", None):
            options["proxies"] = a.proxies
        if getattr(a, "random_user_agent", False):
            options["random_user_agent"] = True
        hosts = "HTTP policy: " + HTTPPolicy(a.http_policy).describe(options)
    if not getattr(a, "rate_limits", None):
        return hosts
    limits = ", ".join(f"{n}/{s:g}" for n, s in a.rate_limits)
    if count := getattr(a, "proxy_count", None):     # one worker per proxy at a time: the limits hold per proxy
        from ..net.proxies import DEFAULT_PER_WORKER, describe_per_worker

        per_worker = _proxy_plan(a)[1].get(a.proxies, {}).get("per_worker", DEFAULT_PER_WORKER)
        workers = min(a.workers or a.tasks or 1, a.tasks or 1) if a.workers or a.tasks else None
        used = min(count, workers * per_worker) if workers and isinstance(per_worker, int) else count
        proxies = f"{count:,} prox{'ies' if count != 1 else 'y'}"
        if used < count:
            proxies = f"{used:,} of {proxies} in use ({describe_per_worker(per_worker)})"
        per_minute = min(n / s for n, s in a.rate_limits) * 60 * used
        note = f"rate limits per proxy: {limits} · {proxies} → up to {per_minute:,.0f}/min at a server"
        return note + (f" · {hosts}" if hosts else "")
    workers = min(a.workers or a.tasks or 1, a.tasks or 1)
    per_minute = min(n / s for n, s in a.rate_limits) * 60 * workers
    note = (f"rate limits per worker: {limits} · {workers} worker{'s' if workers != 1 else ''} → up to "
            f"{per_minute:,.0f}/min at a server")
    return note + (f" · {hosts}" if hosts else "")


def workers_note(a: argparse.Namespace) -> str | None:
    """Why the run has the workers it has, when ``allocate`` chose them from the proxies (``250 proxies available →
    250 workers, 1 proxy each``); None otherwise."""
    return getattr(a, "workers_note", None)


def run_notes(a: argparse.Namespace) -> list[str]:
    """The lines a run states before it starts: ``workers_note`` and ``rate_note``, those it has."""
    return [n for n in (workers_note(a), rate_note(a)) if n]


def http(a: argparse.Namespace) -> dict:
    """pybookget ``Config`` fields from the options (``linecaster.net.http.HTTPFetcher``): ``--rate-limit`` (each
    worker's; with ``--proxies`` each proxy's), ``--user-agent`` or ``--random-user-agent``, ``--proxies`` and the
    broker through which the workers share them (``--broker``; else ``default_broker``, ``OUT/logs/broker``, with
    proxies or an HTTP policy, whose ``broker`` goes over it)."""
    out = {"iiif_format": getattr(a, "iiif_format", None) or "jpg"}
    if getattr(a, "proxies", None):
        out["proxy_file"] = a.proxies
    if getattr(a, "broker", None):
        out["broker"] = a.broker
    if (getattr(a, "proxies", None) or getattr(a, "http_policy", None)) and getattr(a, "out", None):
        out["default_broker"] = f"{a.out.rstrip('/')}/logs/broker"
        out["broker_run"] = a.out
    if getattr(a, "user_agent", None):
        out["user_agent"] = a.user_agent
    if getattr(a, "random_user_agent", False):
        out["use_fake_user_agent"] = True
    if getattr(a, "rate_limits", None):
        out["rate_limits"] = a.rate_limits
    return out


def _proxy_plan(a: argparse.Namespace) -> tuple[bool, dict[str, dict]]:
    """How the run's requests go out, for ``allocate``: whether a host with rate limits goes without proxies (its
    limits then hold per worker), and the proxy lists, file -> ``hosts`` (the hosts that use it; None: any host
    without an entry), ``per_worker`` (its ``proxies_per_worker``), ``broker`` (the folder) and ``run`` (what the
    heartbeats name as the run)."""
    base = http(a)
    if getattr(a, "http_policy", None):
        from ..net.policy import HTTPPolicy

        policy = HTTPPolicy(a.http_policy, base)
        entries = [(None, policy.settings(None)), *((h, policy.settings(h)) for h in policy.hosts)]
    else:
        entries = [(None, base)]
    from ..net.proxies import DEFAULT_PER_WORKER

    direct, lists = False, {}
    for host, s in entries:
        if s.get("proxy_file"):
            g = lists.setdefault(s["proxy_file"], {"hosts": set(),
                                                   "per_worker": s.get("proxies_per_worker", DEFAULT_PER_WORKER),
                                                   "broker": s.get("broker") or s.get("default_broker"),
                                                   "run": s.get("broker_run")})
            g["hosts"].add(host)
        elif s.get("rate_limits"):
            direct = True
    return direct, lists


def available_proxies(path: str, hosts: set, broker: str | None, run: str | None) -> dict:
    """The proxies of the file ``path`` a run can use now, from one listing of the broker
    (``linecaster.broker.survey_kind``): ``proxies`` (in the file), ``blocked`` (a live block or broken mark there
    for one of ``hosts``, any host when None is among them), ``held`` (leased by a live worker of another run than
    ``run``; the run's own earlier leases do not count against it), ``available`` (the rest). Without a broker yet
    (a first launch), or one that cannot be read (a warning), all are available."""
    from ..broker import survey_kind
    from ..net.http import read_proxies
    from ..net.proxies import KIND, proxy_id

    ids = {proxy_id(p) for p in read_proxies(path)}
    survey = {"resources": {}, "runs": {}}
    if broker:
        try:
            survey = survey_kind(broker, KIND)
        except Exception as e:  # noqa: BLE001 - the workers are then counted from the file alone
            from loguru import logger

            logger.warning("broker {broker} not read for the workers: {error}; every proxy counts as available",
                           broker=broker, error=e)
    blocked = held = 0
    for pid in ids:
        r = survey["resources"].get(pid)
        if r is None:
            continue
        if r.marks if None in hosts else any(r.marked(h) is not None for h in hosts):
            blocked += 1
        elif r.holder is not None and r.holder in survey["runs"] and survey["runs"][r.holder] != run:
            held += 1
    return {"proxies": len(ids), "blocked": blocked, "held": held, "available": len(ids) - blocked - held}


def on_object_storage(path: str | None) -> bool:
    """Whether ``path`` is on object storage: any fsspec protocol but a local one (``s3://``, ``gs://``, ``hf://``,
    ``az://``, ...; not a plain path, ``file://``, ``local://`` or ``memory://``).

    Args:
        path: a folder, any fsspec path; None counts as local.
    """
    from fsspec.core import split_protocol

    protocol = split_protocol(str(path or ""))[0]
    return protocol not in (None, "file", "local", "memory")


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'s' if n != 1 else ''}"


def _proxy_workers(a: argparse.Namespace, lists: dict[str, dict]) -> tuple[int, str]:
    """The workers the proxy lists allow and why. Per list: one per available proxy divided by its
    ``proxies_per_worker`` (``ceil(available / N)``), or, sharing them fairly (``share``), the available proxies and
    at most one per CPU; the fewest over the lists, at least one. Then at most one per task and, with OUT on object
    storage (``on_object_storage``), at most ``OBJECT_STORAGE_WORKERS``. The reason names the limits that decided."""
    import math

    from ..net.proxies import SHARE, describe_per_worker

    best, why, each, shared = None, "", "", False
    for path, g in lists.items():
        counts = available_proxies(path, g["hosts"], g["broker"], g["run"])
        available = counts["available"]
        left = [f"{counts[k]:,} {what}" for k, what in (("blocked", "blocked or broken"),
                                                         ("held", "held by other runs")) if counts[k]]
        reason = (f"{available:,} prox{'ies' if available != 1 else 'y'} available"
                  + (f" ({counts['proxies']:,} in the list, {', '.join(left)})" if left else ""))
        share = g["per_worker"] == SHARE
        n = max(1, available if share else math.ceil(available / g["per_worker"]))
        if best is None or n < best:
            best, why, shared = n, reason, share
            each = ("a fair share each" if share else "1 proxy each" if g["per_worker"] == 1
                    else describe_per_worker(g["per_worker"]).replace("per worker", "each"))
    caps = [(a.tasks, _plural(a.tasks, "task"))]
    if shared:                                          # a fair share needs no worker per proxy: one per CPU at most
        cpus = available_cpus()
        caps.append((cpus, _plural(cpus, "CPU")))
    if on_object_storage(getattr(a, "out", None)):
        caps.append((OBJECT_STORAGE_WORKERS, "OUT on object storage"))
    workers = min(best, *(n for n, _ in caps))
    why += "".join(f", {text}" for n, text in caps if n == workers and n < best)
    return workers, f"{why} → {_plural(workers, 'worker')}, {each}"


def allocate(a: argparse.Namespace, pipeline: list) -> None:
    """``--tasks`` and ``--workers`` where the command line leaves them open. A pipeline without engines: the task
    count its reader suggests (``auto_tasks``, from the input; one if it has none), and as workers: with a proxy list
    for every host that has rate limits, from the proxies available (``available_proxies``: the proxies in the file
    less those blocked or broken for the run's hosts and those held by another run's live workers, from one listing
    of the broker at launch): sharing them fairly (``proxies_per_worker: share``, the default) one per available
    proxy and at most one per CPU; with ``proxies_per_worker`` 1 or N one per available proxy divided by N
    (``ceil(available / N)``), never capped by the CPUs (the workers mostly wait on the network); either way at most
    one per task and, with OUT on object storage, at most ``OBJECT_STORAGE_WORKERS``, the reason in
    ``workers_note``. A host with rate limits and no proxy list: one worker (one task keeps them busy,
    ``linecaster.net.http.prefetched``); one per CPU otherwise. A pipeline with engines: one task, every task at once.
    ``--page``: one of each. The proxy rule holds for local and Ray runs only: on HF Jobs each worker is a Job, so its
    count is never derived from a proxy list."""
    if getattr(a, "page", None):
        a.tasks, a.workers = 1, 1
        return
    if a.tasks is None:
        reader = next((b for b in pipeline if hasattr(b, "auto_tasks")), None)
        a.tasks = reader.auto_tasks() if reader is not None and not has_engines(a) else 1
    if a.workers is None:
        if has_engines(a):
            a.workers = a.tasks
            return
        direct, lists = _proxy_plan(a)
        if lists and not direct and getattr(a, "on", "local") in ("local", "ray"):   # not a Job per proxy on HF Jobs
            a.workers, a.workers_note = _proxy_workers(a, lists)
            return
        if direct or getattr(a, "rate_limits", None) or _policy_rate_limited(a):
            a.workers = 1
        else:
            a.workers = min(a.tasks, available_cpus())


def _policy_rate_limited(a: argparse.Namespace) -> bool:
    if not getattr(a, "http_policy", None):
        return False
    from ..net.policy import HTTPPolicy

    return HTTPPolicy(a.http_policy).rate_limited()


def reader(a: argparse.Namespace, manifest_folder: str | None = None, task_per_item: bool = False,
           reuse_folder: str | None = None):
    """The reader for the input options. ``manifest_folder``: where ``ManifestReader`` saves the manifests it
    reads (``pipelines/harvest.py``); ``task_per_item``: one item per task when the reader chooses the task count
    (``--parquet`` with ``--item-key``, ``--manifests``; ``pipelines/harvest.py``); ``reuse_folder``: where the
    pipeline writes its images, so a resumed run passes the ones already there on without a request."""
    from ..blocks.readers.images import IMAGE_GLOB, ImageFolderReader, ImageParquetReader
    from ..blocks.readers.records import PageRecordReader

    if getattr(a, "items", None):
        from ..blocks.readers.resources import ResourceReader

        folder, glob = a.items, a.glob_pattern or "**/*.parquet"
        if a.items.endswith(".parquet"):
            parent, _, name = a.items.rpartition("/")
            folder, glob = parent or ".", name
        return ResourceReader(folder, item_key=a.item_key, templates=getattr(a, "templates", None) or None,
                              url_key=a.url_key, kind_key=a.kind_key, name_key=a.name_key, http=http(a),
                              http_policy=a.http_policy, reuse_folder=reuse_folder, max_items=a.max_items, glob_pattern=glob,
                              limit=a.limit, skip=a.skip)
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
                              existing_ocr=a.existing_ocr, manifest_folder=manifest_folder, http=http(a),
                              task_per_item=task_per_item, reuse_folder=reuse_folder)
    if getattr(a, "pages", None):
        return PageRecordReader(a.pages, http=http(a))
    if getattr(a, "page", None):
        folder, _, name = a.page.rstrip("/").rpartition("/")
        return ImageFolderReader(folder or ".", glob_pattern=name, recursive=False)
    if a.parquet:
        folder, glob = a.parquet, a.glob_pattern or "**/*.parquet"
        if a.parquet.endswith(".parquet"):                    # one file: its folder, the file by name
            parent, _, name = a.parquet.rpartition("/")
            folder, glob = parent or ".", name
        return ImageParquetReader(folder, glob_pattern=glob, limit=a.limit,
                                  skip=a.skip, id_key=a.id_key, image_key=a.image_key, item_key=a.item_key,
                                  sequence_key=a.sequence_key, image_folder=a.image_folder, http=http(a),
                                  max_pages=a.max_pages, task_per_item=task_per_item and bool(a.item_key),
                                  reuse_folder=reuse_folder, http_policy=getattr(a, "http_policy", None))
    return ImageFolderReader(a.images, paths_file=a.paths_file, glob_pattern=a.glob_pattern or IMAGE_GLOB,
                             item_from_parent=a.item_from_parent, limit=a.limit, skip=a.skip, max_pages=a.max_pages,
                             sequence=a.item_from_parent and not a.paths_file)


def engines(a: argparse.Namespace, models: list[dict], script: str, window: int = 32) -> tuple[dict, list]:
    """Backends for the engine ``models`` by name, and the server block that goes last (none in-process or
    with ``--endpoint``). Presets of built-in engines (``layout.single-region.v1``) are in-process either way. With
    ``--endpoint`` the served engines need not be installed here: they run in the server's environment."""
    from ..backends import InProcess, Served
    from ..blocks.servers.serve import ModelServer
    from ..catalog.registry import in_process_only

    installed = not getattr(a, "describe_only", False)
    # built-in engines (the single-region layout) run in the pipeline's process with either backend
    local = [m for m in models if a.backend == "in-process" or (m.get("preset") and not m.get("spec")
                                                               and in_process_only(m["preset"]))]
    backends = {}
    for m in preset_models(local, installed=installed):
        b = backends[m["name"]] = InProcess(m["spec"], **m.get("kwargs", {}))
        b.preset, b.preset_sha256 = m.get("preset"), m.get("preset_sha256")
        b.overrides = m.get("overrides")
    # with --endpoint the engines run in the server's environment (one with kraken, say), not in this one
    models = preset_models([m for m in models if m not in local], installed=installed and not a.endpoint, served=True)
    if not models:
        return backends, []
    endpoint = a.endpoint or f"http://127.0.0.1:{ENGINE_PORT}/v1"
    backends.update({m["name"]: Served(endpoint, model=m["name"], max_window=window, preset=m.get("preset"),
                                       engine=m.get("spec")) for m in models})
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
    are. ``installed=False``: the engines need not be installed here (``describe``). ``served``: for a server,
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
    names others. The pipeline's slots (``--layout``, ``--recognition``, ...) pick them; presets of built-in engines
    (in the pipeline's process only) are left out."""
    from ..cli import main as cli

    ap = argparse.ArgumentParser(add_help=False)
    if pipeline_id:
        ap.add_argument("--recipe")
    options(ap)
    a, rest = ap.parse_known_args(argv)
    if pipeline_id:
        apply_recipe(ap, a, pipeline_id, slots or {}, argv)
    if not any(x in rest for x in ("--model", "--config", "-h", "--help")):
        from ..catalog.registry import in_process_only

        hosted = [m for m in models(a) if not (m.get("preset") and in_process_only(m["preset"]))]
        rest = model_args(hosted) + rest
    cli(["serve", *rest])


def executor_name(a: argparse.Namespace) -> str:
    if getattr(a, "page", None):
        return "run_pages"
    ray = "RayGPUExecutor" if has_engines(a) else "RayExecutor"
    return {"local": "LocalPipelineExecutor", "ray": ray}.get(a.on, "GPUJobsExecutor" if a.gpus > 1 else "JobsExecutor")


def record(a: argparse.Namespace, p, script: str | None, argv: list[str] | None = None,
           deps: list | None = None, image: str | None = None) -> dict:
    """The run record of this launch (``linecaster.runtime.provenance.run_record``) for the builder's plan ``p``:
    its stages with their blocks, and ``pipeline_sha256``."""
    from .provenance import run_record

    extra = {"image": image, "dependencies": deps} if a.on == "hf-jobs" else {}
    internal = ("recipe_record", "describe_only", "has_engines", "proxy_count", "templates", "workers_note")
    opts = {k: v for k, v in vars(a).items() if k not in internal}
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
    from ..blocks.servers.service import ServiceServer
    from ..serve import serve_command

    servers = [serve_command(s.models, s.port, s.python, s.max_queue, s.script) if isinstance(s, ModelServer)
               else s.launch_command(getattr(s, "python", None)) for s in pipeline
               if isinstance(s, (ModelServer, ChatModelServer, ServiceServer))]
    pickled = [s.pipeline for s in stages] if stages else pipeline
    return {"on": a.on, "tasks": a.tasks, "tasks_per_job": a.tasks_per_job, "backend": a.backend, "out": a.out,
            "image": image,
            "dependencies": deps, "pipeline": [type(s).__name__ for s in pipeline], "servers": servers,
            "pickled_bytes": len(dill.dumps(pickled))}


def build_plan(a: argparse.Namespace, pipeline: list):
    """The builder's plan for the pipeline a script built, with the command line's partial run, taps and recipe."""
    from . import builder

    from .console import Progress

    recipe = getattr(a, "recipe_record", None)
    return builder.build(pipeline, tasks=1 if getattr(a, "page", None) else (a.tasks or 1),
                         observers=None if getattr(a, "page", None) else [Progress()],
                         until=getattr(a, "until", None), after=getattr(a, "after", None),
                         taps=dict(getattr(a, "tap_after", None) or []), run_folder=a.out.rstrip("/"),
                         recipe=(recipe["ref"], recipe["sha256"]) if recipe else None,
                         max_page_errors=getattr(a, "max_page_errors", None),
                         trace_sample=getattr(a, "trace_sample", None))


def _executors(a: argparse.Namespace, p, out: str, image: str | None, deps: list | None, script: str | None = None):
    """One executor per stage, each depending on the one before (datatrove's ``depends=``); the last one runs
    them all. One stage logs to ``OUT/logs``, several to ``OUT/logs/<stage>``."""
    previous = None
    many = len(p.stages) > 1
    for stage in p.stages:
        logs = f"{out}/logs/{stage.name}" if many else f"{out}/logs"
        servers = any(type(b).__name__ in ("ModelServer", "ChatModelServer", "ServiceServer") for b in stage.blocks)
        if a.on == "local":
            from .local import LocalExecutor

            workers = a.workers or stage.tasks
            title = Path(script).stem if script else "run"
            reader = next((b for b in stage.blocks if hasattr(b, "task_pages")), None)
            previous = LocalExecutor(stage.pipeline, tasks=stage.tasks, workers=min(workers, stage.tasks),
                                     logging_dir=logs, depends=previous, out=out, reader=reader,
                                     title=f"{title}/{stage.name}" if many else title, note=run_notes(a),
                                     retry_failed=getattr(a, "retry_failed", False))
        elif a.on == "ray":
            if servers or (not many and has_engines(a)):
                from .ray import RayGPUExecutor as Ray
            else:                                    # a stage without models (an item stage, a harvest) needs no GPU
                from .ray import RayExecutor as Ray

            previous = Ray(stage.pipeline, tasks=stage.tasks, workers=min(a.workers or stage.tasks, stage.tasks),
                           cpus_per_task=a.cpus_per_task, mem_per_cpu_gb=a.mem_per_cpu_gb,
                           mem_per_task_gb=getattr(a, "mem_per_task_gb", None),
                           check_fit=getattr(a, "fit_check", True), logging_dir=logs, depends=previous)
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
    allocate(a, pipeline)
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
    if a.on != "local":
        from loguru import logger

        for note in run_notes(a):
            logger.info(note)
    if a.on == "ray":
        connect_ray(a.address)
    _executors(a, p, out, image, deps, script).run()
    if a.on == "hf-jobs":
        print(json.dumps({"out": out, "commit": a.commit, "image": a.image or image}))


def connect_ray(address: str) -> None:
    """Joins the Ray cluster at ``address`` (``--address``: ``auto``, the cluster on this machine or ``RAY_ADDRESS``;
    ``host:6379``; ``ray://host:10001``), unless this process has joined one already (inside a Ray job)."""
    import ray

    if not ray.is_initialized():
        ray.init(address=address)


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


def describe(shape, argv: list[str], c=None, script: str | None = None):
    """The builder's plan of the pipeline shape ``shape`` (a module of ``linecaster.pipelines``, or anything with its
    ``options``, ``models``, ``pipeline``, ``PIPELINE`` and ``SLOTS``) with the command line ``argv``, built in this
    process without its engines (the describe mode: presets name their engines without importing them, nothing is
    loaded or launched). ``c``: the catalog (default the installed one); ``script``: the pipeline script the blocks
    are told about (servers would start it; default the checkout's script of the same name, if there is one)."""
    pipeline_id = getattr(shape, "PIPELINE", None)
    a = parse(list(argv), shape.__doc__, shape.options, pipeline_id, getattr(shape, "SLOTS", None), c)
    a.describe_only = True
    a.has_engines = bool(shape.models(a))
    if script is None:
        from ..catalog import code

        found = code.script_of(shape)
        script = str(found) if found is not None else None
    built = shape.pipeline(a, script)
    pipeline = built[0] if isinstance(built, tuple) else built
    return build_plan(a, pipeline)


def describe_recipe(ref: str, c=None) -> dict:
    """A recipe edition's expanded pipeline: its pipeline shape (by the recipe's pipeline id,
    ``linecaster.pipelines``) described with ``--recipe REF`` on placeholder folders (``describe``), in-process, one
    task: ``{"pipeline": the functional blocks (provenance.functional_pipeline), "pipeline_sha256": ...}``. ``c``: the
    catalog the recipe is in (default the installed one)."""
    from ..blocks.base import model
    from ..catalog.registry import active, catalog
    from ..pipelines import shape
    from . import provenance

    c = c if c is not None else catalog()
    pipeline_id = c.resolve_recipe(ref).content["pipeline"]
    try:
        found = shape(pipeline_id)
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


def main(script: str, description: str | None, options: Callable, models: Callable, build: Callable,
         pipeline_id: str | None = None, slots: dict[str, str] | None = None) -> None:
    """Gives a pipeline script its command line: a run on any executor, ``serve`` for its models, ``ray`` for Ray's.

    ``ray ...`` runs Ray's own command line in the script's environment; ``serve ...`` starts ``linecaster serve``
    with the script's models; anything else is a run: the options are parsed (a recipe given with ``--recipe``
    fills the slots), ``build`` makes the blocks, and the run is checked, recorded (``OUT/run.yaml``) and launched on
    ``--on local|ray|hf-jobs`` (see the module docstring). A ``LinecasterError`` ends the command with its exit
    code (2: nothing was launched), every problem listed.

    Args:
        script: the pipeline script's path (its ``__file__``): the run record names it, servers and Jobs run it.
        description: the command line's help text, usually the script's docstring.
        options: ``options(ap)`` adds the script's own options to the ``argparse`` parser.
        models: ``models(a)`` returns the engines the parsed options ask for, as dicts for ``linecaster serve``
            (``{"name", "preset"}`` or ``{"name", "spec", "kwargs"}``).
        build: ``build(a, script)`` returns the blocks, or ``(blocks, {"image": ..., "engines": False})`` (the
            Jobs' container image; whether a Job installs the script's engine packages or linecaster alone).
        pipeline_id: the script's pipeline id (``PIPELINE``, e.g. ``transcribe_modular.v1``), which recipes name.
        slots: slot -> option name (``SLOTS``): the options a recipe fills with its presets.

    Example:
        from linecaster.runtime import run

        PIPELINE = "bind.v1"
        SLOTS = {"recomposition": "recomposition", "normalization": "normalization", "composition": "composition"}

        if __name__ == "__main__":
            run.main(__file__, __doc__, options, models, pipeline, PIPELINE, SLOTS)
    """
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
        a.has_engines = bool(models(a))
        built = build(a, str(Path(script).resolve()))
        pipeline, extra = built if isinstance(built, tuple) else (built, {})
        run(a, pipeline, str(Path(script).resolve()), argv=argv, **extra)
    except LinecasterError as e:            # the command line's exit code (2: nothing launched); every problem listed
        print(e, file=sys.stderr)
        sys.exit(exit_code(e))
