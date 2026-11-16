r"""A benchmark's own harness on a run, against a linecaster ground truth, over many tasks (``harness.v1``). Each task
writes its share of the run's pages as a shard (``HarnessWriter``: their ground truth in the harness's format, the
run's pages as its predictions) and runs the harness on it in one process; when every task is done, the ground
truth's pages no task had (the run lacks them) are scored as empty predictions and the shards' results put together
by the harness's own aggregation (``linecaster.scoring.harness.finish``) into OUT/result/merged_metric_result.json
and OUT/harness.yaml.

    uv run pipelines/harness.py OUT --pages RUN/pages --truth TRUTH/pages --harness omnidocbench --tasks 100
    ... --ids IDS                        # only these pages (a file, one id per line)
    ... --on ray --tasks 300             # on a Ray cluster (the ground truth readable where the tasks run)

The run's page records are read without their images; with more tasks than page-record files the tasks share each
file. The harness's environment is built by uv on first use (``linecaster.scoring.harness.environment``).
"""
from ..runtime import run


def options(ap):
    ap.add_argument("--truth", help="the ground truth's page records (a folder: local or fsspec URI; needed)")
    ap.add_argument("--harness", default="omnidocbench", help="the harness (default omnidocbench)")
    ap.add_argument("--transcription", default="ocr_new", help="the run's transcription scored")
    ap.add_argument("--truth-transcription", default="ground_truth", help="the ground truth's transcription")
    ap.add_argument("--ids", help="a file of page ids (one per line): only these pages")
    ap.add_argument("--cdm", action="store_true", help="OmniDocBench's CDM for formulas (TeX Live, ImageMagick)")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str):
    from ..blocks.writers import HarnessWriter
    from ..errors import PipelineConfigError
    from ..scoring.harness import HARNESSES, environment, finish

    if not (a.truth and getattr(a, "pages", None)):
        raise PipelineConfigError("harness: give --pages (the run's page records) and --truth")
    if a.harness not in HARNESSES:
        raise PipelineConfigError(f"harness: unknown harness {a.harness!r}; known: {sorted(HARNESSES)}")
    if a.cdm and a.tasks not in (None, 1):
        raise PipelineConfigError("harness: --cdm runs in one task (CDM results are not merged across shards)")
    environment(a.harness)                       # built here once, before the tasks start
    import fsspec

    ids = None
    if a.ids:
        with fsspec.open(a.ids, "rt") as fh:
            ids = sorted(set(fh.read().split()))
    out = a.out.rstrip("/")
    blocks = [run.reader(a, read_images=False),
              HarnessWriter(out, a.truth, a.harness, a.transcription, a.truth_transcription, ids, a.cdm)]

    def after() -> None:
        r = finish(a.harness, out, a.pages, a.truth, a.transcription, a.truth_transcription,
                   set(ids) if ids is not None else None, a.cdm)
        for k, v in r["metrics"].items():
            if k != "groups":
                print(f"{k:22} {v:.4f}")
        print(f"pages {r['counts']['pages']:,}, missing {r['counts']['missing']:,}, shards {r['counts']['shards']:,}; "
              f"{out}/harness.yaml")

    return blocks, {"engines": False, "after": after}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "harness.v1"
SLOTS: dict[str, str] = {}
