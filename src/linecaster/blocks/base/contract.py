"""Block contracts: what one call of a block processes (its unit) and what it reads, adds and replaces in the
record. The builder (``linecaster.runtime.builder``) checks a pipeline's contracts before it runs and derives its
graph from them (``docs/reference/pipelines.md``).

A part is a name of the ``PARTS`` vocabulary (``linecaster.catalog.schema``) and the transcription it belongs to
(``ocr_new``, ``ocr_original``, ...), or ``None`` for page-level parts (``image``, ``metadata``,
``transcription_file``) and for the parts of an item record. ``*`` stands for every part (``Part("*", "ocr_original")``: whatever the library's OCR holds).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ...catalog.schema import PARTS
from ...errors import PipelineConfigError
from .block import Block

#: page-level parts: they belong to no transcription
PAGE_PARTS = frozenset({"image", "metadata", "transcription_file"})
#: the units a stream carries; ``any`` is for blocks that pass whatever comes (servers)
UNITS = ("page", "item", "any")
ROLES = ("reader", "writer", "server", "model", "transform", "binder", "splitter", "validator", "composite")


@dataclass(frozen=True, order=True)
class Part:
    name: str                       # a part of the record (``PARTS``), or ``*``
    transcription: str | None = None  # the transcription it belongs to; None: page-level (or the item record's)

    def __post_init__(self):
        if self.name != "*" and self.name not in PARTS:
            raise PipelineConfigError(f"unknown part {self.name!r}; known: {', '.join(PARTS)}")

    def __str__(self) -> str:
        return self.name if self.transcription is None else f"{self.transcription}:{self.name}"

    @classmethod
    def parse(cls, text: "str | Part") -> "Part":
        """``"image"``, ``"ocr_new:lines"``, ``"ocr_original:*"`` -> a ``Part``."""
        if isinstance(text, Part):
            return text
        transcription, sep, name = text.rpartition(":")
        return cls(name, transcription if sep else None)

    def covers(self, other: "Part") -> bool:
        """Whether this part satisfies a read of ``other`` (a ``*`` covers every part of its transcription; a
        ``*`` without transcription every part)."""
        if self == other:
            return True
        if self.name != "*":
            return False
        return self.transcription is None or self.transcription == other.transcription


def parts(names: Iterable[str], transcription: str | None) -> frozenset[Part]:
    """Parts by name: page-level names (``image``, ``metadata``) without transcription, the others in
    ``transcription``."""
    return frozenset(Part(n, None if n in PAGE_PARTS else transcription) for n in names)


@dataclass(frozen=True)
class Contract:
    unit: str                                   # "page" or "item": what the block's input stream carries ("any")
    unit_out: str | None = None                 # set when the block changes the stream's unit (page <-> item)
    reads: frozenset[Part] = field(default_factory=frozenset)
    adds: frozenset[Part] = field(default_factory=frozenset)
    replaces: frozenset[Part] = field(default_factory=frozenset)
    role: str = ""                              # "reader", "writer", "server", "model", "transform", "binder", ...

    def __post_init__(self):
        for u in (self.unit, self.unit_out):
            if u is not None and u not in UNITS:
                raise PipelineConfigError(f"unknown unit {u!r}; known: {', '.join(UNITS)}")

    @property
    def output_unit(self) -> str:
        return self.unit_out or self.unit

    def describe(self) -> dict:
        out: dict = {"role": self.role, "unit": self.unit}
        if self.unit_out:
            out["unit_out"] = self.unit_out
        for key in ("reads", "adds", "replaces"):
            if getattr(self, key):
                out[key] = sorted(map(str, getattr(self, key)))
        return out


class Contracted(Block):
    """The default ``contract()``: from class attributes (and, from ``Block``, ``warm_up()`` and ``to_dict()``).
    ``parts_read``, ``parts_added`` and ``parts_replaced`` name parts; page-level ones (``image``, ``metadata``) stay
    page-level, the others belong to the block's ``transcription`` attribute (default ``ocr_new``). Blocks whose parts
    depend on their options override ``contract()``."""

    unit: str = "page"
    unit_out: str | None = None
    role: str = "transform"
    parts_read: tuple[str, ...] = ()
    parts_added: tuple[str, ...] = ()
    parts_replaced: tuple[str, ...] = ()

    def _transcription(self) -> str:
        return getattr(self, "transcription", None) or "ocr_new"

    def contract(self) -> Contract:
        t = self._transcription()
        return Contract(unit=self.unit, unit_out=self.unit_out, role=self.role, reads=parts(self.parts_read, t),
                        adds=parts(self.parts_added, t), replaces=parts(self.parts_replaced, t))


def contract_of(block) -> Contract:
    """A block's contract; a block without one (a plain datatrove step) passes pages and touches no part."""
    fn = getattr(block, "contract", None)
    if callable(fn):
        return fn()
    return Contract(unit="page", role="transform")
