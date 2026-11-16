r"""OmniDocBench's own evaluation of a run against a linecaster ground truth, over many tasks (``harness.v1``), in
linecaster's process (``linecaster.scoring.omnidocbench``: the harness's code at its pinned commit, imported). Each task
scores its share of the run's pages (``OmniDocBenchScorer``: both sides in OmniDocBench's formats, in memory; its
matching and metrics) and writes their samples (``OmniDocBenchWriter``: OUT/samples); when every task is done the
ground truth's pages the run lacks are scored as empty predictions, and every page's samples are put together by the
harness's own aggregation into OUT/result.json (the harness's metric result: per module ``all``, ``group``,
``page``) and OUT/harness.yaml (what produced it and the headline numbers).

    uv run pipelines/harness.py OUT --pages RUN/pages --truth TRUTH/pages --tasks 100
    ... --ids IDS                        # only these pages (a file, one id per line)
    ... --on ray --tasks 1024            # on a Ray cluster (the ground truth readable where the tasks run)

The run's page records are read without their images; with more tasks than page-record files the tasks share each
file (every k-th record), which spreads slow pages (dense formulas, large tables) over the tasks. The result equals
the pinned harness run unchanged on every page (``linecaster harness``, the reference to check it against).
"""
from ..runtime import run


def options(ap):
    ap.add_argument("--truth", help="the ground truth's page records (a folder: local or fsspec URI; needed)")
    ap.add_argument("--transcription", default="ocr_new", help="the run's transcription scored")
    ap.add_argument("--truth-transcription", default="ground_truth", help="the ground truth's transcription")
    ap.add_argument("--ids", help="a file of page ids (one per line): only these pages")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str):
    from ..blocks.scoring import OmniDocBenchScorer
    from ..blocks.writers import OmniDocBenchWriter
    from ..errors import PipelineConfigError
    from ..scoring.omnidocbench import NAME
    from ..scoring.harness import source

    if not (a.truth and getattr(a, "pages", None)):
        raise PipelineConfigError("harness: give --pages (the run's page records) and --truth")
    source(NAME)                                 # fetched here once, before the tasks start
    import fsspec

    ids = None
    if a.ids:
        with fsspec.open(a.ids, "rt") as fh:
            ids = sorted(set(fh.read().split()))
    out = a.out.rstrip("/")
    blocks = [run.reader(a, read_images=False),
              OmniDocBenchScorer(a.truth, a.transcription, a.truth_transcription, ids), OmniDocBenchWriter(out)]

    def after() -> None:
        r = report(out, a.pages, a.truth, a.transcription, a.truth_transcription, set(ids) if ids is not None else None)
        for k, v in r["metrics"].items():
            if k != "groups":
                print(f"{k:22} {v:.4f}")
        print(f"pages {r['counts']['pages']:,}, missing {r['counts']['missing']:,}; {out}/harness.yaml")

    return blocks, {"engines": False, "after": after}


def report(out: str, pages: str, truth: str, transcription: str = "ocr_new", truth_transcription: str = "ground_truth",
           ids: set[str] | None = None) -> dict:
    """Every task's samples put together: the ground truth's pages the run lacks scored as empty predictions, the
    harness's aggregation, OUT/result.json and OUT/harness.yaml. A page of the run with ground truth that no task
    scored is an error (a task failed), never a missing page."""
    import datetime as dt
    import gzip
    import json

    import fsspec
    import yaml
    from datatrove.io import get_datafolder

    from ..data import Page
    from ..data.upgrade import upgrade
    from ..errors import LinecasterError
    from ..formats.omnidocbench import truth_page
    from ..scoring import scorer
    from ..scoring.harness import HARNESSES, _attributes, _truth_ids, summarize
    from ..scoring.omnidocbench import NAME, aggregate, page_summary, score_pages
    from ..scoring.run import read_truth

    folder = get_datafolder(out)
    samples: dict[str, list] = {}
    summaries: list[dict] = []
    scored: set[str] = set()
    for name in sorted(folder.list_files("samples", glob_pattern="*.jsonl.gz")):
        with folder.open(name, "rb") as raw, gzip.open(raw, "rt", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                scored.add(row["id"])
                summaries.append(row["page"])
                for element, ss in row["samples"].items():
                    samples.setdefault(element, []).extend(ss)
    wanted = set(ids) if ids is not None else _truth_ids(truth)
    in_run = wanted & _truth_ids(pages)
    if in_run - scored:
        raise LinecasterError(f"harness: {len(in_run - scored):,} pages of the run were scored by no task (a task "
                              f"failed: see its log); not aggregated")
    lacking = sorted(wanted - in_run)
    if lacking:                                  # the run lacks them: the harness scores an empty prediction
        rows = read_truth(truth, set(lacking))
        gts = [truth_page(pid, g, attributes=_attributes(g)) for pid, g in
               ((pid, Page.model_validate(upgrade(rows[pid])["page"]).transcriptions[truth_transcription])
                for pid in lacking)]
        for element, ss in score_pages([(g, "") for g in gts]).items():
            samples.setdefault(element, []).extend(ss)
        summaries += [page_summary(g) for g in gts]
    result = aggregate(samples, summaries)
    h = HARNESSES[NAME]
    record = {"schema": "linecaster.harness-run/1", "harness": NAME, "repo": h["repo"], "commit": h["commit"],
              "process": "in linecaster (linecaster.scoring.omnidocbench)", "pages": str(pages), "truth": str(truth),
              "transcription": transcription, "truth_transcription": truth_transcription,
              "counts": {"pages": len(summaries), "missing": len(lacking)}, "metrics": summarize(result),
              "scorer": scorer(), "date": dt.date.today().isoformat()}
    with fsspec.open(f"{out}/result.json", "wt", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, default=float)
    with fsspec.open(f"{out}/harness.yaml", "wt", encoding="utf-8") as fh:
        fh.write(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return record


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "harness.v1"
SLOTS: dict[str, str] = {}
