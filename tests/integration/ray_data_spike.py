"""Ray Data spike (phase 6): a recipe's per-page blocks as Ray Data ``map_batches`` stages, one actor per block and
the pages streaming between them, instead of a datatrove executor.

The recipe's pipeline is built as a normal run builds it: the pipeline shape's ``pipeline()`` with ``--recipe``,
then the builder (one task, no run folder, so no rejects writer and no tracing). The reader reads the pages in the
driver; every block between the reader and the writers becomes one ``map_batches`` stage (``batch_size=1``: one page
per request) run by a single actor that calls ``warm_up()`` once and then the block's ``run`` on each page. Model
blocks share the GPU (``num_gpus`` = 1 / their number); rule blocks run on CPUs. Between stages a page travels as a
plain row: ``id``, ``text``, ``metadata`` (JSON), ``media`` (the image's ``Media`` fields as JSON) and ``image``
(its bytes). The page records go to ``OUT/pages.json`` (page id -> the row ``PageJsonlWriter`` writes), the timings
to ``OUT/timings.json``, Ray Data's stats to ``OUT/ray-stats.txt``.

``--compare RUN`` compares each page's transcription with a normal run's page records (``RUN/pages/*.jsonl.gz``),
leaving out every step's ``measurements.seconds`` and ``measurements.datetime``.

    PY=$(uv python find --script pipelines/transcribe_modular.py)
    $PY tests/integration/ray_data_spike.py IMAGES OUT [--recipe squiddle] [--compare RUN]
    $PY tests/integration/ray_data_spike.py --compare-only RUN OUT     # compare an earlier spike's OUT again

Ray starts locally with the loopback address only (nothing listens on other interfaces; checked while the actors
run) and is shut down at the end.
"""
import argparse
import copy
import glob
import gzip
import ipaddress
import json
import os
import time
from pathlib import Path

# Ray's single-machine mode: the node address is the loopback address and every Ray process listens on it alone.
# Read when ray is imported (only in run_ray), so set before.
os.environ.setdefault("RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER", "0")

START = time.time()
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "pipelines" / "transcribe_modular.py"
#: the measurements that differ from run to run
VARYING = ("seconds", "datetime")
#: CPUs per actor: model blocks (their engines' CPU work: decoding, pre- and post-processing) and rule blocks
MODEL_CPUS, RULE_CPUS = 3, 0.5


# ------------------------------------------------------------------------------------------------- the blocks
def recipe_blocks(images: str, out: str, recipe: str):
    """The reader and the per-page blocks of ``recipe``'s pipeline, as the builder expands them for a normal run of
    one task (composites expanded, the recipe stamper added); the writers are left out."""
    from linecaster.pipelines import transcribe_modular as module
    from linecaster.runtime import builder, run

    a = run.parse([images, out, "--recipe", recipe], module.__doc__, module.options, module.PIPELINE, module.SLOTS)
    blocks = module.pipeline(a, str(SCRIPT))
    rec = a.recipe_record
    plan = builder.build(blocks, tasks=1, run_folder=None, recipe=(rec["ref"], rec["sha256"]))
    plan.check()
    if len(plan.stages) != 1:
        raise SystemExit(f"{recipe}: {len(plan.stages)} stages; the spike runs one page stage")
    reader, *rest = plan.stages[0].blocks
    page_blocks = [b for b in rest if getattr(b, "role", None) not in ("writer", "server")]
    return reader, page_blocks, rec


# ----------------------------------------------------------------------------------- pages as Ray Data rows
MEDIA_FIELDS = ("id", "type", "url", "alt", "path", "offset", "length", "metadata")


def to_row(doc) -> dict:
    """A page document as a plain row (one image per page, as linecaster's readers make them)."""
    (media,) = doc.media
    return {"id": doc.id, "text": doc.text, "metadata": json.dumps(doc.metadata, ensure_ascii=False),
            "media": json.dumps({k: getattr(media, k) for k in MEDIA_FIELDS}, ensure_ascii=False),
            "image": media.media_bytes}


def to_doc(row: dict):
    from datatrove.data import Document, Media

    return Document(text=row["text"], id=row["id"], media=[Media(**json.loads(row["media"]), media_bytes=row["image"])],
                    metadata=json.loads(row["metadata"]))


class BlockStage:
    """One block as a Ray Data actor: warmed up once, then a page per call."""

    def __init__(self, block, label: str, log_folder: str):
        self.block, self.label = block, label
        start = time.time()
        block.warm_up()
        end = time.time()
        Path(log_folder, f"{label}.json").write_text(json.dumps(
            {"block": label, "pid": os.getpid(), "warm_up_start": start, "warm_up_end": end,
             "warm_up_seconds": round(end - start, 3), "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
             "omp_num_threads": os.environ.get("OMP_NUM_THREADS")}))

    def __call__(self, batch):
        import pyarrow as pa

        out = []
        for row in batch.to_pylist():
            out.extend(to_row(d) for d in self.block.run(iter([to_doc(row)]), 0, 1))
        return pa.Table.from_pylist(out, schema=batch.schema)


# ------------------------------------------------------------------------------------------------------ Ray
def listening_elsewhere() -> list[str]:
    """Listening sockets of this process and its descendants (Ray's processes) on anything but loopback."""
    import psutil

    me = psutil.Process()
    pids = {me.pid, *(p.pid for p in me.children(recursive=True))}
    bad = []
    for c in psutil.net_connections(kind="inet"):
        if c.status != psutil.CONN_LISTEN or c.pid not in pids or not c.laddr:
            continue
        ip = ipaddress.ip_address(c.laddr.ip)
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_loopback:
            bad.append(f"pid {c.pid} {c.laddr.ip}:{c.laddr.port}")
    return bad


def run_ray(rows: list[dict], page_blocks: list, out: Path) -> tuple[dict, dict]:
    import ray
    import ray.data

    from linecaster.blocks.base.model import ModelBlock
    from linecaster.blocks.writers.records import page_record

    t = {}
    log_folder = out / "warm-up"
    log_folder.mkdir(parents=True, exist_ok=True)
    models = sum(isinstance(b, ModelBlock) for b in page_blocks)
    share = int(10000 / max(models, 1)) / 10000          # Ray counts GPU shares in 1/10000
    t0 = time.time()
    ray.init(address="local", include_dashboard=False, num_gpus=1)
    t["ray_init"] = time.time() - t0
    bad = []
    try:
        ctx = ray.data.DataContext.get_current()
        ctx.enable_progress_bars = False
        ctx.execution_options.preserve_order = False
        ds = ray.data.from_items(rows, override_num_blocks=len(rows))
        stages = []
        for i, block in enumerate(page_blocks):
            gpu = isinstance(block, ModelBlock)
            label = f"{i + 1:02d}-{type(block).__name__}"
            stages.append({"stage": label, "num_gpus": share if gpu else 0, "num_cpus": MODEL_CPUS if gpu else RULE_CPUS})
            ds = ds.map_batches(BlockStage, batch_size=1, batch_format="pyarrow",
                                compute=ray.data.ActorPoolStrategy(size=1), num_cpus=MODEL_CPUS if gpu else RULE_CPUS, **({"num_gpus": share} if gpu else {}),
                                fn_constructor_kwargs={"block": block, "label": label, "log_folder": str(log_folder)})
        records, first = {}, None
        t0 = time.time()
        for row in ds.iter_rows():
            if first is None:
                first = time.time()
                bad = listening_elsewhere()        # every actor is up once a page has gone through them all
                if bad:
                    break
            doc = to_doc(row)
            records[doc.id] = page_record(None, doc)
        last = time.time()
        t.update(execution=last - t0, first_page=(first or last) - t0)
        try:
            (out / "ray-stats.txt").write_text(ds.stats())
        except Exception as e:  # noqa: BLE001 - the stats are a convenience
            (out / "ray-stats.txt").write_text(f"no stats: {type(e).__name__}: {e}")
        warm = [json.loads(p.read_text()) for p in sorted(log_folder.glob("*.json"))]
        ready = max((w["warm_up_end"] for w in warm), default=t0)
        t["after_last_warm_up"] = last - ready
        t["warm_up_seconds"] = {w["block"]: w["warm_up_seconds"] for w in warm}
        t["actors"] = {w["block"]: {k: w[k] for k in ("cuda_visible_devices", "omp_num_threads")} for w in warm}
        t["stages"] = stages
    finally:
        t0 = time.time()
        ray.shutdown()
        t["ray_shutdown"] = time.time() - t0
    if bad:
        raise SystemExit(f"Ray listens on other interfaces than loopback: {bad}")
    return records, t


# -------------------------------------------------------------------------------------------- the comparison
def without_varying(t: dict) -> dict:
    t = copy.deepcopy(t)
    for step in t.get("steps") or []:
        for k in VARYING:
            (step.get("measurements") or {}).pop(k, None)
    return t


def differences(a, b, path: str = "") -> list[str]:
    """The paths where ``a`` and ``b`` differ (the first difference down each branch)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}.{k} (only in {'spike' if k in a else 'normal run'})")
            else:
                out.extend(differences(a[k], b[k], f"{path}.{k}"))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path} (length {len(a)} vs {len(b)})"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {json.dumps(a, ensure_ascii=False)[:120]} vs {json.dumps(b, ensure_ascii=False)[:120]}"]


def normal_records(run: str) -> dict:
    out = {}
    for path in sorted(glob.glob(f"{run.rstrip('/')}/pages/**/*.jsonl.gz", recursive=True)):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                out[row["id"]] = row
    return out


def compare(spike: dict, normal: dict, transcription: str) -> dict:
    """Per page: the transcription ``transcription`` without the varying measurements; and the whole row (text,
    every transcription, the image, errors) the same way."""
    same, different, whole_same, details = 0, 0, 0, {}
    for pid in sorted(set(spike) | set(normal)):
        if pid not in spike or pid not in normal:
            details[pid] = [f"only in {'spike' if pid in spike else 'normal run'}"]
            different += 1
            continue
        a, b = spike[pid], normal[pid]
        ta = without_varying(((a.get("page") or {}).get("transcriptions") or {}).get(transcription) or {})
        tb = without_varying(((b.get("page") or {}).get("transcriptions") or {}).get(transcription) or {})
        d = differences(ta, tb, transcription)
        if d:
            different += 1
            details[pid] = d[:20] + ([f"... {len(d) - 20} more"] if len(d) > 20 else [])
        else:
            same += 1
        wa, wb = copy.deepcopy(a), copy.deepcopy(b)
        for w in (wa, wb):
            ts = (w.get("page") or {}).get("transcriptions") or {}
            for k in ts:
                ts[k] = without_varying(ts[k])
        whole_same += not differences(wa, wb)
    return {"pages_spike": len(spike), "pages_normal": len(normal), "transcription": transcription,
            "ignored": [f"steps[*].measurements.{k}" for k in VARYING], "identical": same, "different": different,
            "whole_rows_identical": whole_same, "differences": details}


# ------------------------------------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="?", help="a folder of page images")
    ap.add_argument("out", help="where the spike writes pages.json, timings.json, ray-stats.txt")
    ap.add_argument("--recipe", default="squiddle")
    ap.add_argument("--compare", metavar="RUN", help="a normal run's folder (RUN/pages/*.jsonl.gz)")
    ap.add_argument("--compare-only", metavar="RUN", help="only compare OUT/pages.json with RUN")
    ap.add_argument("--transcription", default="ocr_new")
    a = ap.parse_args()
    out = Path(a.out)
    if a.compare_only:
        spike = json.loads((out / "pages.json").read_text())
        result = compare(spike, normal_records(a.compare_only), a.transcription)
        (out / "comparison.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps({k: v for k, v in result.items() if k != "differences"}, indent=1))
        return
    if not a.images:
        ap.error("IMAGES is needed unless --compare-only")
    out.mkdir(parents=True, exist_ok=True)
    import torch

    timings = {"torch": torch.__version__, "imports": time.time() - START}
    t0 = time.time()
    reader, page_blocks, rec = recipe_blocks(a.images, str(out), a.recipe)
    timings["build"] = time.time() - t0
    t0 = time.time()
    rows = [to_row(d) for d in reader(None, 0, 1)]
    timings["read"] = time.time() - t0
    timings["pages"] = len(rows)
    timings["recipe"] = rec["ref"]
    timings["blocks"] = [type(b).__name__ for b in page_blocks]
    records, ray_timings = run_ray(rows, page_blocks, out)
    timings.update(ray_timings)
    (out / "pages.json").write_text(json.dumps(records, ensure_ascii=False))
    timings["total_in_script"] = time.time() - START
    (out / "timings.json").write_text(json.dumps(timings, indent=1))
    print(json.dumps({k: v for k, v in timings.items() if k not in ("stages", "actors")}, indent=1))
    if a.compare:
        result = compare(records, normal_records(a.compare), a.transcription)
        (out / "comparison.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps({k: v for k, v in result.items() if k != "differences"}, indent=1))


if __name__ == "__main__":
    main()
