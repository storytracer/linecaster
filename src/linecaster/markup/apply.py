"""Conventions applied to one document: each node the decision of the first rule that matched it, and what no rule
handled."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .decisions import Decision
from .matchers import Matcher
from .resolve import ResolvedConventions


@dataclass
class Coverage:
    """What conventions handled in one document: matches per rule, and the features of nodes no rule matched
    (``unmapped``: for a tree, the classes of elements no rule matched)."""

    matched: Counter = field(default_factory=Counter)
    unmapped: Counter = field(default_factory=Counter)

    def measurements(self) -> dict[str, Any]:
        """As an annotator's measurements (``linecaster.data.MEASUREMENTS``: ``rules_matched``, ``unmapped``)."""
        return {"rules_matched": dict(sorted(self.matched.items())),
                "unmapped": dict(self.unmapped.most_common())}


@dataclass(frozen=True)
class Conventions:
    """Resolved conventions with the matcher of their format's documents."""

    resolved: ResolvedConventions
    matcher: Matcher

    def __post_init__(self):
        kinds = {r.match.kind for r in self.resolved.rules}
        wrong = sorted(kinds - {self.matcher.kind})
        if wrong:
            raise ValueError(f"conventions {self.resolved.ref} use match kinds {wrong}; this format's matcher reads "
                             f"{self.matcher.kind!r}")

    def decide(self, document) -> tuple[dict[Any, tuple[str, Decision]], Coverage]:
        """Node -> (rule id, decision) for every node a rule matched (the first rule in order wins), and the
        coverage."""
        decided: dict[Any, tuple[str, Decision]] = {}
        cov = Coverage()
        for rule, decision in zip(self.resolved.rules, self.resolved.decisions):
            for node in self.matcher.select(document, rule.match):
                if node not in decided:
                    decided[node] = (rule.id, decision)
                    cov.matched[rule.id] += 1
        for node in self.matcher.nodes(document):
            if node not in decided:
                cov.unmapped.update(self.matcher.features(node))
        return decided, cov
