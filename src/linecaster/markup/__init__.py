"""Conventions: what one source's markup means, as declarative catalog entries (``linecaster.conventions``), and
the machinery every importer shares to apply them.

A **conventions** entry (``ConventionsDoc``) is a list of rules. A rule points at things in the source by a **match**
of its format family (``TreeMatch``: a CSS selector on an HTML or XML tree; ``JsonMatch``: a JSONPath; ``TextMatch``:
a regular expression) and says what they are by a **decision** (``linecaster.markup.decisions``: remove with a
reason, a block of a role, a note, an edit, ...), which is format-neutral and in the data model's vocabulary. An
entry may extend one other, by id; ``resolve`` turns the chain into one ``ResolvedConventions`` with its
hash. A ``Matcher`` finds a rule's matches in a parsed document; ``Conventions.decide`` gives each matched node the
decision of the first rule that matched it and counts what no rule handled (``Coverage``). How a decision changes
the transcription is the importer's: each format's importer applies the decisions it understands.

Import-light, like ``linecaster.data``: pydantic and lxml; cssselect and a JSONPath implementation when a matcher
needs them.
"""
from linecaster.markup.apply import Conventions, Coverage
from linecaster.markup.decisions import DECISIONS, Decision, decision_class
from linecaster.markup.matchers import JsonMatcher, Matcher, TextMatcher, TreeMatcher
from linecaster.markup.model import SCHEMA, ConventionsDoc, JsonMatch, Match, Rule, TextMatch, TreeMatch
from linecaster.markup.resolve import ResolvedConventions, resolve

__all__ = [
    "DECISIONS", "SCHEMA", "Conventions", "ConventionsDoc", "Coverage", "Decision", "JsonMatch", "JsonMatcher",
    "Match", "Matcher", "ResolvedConventions", "Rule", "TextMatch", "TextMatcher", "TreeMatch", "TreeMatcher",
    "decision_class", "resolve",
]
