r"""A run graded by Omni Parse Bench (datalab-to/omni_parse_bench) on an Omni Parse Bench dataset (``omniparsebench.v1``):
linecaster writes the predictions, Omni Parse Bench grades them, its code unchanged.

1. Each task writes its share of the run's pages as Omni Parse Bench predictions
   (``OmniParseBenchPredictionWriter``: OUT/predictions/<page_id>.json, a failed page's failure in OUT/records/).
2. When every task is done, Omni Parse Bench's own grading of OUT on the dataset (``Benchmark.grade``, what
   ``opb grade OUT --dataset DATASET`` runs) writes OUT/unit_tests/: summary.json, scores.jsonl and details/. The one
   difference from ``opb grade``: its unit-test scorer scores ``--grade-workers`` pages at once, in its own process
   pool (omni-bench-core's ``Scorer.workers``, which ``opb grade`` leaves at 1), started fresh once per 10,000 pages
   (``Scorer.batch_size``, 500 under ``opb grade``); the results are the same.

    uv run pipelines/omniparsebench.py OUT --pages RUN/pages --dataset DATASET --tasks 32
    ... --no-grade                     # only the predictions: grade them later with `opb grade OUT --dataset DATASET`
    ... --partial                      # pages of the dataset the run lacks count as failed (else grading refuses)

The tests are the dataset's: a folder of ``manifest.parquet`` and ``gold/<page_id>.json`` (Omni Parse Bench's
docs/API.md), made by whoever owns the ground truth. OUT and the dataset are local folders when grading (Omni Parse
Bench reads files); the run's page records may be anywhere, read without their images. OUT/omniparsebench.yaml
records what graded what and the headline.
"""
from typing import ClassVar

from ..runtime import run


def options(ap):
    ap.add_argument("--dataset", help="the Omni Parse Bench dataset: a local folder or hf://datasets/... (needed)")
    ap.add_argument("--manifest", default="manifest.parquet", help="the dataset's manifest")
    ap.add_argument("--transcription", default="ocr_new", help="the run's transcription written")
    ap.add_argument("--grade-workers", type=int, default=None,
                    help="pages Omni Parse Bench scores at once, in processes (default: the machine's CPUs)")
    ap.add_argument("--partial", action="store_true", help="grade though the run lacks pages: they count as failed")
    ap.add_argument("--no-grade", action="store_true", help="only write the predictions")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str):
    from ..blocks.writers import OmniParseBenchPredictionWriter
    from ..errors import PipelineConfigError

    if not (a.dataset and getattr(a, "pages", None)):
        raise PipelineConfigError("omniparsebench: give --pages (the run's page records) and --dataset")
    out = a.out.rstrip("/")
    if not a.no_grade and "://" in out:
        raise PipelineConfigError("omniparsebench: Omni Parse Bench grades a local folder; give a local OUT, or "
                                  "--no-grade")
    blocks = [run.reader(a, read_images=False), OmniParseBenchPredictionWriter(out, a.transcription)]

    def after() -> None:
        if a.no_grade:
            print(f"predictions in {out}/predictions; grade them with: opb grade {out} --dataset {a.dataset}")
            return
        from ..runtime.cpus import available_cpus

        r = grade(out, a.dataset, a.manifest, a.grade_workers or available_cpus(), a.partial, a.pages, a.transcription)
        s = r["summary"]
        print(f"{'score':10} {s['score']:.4f}")
        for fam, v in (s.get("families") or {}).items():
            print(f"{fam:10} {v['score']:.4f}  ({v['tests']:,} tests, {v['documents']:,} documents)")
        print(f"pages {s['rows']:,}, failed {sum(s['failed'].values()):,}; {out}/unit_tests/summary.json")

    return blocks, {"engines": False, "after": after}


try:
    from omni_parse_bench.scorers.unit_tests import UnitTests as _UnitTests
except ImportError:                              # the extra omniparsebench is not installed: no grading
    _UnitTests = object


class UnitTests(_UnitTests):
    """Omni Parse Bench's unit-test scorer as it is, scoring ``workers`` pages at once in its process pool, which it
    starts once per ``batch_size`` pages (a class at module level, so that the pool's processes can unpickle it).
    Neither changes a score: they are how the core schedules ``score``."""
    workers: ClassVar[int] = 1
    batch_size: ClassVar[int | None] = 10_000


def grade(out: str, dataset: str, manifest: str = "manifest.parquet", workers: int = 1, partial: bool = False,
          pages: str | None = None, transcription: str | None = None) -> dict:
    """Omni Parse Bench's grading of the predictions folder ``out`` on ``dataset`` (``Benchmark.grade``), its unit-test
    scorer with ``workers`` processes; writes ``out``/unit_tests/ (Omni Parse Bench's) and ``out``/omniparsebench.yaml
    (what graded what). Returns the record."""
    import datetime as dt
    import multiprocessing
    from importlib.metadata import version

    import fsspec
    import yaml
    from omni_bench_core import benchmark as core
    from omni_parse_bench import task

    from ..scoring import scorer

    UnitTests.workers = max(1, workers)
    b = core.Benchmark(task.Parse(), dataset, [UnitTests()], manifest)
    # Note: the pool's processes are started fresh ("spawn"), not forked: a fork of this process (the executor's
    # threads, the KaTeX engine Omni Parse Bench's validation started) deadlocks its children.
    before = multiprocessing.get_start_method(allow_none=True)
    multiprocessing.set_start_method("spawn", force=True)
    try:
        graded = b.grade(out, partial=partial)
    finally:
        multiprocessing.set_start_method(before, force=True)
    summary = graded["scorers"][UnitTests().folder_name]
    said: dict = {}
    try:
        with fsspec.open(f"{dataset.rstrip('/')}/dataset.yaml", "rt", encoding="utf-8") as fh:
            said = yaml.safe_load(fh) or {}
    except (FileNotFoundError, OSError):
        pass
    record = {"schema": "linecaster.omniparsebench-run/1", "package": f"omni-parse-bench {version('omni-parse-bench')}",
              "core": f"omni-bench-core {version('omni-bench-core')}", "dataset": str(dataset), "manifest": manifest,
              "dataset_record": said, "pages": str(pages) if pages else None, "transcription": transcription,
              "grade_workers": UnitTests.workers, "partial": partial,
              "headline": {"score": summary.get("score"), "rows": summary.get("rows"), "failed": summary.get("failed"),
                           "families": summary.get("families")},
              "results": f"{out}/unit_tests/summary.json", "linecaster": scorer(), "date": dt.date.today().isoformat()}
    with fsspec.open(f"{out}/omniparsebench.yaml", "wt", encoding="utf-8") as fh:
        fh.write(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return {"record": record, "summary": summary}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "omniparsebench.v1"
SLOTS: dict[str, str] = {}
