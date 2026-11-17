"""datatrove behavior with linecaster components, against a running ``linecaster serve`` (squiddle models):

1. depends: pipeline A (layout, lines, line assignment) writes page records; pipeline B, launched with
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
from linecaster.components.layout.layout_detector import LayoutDetector
from linecaster.components.lines.line_assigner import LineAssigner
from linecaster.components.lines.line_detector import LineDetector
from linecaster.components.readers.images import ImageFolderReader
from linecaster.components.readers.records import PageRecordReader
from linecaster.components.recognition.line_recognizer import LineRecognizer
from linecaster.components.writers.records import PageJsonlWriter


def executors(images: str, out: pathlib.Path, ep: str):
    a = LocalPipelineExecutor([ImageFolderReader(images), LayoutDetector(Served(ep, "layout")), LineDetector(Served(ep, "lines")),
                               LineAssigner(), PageJsonlWriter(str(out / "A"), "${rank}.jsonl", compression=None)],
                              tasks=3, workers=3, logging_dir=str(out / "logs/A"))
    b = LocalPipelineExecutor([PageRecordReader(str(out / "A")), LineRecognizer(Served(ep, "recognition")),
                               PageJsonlWriter(str(out / "B"), "${rank}.jsonl", compression=None)],
                              tasks=3, workers=3, logging_dir=str(out / "logs/B"), depends=a)
    return a, b


def content(text: str) -> list:
    """Page records without timings (``StepInfo.measurements`` differ from run to run)."""
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
