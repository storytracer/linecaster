"""Conventions: what one source's markup means, as declarative catalog entries (``linecaster.conventions``), and
the machinery every importer shares to apply them.

A **conventions** entry (``ConventionsDoc``) is a list of rules. A rule points at things in the source by a **match**
of its format family (``TreeMatch``: a CSS selector on an HTML or XML tree; ``JsonMatch``: a JSONPath; ``TextMatch``:
a regular expression) and says what they are by a **decision** (``linecaster.conventions.decisions``: remove with a
reason, a block of a role, a note, an edit, ...), which is format-neutral and in the data model's vocabulary. An
entry may extend one other, by id; ``resolve`` turns the chain into one ``ResolvedConventions`` with its
hash. A ``Matcher`` finds a rule's matches in a parsed document; ``Conventions.decide`` gives each matched node the
decision of the first rule that matched it and counts what no rule handled (``Coverage``). How a decision changes
the transcription is the importer's: each format's importer applies the decisions it understands.

Import-light, like ``linecaster.data``: pydantic and lxml; cssselect and a JSONPath implementation when a matcher
needs them.
"""
from linecaster.conventions.apply import Conventions, Coverage
from linecaster.conventions.decisions import DECISIONS, Decision, decision_class
from linecaster.conventions.matchers import JsonMatcher, Matcher, TextMatcher, TreeMatcher
from linecaster.conventions.model import SCHEMA, ConventionsDoc, JsonMatch, Match, Rule, TextMatch, TreeMatch
from linecaster.conventions.resolve import ResolvedConventions, resolve

__all__ = [
    "DECISIONS", "SCHEMA", "Conventions", "ConventionsDoc", "Coverage", "Decision", "JsonMatch", "JsonMatcher",
    "Match", "Matcher", "ResolvedConventions", "Rule", "TextMatch", "TextMatcher", "TreeMatch", "TreeMatcher",
    "decision_class", "resolve",
]
