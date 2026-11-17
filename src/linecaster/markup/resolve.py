"""Layering resolved: an entry and the chain of entries it extends as one ordered list of rules, with its hash.

A child starts from its parent's resolved rules: ``disable`` removes rules by id, a rule with a parent's id replaces
that rule where it stands (or moves it, with ``before``/``after``), a new id is added at the end (or before/after a
rule). Every entry of a chain has the same ``format``. Two readings with the same ``sha256`` applied the same rules.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from linecaster.markup.decisions import Decision, make
from linecaster.markup.model import ConventionsDoc, Rule


class ConventionsError(ValueError):
    """A conventions entry or chain that cannot be resolved."""


@dataclass(frozen=True)
class ResolvedConventions:
    """An entry with its chain resolved: the rules in order, each with its decision; ``chain`` names the entries,
    root first (``base>child``)."""

    format: str
    chain: tuple[str, ...]
    rules: tuple[Rule, ...]
    decisions: tuple[Decision, ...]
    #: the normalizations the source's transcription embodies (``ConventionsDoc.transcription``, the nearest given)
    transcription: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return ">".join(self.chain)

    @property
    def sha256(self) -> str:
        """The hash of what the rules do: format, matches, decisions and their fields, by and order (not why,
        decided, open: they are documentation), and the normalizations the transcription embodies."""
        content = {"format": self.format,
                   "rules": [r.model_dump(mode="json", include={"id", "match", "decision", "params", "by"})
                             for r in self.rules]}
        if self.transcription:
            content["transcription"] = list(self.transcription)
        return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)


def _place(rules: list[Rule], rule: Rule) -> None:
    anchor = rule.before or rule.after
    if anchor is None:
        rules.append(rule)
        return
    k = next((i for i, r in enumerate(rules) if r.id == anchor), None)
    if k is None:
        raise ConventionsError(f"rule {rule.id}: {'before' if rule.before else 'after'} {anchor!r}, which is not a "
                               f"rule here")
    rules.insert(k if rule.before else k + 1, rule)


def resolve(ref: str, entry: Callable[[str], ConventionsDoc]) -> ResolvedConventions:
    """The entry ``ref`` (``id``) with its chain, each entry looked up by ``entry(ref)``."""
    seen: list[str] = []
    stated: list[tuple[str, ...]] = []                     # each entry's transcription, root first

    def walk(r: str) -> tuple[str, tuple[str, ...], list[Rule]]:
        if r in seen:
            raise ConventionsError(f"conventions extend themselves: {' > '.join([*seen, r])}")
        seen.append(r)
        doc = entry(r)
        if doc.transcription is not None:
            stated.insert(0, tuple(doc.transcription))     # the walk goes child first: the child's ends up last
        if doc.extends is None:
            fmt, chain, rules = doc.format, (), []
        else:
            fmt, chain, rules = walk(doc.extends)
            if fmt != doc.format:
                raise ConventionsError(f"{doc.ref} ({doc.format}) extends {doc.extends} ({fmt})")
        ids = {x.id for x in rules}
        missing = sorted(set(doc.disable) - ids)
        if missing:
            raise ConventionsError(f"{doc.ref}: disables rules its parent does not have: {missing}")
        rules = [x for x in rules if x.id not in doc.disable]
        for rule in doc.rules:
            k = next((i for i, x in enumerate(rules) if x.id == rule.id), None)
            if k is not None and not (rule.before or rule.after):
                rules[k] = rule
                continue
            if k is not None:
                del rules[k]
            _place(rules, rule)
        return fmt, (*chain, doc.ref), rules

    fmt, chain, rules = walk(ref)
    decisions = []
    for r in rules:
        try:
            decisions.append(make(r.decision, r.params))
        except (KeyError, ValueError) as e:
            raise ConventionsError(f"rule {r.id} of {chain[-1]}: {e}") from e
    return ResolvedConventions(fmt, chain, tuple(rules), tuple(decisions), stated[-1] if stated else ())
