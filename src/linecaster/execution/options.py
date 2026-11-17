"""The pipelines' command line: the options every pipeline script has (``parser``, ``input_options``), their
checks (``check``) and the sample rule they name (``sample_rule``)."""
from __future__ import annotations

import argparse

from linecaster.errors import PipelineConfigError


ON = ("local", "ray", "hf-jobs")
ENGINE_PORT = 8100
#: the most workers a run through proxies gets by default with OUT on object storage (``allocate``): 250 workers
#: writing to S3-compatible object storage hung in their listings of OUT/images where 64 ran cleanly, an observation
#: from one setup, not a guarantee; ``--workers`` overrides
OBJECT_STORAGE_WORKERS = 64


def parser(description: str | None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="?", help="folder of page images (any fsspec path: local, s3://, hf://), or "
                                              "--parquet, --manifests or --pages")
    ap.add_argument("out", help="output folder (any fsspec path): page records in OUT/pages, logs in OUT/logs")
    input_options(ap)
    g = ap.add_argument_group("partial runs (components by class name, datatrove name or composite)")
    g.add_argument("--until", metavar="BLOCK", help="run the components up to BLOCK, then write the page records "
                                                    "(OUT/pages)")
    g.add_argument("--after", metavar="BLOCK", help="start from page records (--pages DIR) with the components after "
                                                    "BLOCK")
    g.add_argument("--tap-after", nargs=2, action="append", default=[], metavar=("BLOCK", "DIR"),
                   help="also write the page records as they leave BLOCK into DIR; repeatable")
    g = ap.add_argument_group("output")
    g.add_argument("--max-page-errors", type=float, default=0.01, metavar="SHARE",
                   help="the share of a task's pages a component may fail on (counting at least 100 pages) before the "
                        "task fails; failed pages go to OUT/rejects and keep their errors in the page records")
    g.add_argument("--image-decode", choices=["auto", "gpu", "cpu"], default=None,
                   help="how the model components decode page images: auto (on an NVIDIA GPU where the machine has one "
                        "and linecaster[nvimgcodec] is installed, else Pillow), gpu (an error where none is), cpu "
                        "(Pillow); default auto. Each step records its decoder")
    g.add_argument("--retry-failed", action="store_true",
                   help="local: finished tasks that left rejects (OUT/rejects) run again; with harvest.py their "
                        "images that are there are read back and only the failed pages fetched")
    g.add_argument("--new-pipeline", action="store_true",
                   help="run into an OUT that holds a run of another pipeline (another pipeline_sha256) knowingly; "
                        "without it such a run is refused")
    g.add_argument("--trace-share", type=float, default=None, metavar="SHARE",
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
                        "proxy, at most one per CPU (per_worker: share in an HTTP policy, the default) or divided by "
                        f"per_worker (1 or N), at most {OBJECT_STORAGE_WORKERS} with OUT on object storage; "
                        "one with --rate-limit without proxies, one per CPU otherwise; all tasks with engines")
    g.add_argument("--backend", choices=["in-process", "served"], default=None,
                   help="engines inside the pipeline or behind a server in each task "
                        "(default: in-process here, served on Ray and HF Jobs)")
    g.add_argument("--endpoint", default=None, help="a running server for the engines")
    g.add_argument("--server-env", choices=["auto", "uv", "path"], default="auto",
                   help="where a model's server (vLLM, SGLang) comes from: auto (the one on PATH or in the image "
                        "when it is the preset's release, e.g. vLLM's image at linecaster's pin; else built by uv), "
                        "uv (the preset's release, built by uv once per machine) or path (the one there, whatever "
                        "its release)")
    g = ap.add_argument_group("Ray")
    g.add_argument("--address", default="auto",
                   help="the Ray cluster: auto (the one on this machine, or RAY_ADDRESS), HOST:6379 or ray://HOST:10001")
    g.add_argument("--cpus-per-task", type=int, default=None,
                   help="CPUs a task reserves on its Ray node (default: 12, or the pipeline's own share; start the "
                        "workers with ray start --num-cpus at least this)")
    g.add_argument("--mem-per-cpu-gb", type=float, default=4,
                   help="memory a task reserves per CPU, in GiB (ignored with --mem-per-task-gb)")
    g.add_argument("--mem-per-task-gb", type=float, default=None,
                   help="memory a task reserves, in GiB, whatever its CPUs (default: --mem-per-cpu-gb per CPU; "
                        "start the workers with ray start --memory at least this)")
    g.add_argument("--worker-env", choices=["script", "node"], default="script",
                   help="the Python a task's Ray worker runs: script (this script's locked environment, built on each "
                        "node by uv from the job's code, which the job uploads: any job on any cluster of nodes "
                        "with uv and linecaster's Ray) or node (the Python the node's Ray runs)")
    g.add_argument("--no-fit-check", dest="fit_check", action="store_false",
                   help="launch without checking that a live Ray node can run a task (a cluster that adds nodes on "
                        "demand)")
    g = ap.add_argument_group("Hugging Face Jobs")
    g.add_argument("--commit", help="linecaster commit the Jobs install (must be pushed); required for linecaster's "
                                    "own scripts, unused by a script outside the checkout that takes linecaster "
                                    "from a git tag, branch or rev")
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


def input_options(ap: argparse.ArgumentParser) -> None:
    """The input options (``reader``) and the sample's, shared by the pipelines and ``linecaster sample``."""
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
    g.add_argument("--manifests", help="items' manifests (IIIF or METS) instead of IMAGES: a "
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
    g.add_argument("--uri-map", action="append", default=[], metavar="PREFIX=REPLACEMENT",
                   help="--pages: rewrite the image URIs that start with PREFIX before reading them (the images "
                        "moved since the records were written, or a local copy of remote files); repeatable")
    g.add_argument("--page", metavar="IMAGE", help="one page image instead of IMAGES, run in this process without "
                                                   "an executor (`linecaster page`)")
    g.add_argument("--rate-limit", action="append", default=[], metavar="REQUESTS/SECONDS",
                   help="http(s) requests (manifests, images, OCR) each worker may send, e.g. 5/1; repeatable, all "
                        "windows apply; a server sees the workers running at once times this")
    g.add_argument("--proxies", default=None, metavar="FILE",
                   help="http(s) requests through these proxies: one per line, a URL or host:port[:user:pass] as "
                        "Webshare lists them; each proxy has one worker at a time (--broker), the rate limits hold "
                        "per proxy, a proxy that is blocked (a 429) is left out for that host until the block ends "
                        "(Retry-After, else 60 s doubling up to an hour), a broken one (3 proxy errors in a row) for "
                        "5 min, doubling; the environment's HTTPS_PROXY then does not apply")
    g.add_argument("--broker", default=None, metavar="PATH",
                   help="the folder (any fsspec path) through which the workers share the proxies and their blocks "
                        "(linecaster.net.broker; default OUT/logs/broker); runs pointed at one path share them too")
    ua = g.add_mutually_exclusive_group()
    ua.add_argument("--user-agent", default=None, metavar="TEXT",
                    help="the User-Agent of every http(s) request (default: datatrove's, HF-Research/1.0)")
    ua.add_argument("--random-user-agent", action="store_true",
                    help="a random browser User-Agent (fake-useragent), a new one for each task")
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
                   help="an HTTP policy file for every request over http(s) (--parquet, --items, --manifests, --pages) "
                        "(YAML: rate_limits, max_retries, block_on, stop_on, max_pause, proxies: {file, per_worker, "
                        "block_ttl, broken_after, broken_ttl}, ... for every host at the root, overrides per host "
                        "under hosts:; docs/reference/http.md); the run's own options go over its root, a host's "
                        "entry over both")
    g.add_argument("--max-pages", type=int, default=None, metavar="N",
                   help="--parquet, IMAGES: only the first N pages of the input for the whole run, divided into tasks "
                        "as the whole input would be (a smoke test of the real setup)")
    g.add_argument("--skip", type=int, default=0, help="skip this many pages at the start of each task")
    g = ap.add_argument_group("sample (the same pages for every run setup: linecaster.data.sample)")
    g.add_argument("--sample", type=int, default=None, metavar="N",
                   help="only the first N pages of the sample order for the whole run, whatever --tasks: items "
                        "ranked by sha256 of seed and item id, pages within each item by sha256 of seed, item and "
                        "page id; with --sample-per-item K that is about N/K items; for IMAGES, --parquet, "
                        "--manifests and --pages, chosen from their ids before any image is read; the sample goes to "
                        "OUT/sample.parquet and the run record")
    g.add_argument("--sample-per-item", type=int, default=None, metavar="K",
                   help="at most the first K pages of each item (every item's first K pages without --sample)")
    g.add_argument("--sample-items", type=int, default=None, metavar="M", help="only the first M items")
    g.add_argument("--sample-seed", type=int, default=None, metavar="S",
                   help="the seed of the sample order (default 0)")


def uri_map(values: list[str]) -> dict[str, str]:
    """``--uri-map PREFIX=REPLACEMENT`` options as ``PageRecordReader``'s ``uri_map`` (the first matching prefix
    wins, in the order given)."""
    out = {}
    for v in values:
        prefix, sep, repl = v.partition("=")
        if not sep or not prefix:
            raise PipelineConfigError(f"--uri-map needs PREFIX=REPLACEMENT, got {v!r}")
        out[prefix] = repl
    return out


def rate_limits(values: list[str]) -> list[tuple[int, float]] | None:
    """``["5/1", "200/60"]`` -> ``[(5, 1.0), (200, 60.0)]`` (``linecaster.net.http.HTTPConfig.rate_limits``)."""
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
    if getattr(a, "uri_map", None) and not a.pages:
        ap.error("--uri-map rewrites the image URIs of page records: it needs --pages")
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
    if a.http_policy:
        from linecaster.net.policy import HTTPPolicy

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
    problem = sample_problem(a)
    if problem:
        ap.error(problem)
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
    if a.on == "hf-jobs" and not a.namespace:
        ap.error("--on hf-jobs needs --namespace: the Hugging Face user or organization the Jobs run under")
    if a.backend is None:
        a.backend = "in-process" if a.on == "local" and not a.endpoint else "served"
    if getattr(a, "proxies", None):
        from linecaster.net.http import read_proxies

        try:
            a.proxy_count = len(read_proxies(a.proxies))
        except (OSError, ValueError) as e:
            ap.error(f"--proxies: {e}")
    for kv in a.env:
        if "=" not in kv or kv.startswith("="):
            ap.error(f"--env needs KEY=VALUE, got {kv!r}")
    return a


def sample_problem(a: argparse.Namespace) -> str | None:
    """Why the sample options of ``a`` do not fit its input, or None."""
    given = [f"--{k.replace('_', '-')}" for k in ("sample", "sample_per_item", "sample_items", "sample_seed")
             if getattr(a, k, None) is not None]
    if not given:
        return None
    if getattr(a, "sample", None) is None and getattr(a, "sample_per_item", None) is None and \
            getattr(a, "sample_items", None) is None:
        return "--sample-seed orders a sample: give --sample N, --sample-per-item K or --sample-items M"
    for k in ("sample", "sample_per_item", "sample_items"):
        if getattr(a, k, None) is not None and getattr(a, k) < 1:
            return f"--{k.replace('_', '-')} needs at least 1"
    if getattr(a, "page", None) or getattr(a, "items", None):
        return f"{', '.join(given)}: a sample is of IMAGES, --parquet, --manifests or --pages"
    if getattr(a, "max_pages", None) is not None:
        return "--max-pages and --sample exclude each other: --sample N is the sample's first N pages"
    return None


def sample_rule(a: argparse.Namespace):
    """The ``linecaster.data.sample.SampleRule`` of the sample options, or None without them."""
    from linecaster.data.sample import SampleRule

    limits = [getattr(a, k, None) for k in ("sample", "sample_items", "sample_per_item")]
    if all(v is None for v in limits):
        return None
    seed = getattr(a, "sample_seed", None)
    return SampleRule(pages=limits[0], items=limits[1], per_item=limits[2], seed=0 if seed is None else seed)
