"""datatrove behaviour with linecaster blocks, against a running ``linecaster serve`` (squiddle models):

1. depends: pipeline A (layout, lines, line assignment) writes page rows; pipeline B, launched with
   ``depends=A``, reads A's rows (images fetched again by URI) and adds recognition.
2. resume: B runs as 3 tasks; one task's output and completion marker are deleted; re-running the same
   executors recomputes only that task (datatrove's completion markers) and gives the same rows.

    .venv/bin/python tests/integration/datatrove_resume_depends.py IMAGES OUT [ENDPOINT]
"""
import json
import pathlib
import shutil
import sys

from datatrove.executor import LocalPipelineExecutor

from linecaster.backends import Served
from linecaster.blocks.lines import AssignLinesToRegions
from linecaster.blocks.models import LayoutStep, LinesStep, RecognitionStep
from linecaster.blocks.readers import ImageFolderReader, PageRowReader
from linecaster.blocks.writers import PageJsonlWriter


def executors(images: str, out: pathlib.Path, ep: str):
    a = LocalPipelineExecutor([ImageFolderReader(images), LayoutStep(Served(ep, "layout")), LinesStep(Served(ep, "lines")),
                               AssignLinesToRegions(), PageJsonlWriter(str(out / "A"), "${rank}.jsonl", compression=None)],
                              tasks=3, workers=3, logging_dir=str(out / "logs/A"))
    b = LocalPipelineExecutor([PageRowReader(str(out / "A")), RecognitionStep(Served(ep, "recognition")),
                               PageJsonlWriter(str(out / "B"), "${rank}.jsonl", compression=None)],
                              tasks=3, workers=3, logging_dir=str(out / "logs/B"), depends=a)
    return a, b


def content(text: str) -> list:
    """Page rows without timings (``ModelInfo.measurements`` differ from run to run)."""
    rows = []
    for line in text.splitlines():
        row = json.loads(line)
        for t in row["page"]["transcriptions"].values():
            for m in t["model"]:
                m["measurements"] = {}
        rows.append(json.dumps(row, sort_keys=True))
    return sorted(rows)


def main() -> None:
    images, out = sys.argv[1], pathlib.Path(sys.argv[2])
    ep = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8100/v1"
    shutil.rmtree(out, ignore_errors=True)
    executors(images, out, ep)[1].run()          # runs A first (depends), then B
    first = {p.name: p.read_text() for p in sorted((out / "B").glob("*.jsonl"))}
    print("B outputs:", {k: len(v.splitlines()) for k, v in first.items()})
    victim = sorted((out / "logs/B/completions").iterdir())[1]
    (out / "B" / f"{int(victim.name):05d}.jsonl").unlink()
    victim.unlink()
    print("deleted task", victim.name, "output and completion marker; re-running")
    executors(images, out, ep)[1].run()
    second = {p.name: p.read_text() for p in sorted((out / "B").glob("*.jsonl"))}
    same = sorted(first) == sorted(second) and all(content(first[k]) == content(second[k]) for k in first)
    print(json.dumps({"pages": sum(len(v.splitlines()) for v in second.values()), "resume_identical": same}))


if __name__ == "__main__":
    main()
