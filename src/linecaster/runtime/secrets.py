"""Secrets as references: ``EnvVar("NAME")`` names an environment variable whose value a block reads when it needs
it, in the task (``resolve()``), so the value is never part of a pipeline: not in its pickle (datatrove pickles the
pipeline for every executor), not in ``to_dict()`` (``{"env": "NAME"}``), not in the run record.

    Served("https://api.example.org/v1", model="m", api_key=EnvVar("PROVIDER_API_KEY"),
           headers={"X-Team": "ocr", "X-Token": EnvVar("PROVIDER_TOKEN")})

On HF Jobs the variable comes from the Job's environment (``--env NAME=...`` or the Job's secrets).
"""
from __future__ import annotations

import os

from ..errors import PipelineConfigError


class EnvVar:
    """A secret: the environment variable ``name``, read by ``resolve()``. The instance holds the name only."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        if not name or not isinstance(name, str):
            raise PipelineConfigError(f"EnvVar needs the variable's name, got {name!r}")
        self.name = name

    def resolve(self) -> str:
        """The variable's value, read now; a ``PipelineConfigError`` when it is not set."""
        value = os.environ.get(self.name)
        if value is None:
            raise PipelineConfigError(f"the environment variable {self.name} is not set (a secret this pipeline "
                                      f"reads in the task)")
        return value

    def to_dict(self) -> dict:
        return {"env": self.name}

    def __reduce__(self):            # pickled by name only
        return (EnvVar, (self.name,))

    def __eq__(self, other) -> bool:
        return isinstance(other, EnvVar) and other.name == self.name

    def __hash__(self) -> int:
        return hash(("EnvVar", self.name))

    def __repr__(self) -> str:
        return f"EnvVar({self.name!r})"


def resolve(value):
    """``value`` with an ``EnvVar`` read (anything else as it is)."""
    return value.resolve() if isinstance(value, EnvVar) else value
