"""``Pipeline``: an ordered list of components, checked, run and recorded as one thing.

    from linecaster import Pipeline
    from linecaster.components.readers import ImageFolderReader
    from linecaster.components.recognition import PageRecognizer
    from linecaster.components.writers import PageJsonlWriter

    pipeline = Pipeline([ImageFolderReader("scans/"), PageRecognizer("lightonocr-2-1b"),
                         PageJsonlWriter("out/pages")])
    pipeline.check()                    # the contracts, before anything runs
    pipeline.run("out")                 # on this machine; ``pipeline.plan()`` gives the stages for any executor

A pipeline names its servers apart from its components (``servers=``): they start with a task and stop with it, and
the pipeline puts them where datatrove needs them, after the last component. ``to_dict()`` and ``from_dict()`` take
a pipeline to plain data and back. Importing this module loads no executor and no engine.
"""
from __future__ import annotations

from typing import Any


class Pipeline:
    """An ordered list of components that a stream of pages passes through.

    Args:
        components: the components and composites, in order: a reader first, writers last.
        servers: the server components the pipeline's model components need inside a task (``EngineServer``,
            ``VLMServer``, ``VendorServer``); default none (the models run in-process, or their servers run
            elsewhere).

    Example:
        Pipeline([ImageFolderReader("scans/"), LineDetector("pp-ocrv6-medium-det"),
                  LineRecognizer("kraken-ppocrv6-medium"), PageJsonlWriter("out/pages")]).check()
    """

    def __init__(self, components: list, *, servers: list | None = None):
        self.components = list(components)
        self.servers = list(servers or [])

    def steps(self) -> list:
        """The components and then the servers: the list a datatrove executor runs."""
        return [*self.components, *self.servers]

    def plan(self, **options):
        """The pipeline as a plan of stages (``linecaster.execution.builder.build``): composites expanded, contracts
        analyzed, cut where the stream changes from pages to items. ``options`` are ``build``'s (``tasks``,
        ``run_folder``, ``until``, ``after``, ``taps``, ...). The plan holds the problems it found; ``check()``
        raises them."""
        from linecaster.execution.builder import build

        return build(self.steps(), **options)

    def check(self, **options):
        """Checks the contracts and returns the plan; a pipeline that cannot run is a ``PipelineConfigError`` that
        names every problem."""
        plan = self.plan(**options)
        plan.check()
        return plan

    def draw(self, **options) -> str:
        """The pipeline's graph as Mermaid text: its components and the parts that go from one to the next."""
        return self.plan(**options).mermaid()

    def run_pages(self, docs=(), *, observers: list | None = None) -> list:
        """Runs the pipeline on datatrove documents in this process, without an executor, and returns what comes
        out (``linecaster.execution.builder.run_pages``): for a page at a time, and for tests."""
        from linecaster.execution.builder import run_pages

        return run_pages(self.steps(), docs, observers=observers)

    def run(self, out: str, *, tasks: int = 1, workers: int | None = None, **options) -> None:
        """Runs the pipeline on this machine with datatrove's local executor, stage after stage.

        Args:
            out: the run folder: logs go to ``out/logs``, rejects to ``out/rejects``, traces to ``out/traces``.
            tasks: the tasks the input is divided into.
            workers: the tasks running at once; default all of them.
            **options: ``plan()``'s other options.
        """
        from linecaster.execution.local import LocalExecutor

        plan = self.check(tasks=tasks, run_folder=out, **options)
        many, previous = len(plan.stages) > 1, None
        for stage in plan.stages:
            logs = f"{out}/logs/{stage.name}" if many else f"{out}/logs"
            reader = next((c for c in stage.components if hasattr(c, "task_pages")), None)
            previous = LocalExecutor(stage.pipeline, tasks=stage.tasks, workers=min(workers or stage.tasks, stage.tasks),
                                     logging_dir=logs, depends=previous, out=out, reader=reader,
                                     title=stage.name if many else "run")
        if previous is not None:
            previous.run()

    def to_dict(self) -> dict[str, Any]:
        """``{"components": [...], "servers": [...]}``, each component as its ``to_dict()``."""
        from linecaster.execution.builder import component_dict

        out: dict[str, Any] = {"components": [component_dict(c) for c in self.components]}
        if self.servers:
            out["servers"] = [component_dict(c) for c in self.servers]
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Pipeline":
        """The pipeline a ``to_dict()`` describes (``Component.from_dict`` for each entry)."""
        from linecaster.core.component import Component

        return cls([Component.from_dict(c) for c in data.get("components") or []],
                   servers=[Component.from_dict(c) for c in data.get("servers") or []])

    def __len__(self) -> int:
        return len(self.components)

    def __repr__(self) -> str:
        return f"Pipeline([{', '.join(type(c).__name__ for c in self.components)}])"
