r"""Scoring: a run's page records against a ground truth's, by a benchmark, over many tasks (``score.v1``). Each task
scores a share of the run's pages (``PageScorer``: their ground truth read in one pass, each page rendered and
normalized as the benchmark says) and writes their score records (``ScoreWriter``: OUT/records, OUT/pages); when
every task is done the driver puts them together (``linecaster.scoring.run.aggregate``: the pages the run lacks
scored as empty outputs, the corpus rates with their bootstrap intervals, the conventions check) into
OUT/scores.parquet and OUT/evidence.yaml, as ``linecaster score`` writes them in one process.

    uv run pipelines/score.py RUN/scores --pages RUN/pages --truth TRUTH --benchmark benchmark.yaml
    uv run pipelines/score.py s3://bucket/run/scores --pages s3://bucket/run/pages --truth s3://bucket/truth \
        --benchmark benchmark.yaml --preset lightonocr-3-0.8b --on ray --tasks 32
    ... --workers 64                                   # tasks at once on this machine

The run's page records are read without their images. Any number of tasks: with more tasks than page-record
files, the tasks share each file (every k-th record each), so --tasks 100 uses 100 cores whatever the run wrote. The benchmark's file is read here and travels with the tasks; the ground truth folder must be
readable where the tasks run (object storage on a cluster). --preset names the preset measured when the run follows
no recipe (as ``linecaster score``), --context the rest of the pipeline it was measured in.
"""
from ..runtime import run


def options(ap):
    ap.add_argument("--truth", help="the ground truth's page records (a folder: local or fsspec URI; needed)")
    ap.add_argument("--benchmark", help="the benchmark definition (linecaster.benchmark/2 YAML; needed)")
    ap.add_argument("--transcription", default="ocr_new", help="the run's transcription scored")
    ap.add_argument("--preset", help="the preset measured (id), when the run follows no recipe")
    ap.add_argument("--context", help="for a preset measured inside a pipeline: the rest of it")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str):
    from ..blocks.scoring import PageScorer
    from ..blocks.writers import ScoreWriter
    from ..catalog import yamlio
    from ..errors import PipelineConfigError

    if not (a.truth and a.benchmark and getattr(a, "pages", None)):
        raise PipelineConfigError("score: give --pages (the run's page records), --truth and --benchmark")
    import fsspec

    with fsspec.open(a.benchmark, "rt", encoding="utf-8") as fh:
        bench = yamlio.load(fh.read())
    out = a.out.rstrip("/")
    blocks = [run.reader(a, read_images=False), PageScorer(a.truth, bench, a.transcription),
              ScoreWriter(out)]

    def after() -> None:
        report(out, a.pages, a.truth, bench, a.transcription, a.preset, a.context)

    return blocks, {"engines": False, "after": after}


def report(out: str, pages: str, truth: str, bench_data: dict, transcription: str = "ocr_new",
           preset: str | None = None, context: str | None = None) -> dict:
    """The tasks' score files put together (``aggregate``), written as OUT/scores.parquet and OUT/evidence.yaml, and
    the rates printed as ``linecaster score`` prints them."""
    from ..catalog.registry import rendering_policy
    from ..scoring.benchmark import read_benchmark
    from ..scoring.evidence import evidence, write_evidence
    from ..scoring.run import aggregate, write_scores

    bench = read_benchmark(bench_data)
    result = aggregate(out, truth, bench, transcription, rendering_policy(bench.policy))
    write_scores(result["records"], f"{out}/scores.parquet")
    run_folder = pages.rstrip("/").rsplit("/", 1)[0] if pages.rstrip("/").endswith("/pages") else pages
    write_evidence(evidence(result, bench, run_folder, preset=preset, context=context), f"{out}/evidence.yaml")
    for name, m in sorted(result["rates"].items()):
        lo, hi = m.get("lo"), m.get("hi")
        interval = f" [{lo:.4f}, {hi:.4f}]" if lo is not None else ""
        print(f"{name:32s} {m['value']:.4f}{interval}" if m["value"] is not None else f"{name:32s} -")
    for ln, missing_n in sorted(result["conventions"].items()):
        print(f"conventions: lane {ln} does not apply {', '.join(missing_n)}, which the ground truth does")
    print(f"pages {result['pages_scored']}, missing {result['missing']}, failed {result['failed']}; "
          f"{'eligible' if result['eligible'] else 'NOT eligible'}; {out}")
    return result


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "score.v1"
SLOTS: dict[str, str] = {}
