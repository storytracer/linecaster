"""``Composite``: a named group of blocks with its own outward contract. The builder
(``linecaster.runtime.builder``) expands it into its blocks; the graph and the plan keep the group."""
from __future__ import annotations

from ...errors import PipelineConfigError
from .block import Block
from .contract import Contract, contract_of


class Composite(Block):
    """A named group of ``blocks`` (blocks or composites, in order). Its contract is ``contract`` when given, else
    derived from its blocks: what they read that no block inside adds, what they add and replace, the first block's
    unit and the last one's output unit. It is not a datatrove step: run it through the builder. ``to_dict()`` is
    the group: its parameters and its blocks' dicts."""

    role = "composite"

    def __init__(self, name: str, blocks: list, contract: Contract | None = None):
        if not blocks:
            raise PipelineConfigError(f"composite {name!r} has no blocks")
        self.name, self.blocks, self._contract = name, list(blocks), contract

    def expanded(self) -> list[tuple[object, tuple[str, ...]]]:
        """Its blocks with nested composites expanded, each with the names of the composites it sits in."""
        out = []
        for b in self.blocks:
            if isinstance(b, Composite):
                out += [(x, (self.name, *path)) for x, path in b.expanded()]
            else:
                out.append((b, (self.name,)))
        return out

    def to_dict(self) -> dict:
        return {**super().to_dict(), "composite": self.name, "blocks": [b.to_dict() for b in self.blocks]}

    def contract(self) -> Contract:
        if self._contract is not None:
            return self._contract
        inner = [contract_of(b) for b, _ in self.expanded()]
        available, reads, adds, replaces = set(), set(), set(), set()
        for c in inner:
            reads |= {p for p in c.reads if not any(a.covers(p) for a in available)}
            available |= c.adds | c.replaces
            adds |= c.adds
            replaces |= c.replaces
        unit_out = inner[-1].output_unit
        return Contract(unit=inner[0].unit, unit_out=unit_out if unit_out != inner[0].unit else None,
                        role=self.role, reads=frozenset(reads), adds=frozenset(adds),
                        replaces=frozenset(replaces - adds))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}: {', '.join(type(b).__name__ for b, _ in self.expanded())}>"
