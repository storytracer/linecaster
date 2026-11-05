"""linecaster's errors. Library code raises these, never ``SystemExit``; only the command line (``linecaster.cli``,
``linecaster.runtime.run.main``) turns them into an exit code.

* ``PipelineConfigError``: a pipeline that cannot run as built: its contracts do not fit (every problem listed), an
  option or a block's parameter is wrong, its input is missing, or its run folder belongs to another pipeline;
* ``CatalogError``: a catalog entry that is missing, unreadable or not what was asked for;
* ``PageError``: one page failed in one block (or a task failed more pages than its error budget allows);
* ``ServerError``: a model server did not start or stopped answering.
"""
from __future__ import annotations


class LinecasterError(Exception):
    """The base of linecaster's errors."""


class PipelineConfigError(LinecasterError):
    """A pipeline that cannot run as built. ``problems`` lists every problem found (one message or several)."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("the pipeline cannot run:\n" + "\n".join(f"- {p}" for p in self.problems))


class CatalogError(LinecasterError):
    """A catalog entry that is missing, unreadable or not what was asked for."""


class PageError(LinecasterError):
    """One page failed in one block (``block``: its datatrove name or class name, if known)."""

    def __init__(self, page_id: str, block: str | None = None, message: str = ""):
        self.page_id, self.block = page_id, block
        where = f" in {block}" if block else ""
        super().__init__(f"page {page_id} failed{where}" + (f": {message}" if message else ""))


class ServerError(LinecasterError):
    """A model server did not start, or stopped answering."""


def exit_code(error: BaseException) -> int:
    """The command line's exit code for ``error``: 2 for a pipeline that cannot run (nothing was launched), 1 for
    anything else."""
    return 2 if isinstance(error, PipelineConfigError) else 1
