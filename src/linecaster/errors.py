"""linecaster's errors. Library code raises these, never ``SystemExit``; only the command line turns them into an
exit code.

* ``PipelineConfigError``: a pipeline that cannot run as built (its contracts do not fit; every problem listed);
* ``CatalogError``: a catalog entry that is missing, unreadable or not what was asked for;
* ``PageError``: one page failed in one block;
* ``ServerError``: a model server did not start or stopped answering.
"""
from __future__ import annotations


class LinecasterError(Exception):
    """The base of linecaster's errors."""


class PipelineConfigError(LinecasterError):
    """A pipeline whose blocks do not fit together. ``problems`` lists every problem the builder found."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("the pipeline cannot run:\n" + "\n".join(f"- {p}" for p in self.problems))


class CatalogError(LinecasterError):
    """A catalog entry that is missing, unreadable or not what was asked for."""


class PageError(LinecasterError):
    """One page failed in one block."""

    def __init__(self, page_id: str, block: str, message: str = ""):
        self.page_id, self.block = page_id, block
        super().__init__(f"page {page_id} failed in {block}" + (f": {message}" if message else ""))


class ServerError(LinecasterError):
    """A model server did not start, or stopped answering."""
