"""``Composite``: a named group of components with its own outward contract. The builder
(``linecaster.execution.builder``) expands it into its components; the graph and the plan keep the group."""
from __future__ import annotations

from linecaster.errors import PipelineConfigError
from linecaster.core.component import Component
from linecaster.core.contract import Contract, contract_of


class Composite(Component):
    """Groups components under one name with an outward contract of its own.

    Its contract is ``contract`` when given, else derived from its components: what they read that no component inside
    adds, what they add and replace, the first component's unit and the last one's output unit. It is not a datatrove
    step: the builder expands it into its components (nested composites too), and the graph and the plan keep the
    group. ``to_dict()`` is the group: its parameters and its components' dicts.

    Args:
        name: the group's name, in the graph and the plan; ``--until``, ``--after`` and ``--tap-after`` name its
            last component by it.
        components: the components or composites, in order; at least one (``PipelineConfigError`` otherwise).
        contract: the outward contract; ``None``: derived from the components.
    """

    kind = "composite"

    def __init__(self, name: str, components: list, contract: Contract | None = None):
        if not components:
            raise PipelineConfigError(f"composite {name!r} has no components")
        self.name, self.components, self._contract = name, list(components), contract

    def expanded(self) -> list[tuple[object, tuple[str, ...]]]:
        """Its components with nested composites expanded, each with the names of the composites it sits in."""
        out = []
        for b in self.components:
            if isinstance(b, Composite):
                out += [(x, (self.name, *path)) for x, path in b.expanded()]
            else:
                out.append((b, (self.name,)))
        return out

    def to_dict(self) -> dict:
        return {**super().to_dict(), "composite": self.name, "components": [b.to_dict() for b in self.components]}

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
                        kind=self.kind, reads=frozenset(reads), adds=frozenset(adds),
                        replaces=frozenset(replaces - adds))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}: {', '.join(type(b).__name__ for b, _ in self.expanded())}>"
